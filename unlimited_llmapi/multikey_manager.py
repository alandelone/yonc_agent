"""
多密钥 Gemini API 管理器

提供基于 DSPy 的多 API Key 轮换机制，自动处理速率限制和每日配额。
支持从外部 JSON 文件加载密钥列表，方便被其他模块导入使用。

用法示例:
    from unlimited_llmapi.multikey_manager import configure_dspy

    # 一行配置，自动读取 api_keys.json
    lm = configure_dspy()

    # 或自定义参数
    lm = configure_dspy(model="gemini/gemini-2.0-flash", rpm=30, rpd=500)
"""

import time
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import dspy
from dspy.clients.lm import LM

# 默认 Gemini 免费层限制
DEFAULT_LIMITS = {
    "RPM": 5,              # 每分钟请求数
    "RPD": 20,             # 每日请求数
    "MIN_INTERVAL": 60.0 / 5  # 请求间最小间隔（秒）
}

# 密钥使用情况持久化文件（与 api_keys.json 同目录）
_MODULE_DIR = Path(__file__).parent.absolute()
USAGE_FILE = _MODULE_DIR / "key_usage.json"
DEFAULT_KEYS_FILE = _MODULE_DIR / "api_keys.json"


def load_api_keys(keys_file: str | Path | None = None) -> list[str]:
    """
    从 JSON 文件加载 API 密钥列表。

    Args:
        keys_file: JSON 文件路径，默认为同目录下的 api_keys.json

    Returns:
        API 密钥字符串列表
    """
    path = Path(keys_file) if keys_file else DEFAULT_KEYS_FILE

    if not path.exists():
        raise FileNotFoundError(
            f"密钥配置文件未找到: {path}\n"
            f"请创建 api_keys.json 文件，格式参考 README。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keys = [entry["key"] for entry in data.get("keys", [])]
    if not keys:
        raise ValueError(f"密钥配置文件中未找到有效密钥: {path}")

    return keys


def load_config(keys_file: str | Path | None = None) -> dict:
    """
    从 JSON 文件加载完整配置（密钥 + 默认参数）。

    Returns:
        包含 keys, labels, default_model, default_rpm, default_rpd 的字典
    """
    path = Path(keys_file) if keys_file else DEFAULT_KEYS_FILE

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keys_data = data.get("keys", [])
    return {
        "keys": [entry["key"] for entry in keys_data],
        "labels": {entry["key"]: entry.get("label", f"key_{i+1}") for i, entry in enumerate(keys_data)},
        "default_model": data.get("default_model", "gemini/gemini-1.5-flash"),
        "default_rpm": data.get("default_rpm", 5),
        "default_rpd": data.get("default_rpd", 1000),
    }


class SmartMultiKeyLM(LM):
    """
    智能多密钥 LM 包装器。

    自动在多个 API Key 之间轮换，处理速率限制（RPM）和每日配额（RPD），
    遇到 429/quota 错误时自动切换到下一个可用密钥。
    """

    def __init__(
        self,
        model: str,
        api_keys: list[str],
        limits: dict | None = None,
        labels: dict[str, str] | None = None,
        **kwargs
    ):
        """
        Args:
            model: 模型名称（如 "gemini/gemini-3-flash-preview"）
            api_keys: API 密钥列表
            limits: 可选的速率限制覆盖（RPM, RPD）
            labels: 可选的密钥标签映射 {key: label}，用于日志输出
            **kwargs: 传递给 dspy.LM 的额外参数（temperature, max_tokens 等）
        """
        # 用第一个密钥初始化父类
        super().__init__(model, api_key=api_keys[0], **kwargs)

        self.api_keys = api_keys
        self.clients = {}

        # 应用自定义限制或默认值
        self.limits = limits if limits else DEFAULT_LIMITS.copy()
        self.limits["MIN_INTERVAL"] = 60.0 / self.limits["RPM"]

        # 密钥标签映射，方便日志阅读
        if labels:
            self.key_labels = labels
        else:
            self.key_labels = {k: f"Key#{i+1}" for i, k in enumerate(api_keys)}

        # 为每个密钥初始化独立的 LM 客户端
        for key in api_keys:
            self.clients[key] = dspy.LM(model, api_key=key, **kwargs)

        self.usage_data = self._load_usage()

    def _load_usage(self) -> dict:
        """从磁盘加载密钥使用记录，新的一天自动重置配额。"""
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 新的一天（UTC），重置每日计数
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if data.get("date") != today:
                    print(f"[MultiKey] 新的一天 ({today})，重置所有密钥配额。")
                    return self._fresh_usage(today)

                # 确保所有密钥都有记录
                for k in self.api_keys:
                    if k not in data.get("keys", {}):
                        data.setdefault("keys", {})[k] = {"daily_reqs": 0, "last_used": 0}
                return data
            except (json.JSONDecodeError, KeyError):
                pass  # 文件损坏，重新开始

        return self._fresh_usage()

    def _fresh_usage(self, date: str | None = None) -> dict:
        """创建全新的使用记录。"""
        return {
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "keys": {k: {"daily_reqs": 0, "last_used": 0} for k in self.api_keys}
        }

    def _save_usage(self) -> None:
        """持久化使用记录到磁盘。"""
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.usage_data, f, indent=2)

    def _get_available_key(self) -> tuple[str | None, float]:
        """
        选择最佳可用密钥。

        Returns:
            (key, wait_time) 元组。如果所有密钥配额耗尽，key 为 None。
        """
        now = time.time()

        # 第一轮：找到一个立即可用的密钥
        for key in self.api_keys:
            stats = self.usage_data["keys"][key]
            if stats["daily_reqs"] >= self.limits["RPD"]:
                continue
            if (now - stats["last_used"]) >= self.limits["MIN_INTERVAL"]:
                return key, 0

        # 第二轮：所有密钥都在冷却中，找等待时间最短的
        best_key = None
        min_wait = float("inf")

        for key in self.api_keys:
            stats = self.usage_data["keys"][key]
            if stats["daily_reqs"] >= self.limits["RPD"]:
                continue
            wait = self.limits["MIN_INTERVAL"] - (now - stats["last_used"])
            if wait < min_wait:
                min_wait = wait
                best_key = key

        return best_key, max(0, min_wait)

    def __call__(self, prompt=None, messages=None, **kwargs):
        """发送请求，自动轮换密钥和处理限流。"""
        # 提取当前重试次数，默认0
        retry_count = kwargs.pop('__multi_key_retry', 0)

        key, wait_time = self._get_available_key()

        if key is None:
            raise RuntimeError("所有 API 密钥已达每日限额，无法继续请求。")

        label = self.key_labels.get(key, key[:12])

        if wait_time > 0:
            print(f"  [Throttling] 所有密钥冷却中，{label} 将在 {wait_time:.1f}s 后就绪...")
            time.sleep(wait_time)

        client = self.clients[key]

        try:
            current_count = self.usage_data["keys"][key]["daily_reqs"] + 1
            print(f"[MultiKey] 请求中... ({label} | 今日: {current_count}/{self.limits['RPD']})")

            response = client(prompt=prompt, messages=messages, **kwargs)

            # 更新使用记录
            self.usage_data["keys"][key]["daily_reqs"] += 1
            self.usage_data["keys"][key]["last_used"] = time.time()
            self._save_usage()

            self.history.append(client.history[-1])
            return response

        except Exception as e:
            error_msg = str(e).lower()
            if any(x in error_msg for x in ["429", "quota", "resource_exhausted"]):
                print(f"  [MultiKey] {label} 触发受限 (429/Quota) 自动处理: {str(e).splitlines()[0][:100]}")
                self.usage_data["keys"][key]["last_used"] = time.time()
                
                # 如果明确是配额耗尽，将当前key的本地日限额直接拉满，避免今天再次使用
                if "quota" in error_msg or "resource_exhausted" in error_msg:
                    print(f"  [MultiKey] 判定为配额已尽，今日下线 {label}...")
                    self.usage_data["keys"][key]["daily_reqs"] = self.limits["RPD"]
                
                self._save_usage()
                
                # 限制最大连续重试次数，防止全部key都在遭遇429时死循环
                max_retries = len(self.api_keys) * 3
                if retry_count < max_retries:
                    kwargs['__multi_key_retry'] = retry_count + 1
                    time.sleep(1.5)  # 强制稍微退避一下
                    return self.__call__(prompt, messages, **kwargs)
                else:
                    print(f"  [MultiKey] 达到最大重试次数 ({max_retries})，抛出异常。")
                    raise
            else:
                raise


def get_gemini_manager(
    api_keys: list[str],
    model: str = "gemini/gemini-1.5-flash",
    rpm: int = 5,
    rpd: int = 1000,
    labels: dict[str, str] | None = None,
    **kwargs
) -> SmartMultiKeyLM:
    """
    工厂函数：快速创建一个配置好的多密钥 LM 管理器。

    Args:
        api_keys: API 密钥列表
        model: 模型名称
        rpm: 每分钟请求数限制
        rpd: 每日请求数限制
        labels: 可选的密钥标签
        **kwargs: 传递给 LM 的额外参数

    Returns:
        配置好的 SmartMultiKeyLM 实例
    """
    custom_limits = {
        "RPM": rpm,
        "RPD": rpd,
        "MIN_INTERVAL": 60.0 / rpm,
    }
    return SmartMultiKeyLM(model, api_keys, limits=custom_limits, labels=labels, **kwargs)


def configure_dspy(
    keys_file: str | Path | None = None,
    model: str | None = None,
    rpm: int | None = None,
    rpd: int | None = None,
    **kwargs
) -> SmartMultiKeyLM:
    """
    一站式配置函数：从配置文件加载密钥并配置 DSPy。

    这是推荐的入口函数。调用后 DSPy 即可直接使用。

    Args:
        keys_file: 密钥 JSON 文件路径（默认同目录下 api_keys.json）
        model: 覆盖默认模型名称
        rpm: 覆盖默认 RPM
        rpd: 覆盖默认 RPD
        **kwargs: 传递给 LM 的额外参数

    Returns:
        配置好的 SmartMultiKeyLM 实例

    用法:
        from unlimited_llmapi.multikey_manager import configure_dspy
        lm = configure_dspy()
        # DSPy 已配置完毕，直接使用即可
        result = dspy.ChainOfThought("question -> answer")(question="Hello")
    """
    config = load_config(keys_file)

    lm = get_gemini_manager(
        api_keys=config["keys"],
        model=model or config["default_model"],
        rpm=rpm or config["default_rpm"],
        rpd=rpd or config["default_rpd"],
        labels=config["labels"],
        **kwargs,
    )

    dspy.configure(lm=lm)
    print(f"[MultiKey] DSPy 已配置: {model or config['default_model']} | "
          f"{len(config['keys'])} 个密钥 | RPM={rpm or config['default_rpm']}")
    return lm


# --- 包 __init__ 导出 ---
__all__ = [
    "SmartMultiKeyLM",
    "get_gemini_manager",
    "configure_dspy",
    "load_api_keys",
    "load_config",
]


if __name__ == "__main__":
    print("--- 多密钥 Gemini Manager 测试 ---")

    # 从 api_keys.json 自动加载并配置
    lm = configure_dspy()

    print("\n[测试] 发送 3 个快速请求：")
    try:
        for i in range(1, 4):
            print(f"\n--- 请求 {i} ---")
            try:
                dspy.ChainOfThought("question -> answer")(question=f"Test Q{i}")
            except Exception as e:
                print(f"(预期错误): {e}")
    except KeyboardInterrupt:
        print("\n测试被用户中断。")

    print("\n完成。查看 key_usage.json 了解使用统计。")
