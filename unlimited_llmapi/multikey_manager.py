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
    从 JSON 文件加载完整配置（密钥 + 模型列表）。

    Returns:
        包含 keys, labels, models, light_models 的字典
    """
    path = Path(keys_file) if keys_file else DEFAULT_KEYS_FILE

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    keys_data = data.get("keys", [])

    # 解析 light_models：支持新格式（对象数组）和旧格式（单个模型名字符串）
    light_models_raw = data.get("light_models")  # 新格式优先
    if light_models_raw is None:
        # 向后兼容旧 light_model 字段
        legacy = data.get("light_model")
        if isinstance(legacy, str) and legacy:
            light_models_raw = [legacy]

    return {
        "keys": [entry["key"] for entry in keys_data],
        "labels": {entry["key"]: entry.get("label", f"key_{i+1}") for i, entry in enumerate(keys_data)},
        "models": data.get("models", []),
        "light_models": light_models_raw,  # list[dict] | list[str] | None
    }


class SmartMultiKeyLM(LM):
    """
    智能多密钥 LM 包装器。

    支持多模型回退：当第一个模型的所有密钥配额用尽时，自动切换到下一个模型。
    """

    def __init__(
        self,
        api_keys: list[str],
        models_config: list[dict],
        labels: dict[str, str] | None = None,
        **kwargs
    ):
        """
        Args:
            api_keys: API 密钥列表
            models_config: 模型配置列表 [{"name": "...", "rpm": 5, "rpd": 20}]
            labels: 可选的密钥标签映射 {key: label}
            **kwargs: 传递给 dspy.LM 的额外参数
        """
        if not models_config:
            raise ValueError("至少需要配置一个模型。")

        self.api_keys = api_keys
        self.models_config = models_config
        self.kwargs = kwargs
        
        # 预计算每个模型的限制
        for m in self.models_config:
            m["min_interval"] = 60.0 / m.get("rpm", 5)

        # Remove 'model' and 'api_key' from kwargs to avoid conflict with positional arguments in LM.__init__
        kwargs.pop("model", None)
        kwargs.pop("api_key", None)
        
        self.kwargs = kwargs

        # 用第一个模型初始化父类
        super().__init__(models_config[0]["name"], api_key=api_keys[0], **kwargs)

        # 父类 LM.__init__ 会将 api_key 合并进 self.kwargs，
        # 导致后续 dspy.LM(m_name, api_key=key, **self.kwargs) 出现重复参数。
        # 必须在父类初始化后清理掉。
        self.kwargs.pop("api_key", None)

        self.key_labels = labels or {k: f"Key#{i+1}" for i, k in enumerate(api_keys)}

        # 为每个密钥和模型初始化独立的 LM 客户端（按需初始化）
        self.clients = {}  # {(model_name, key): LM_instance}

        self.usage_data = self._load_usage()

    def _load_usage(self) -> dict:
        """从磁盘加载密钥使用记录，新的一天自动重置配额。"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 如果日期不同，或者数据格式是旧的，则重置
                if data.get("date") != today or "usage" not in data:
                    print(f"[MultiKey] 新的一天 ({today}) 或格式更新，重置统计。")
                    return self._fresh_usage(today)

                return data
            except (json.JSONDecodeError, KeyError, Exception):
                pass

        return self._fresh_usage(today)

    def _fresh_usage(self, date: str) -> dict:
        """创建全新的使用记录，支持多模型。"""
        usage = {}
        for m_cfg in self.models_config:
            m_name = m_cfg["name"]
            usage[m_name] = {k: {"daily_reqs": 0, "last_used": 0} for k in self.api_keys}
            
        return {
            "date": date,
            "usage": usage
        }

    def _save_usage(self) -> None:
        """持久化使用记录到磁盘。"""
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.usage_data, f, indent=2)

    def _get_available_key(self, model_name: str, rpm_limit: int, rpd_limit: int) -> tuple[str | None, float]:
        """
        在指定模型下选择最佳可用密钥。
        """
        now = time.time()
        min_interval = 60.0 / rpm_limit
        
        model_usage = self.usage_data["usage"].get(model_name, {})
        if not model_usage:
            # 如果新模型没在 usage 里，动态加上
            model_usage = {k: {"daily_reqs": 0, "last_used": 0} for k in self.api_keys}
            self.usage_data["usage"][model_name] = model_usage

        # 第一轮：找到一个立即可用的密钥
        for key in self.api_keys:
            stats = model_usage.get(key, {"daily_reqs": 0, "last_used": 0})
            if stats["daily_reqs"] >= rpd_limit:
                continue
            if (now - stats["last_used"]) >= min_interval:
                return key, 0

        # 第二轮：找等待时间最短的
        best_key = None
        min_wait = float("inf")

        for key in self.api_keys:
            stats = model_usage.get(key, {"daily_reqs": 0, "last_used": 0})
            if stats["daily_reqs"] >= rpd_limit:
                continue
            wait = min_interval - (now - stats["last_used"])
            if wait < min_wait:
                min_wait = wait
                best_key = key

        return best_key, max(0, min_wait)

    def __call__(self, prompt=None, messages=None, **kwargs):
        """发送请求，支持模型回退。"""
        # 内部重试标记
        retry_count = kwargs.pop('__multi_key_retry', 0)
        current_model_idx = kwargs.pop('__current_model_idx', 0)

        if current_model_idx >= len(self.models_config):
            raise RuntimeError("所有配置的模型及其 API 密钥已达每日限额。")

        m_cfg = self.models_config[current_model_idx]
        m_name = m_cfg["name"]
        
        key, wait_time = self._get_available_key(m_name, m_cfg["rpm"], m_cfg["rpd"])

        # 如果当前模型所有密钥都不可用，尝试下一个模型
        if key is None:
            if current_model_idx + 1 < len(self.models_config):
                next_model = self.models_config[current_model_idx + 1]["name"]
                print(f"  [MultiKey] 模型 {m_name} 已达限额，切换到回退模型: {next_model}")
                kwargs['__current_model_idx'] = current_model_idx + 1
                return self.__call__(prompt, messages, **kwargs)
            else:
                raise RuntimeError(f"所有 API 密钥及模型已达每日限额，最后尝试的模型是: {m_name}")

        label = self.key_labels.get(key, key[:12])

        if wait_time > 0:
            print(f"  [Throttling] {m_name} 冷却中，{label} 将在 {wait_time:.1f}s 后就绪...")
            time.sleep(wait_time)

        # 获取或初始化客户端
        client_key = (m_name, key)
        if client_key not in self.clients:
            self.clients[client_key] = dspy.LM(m_name, api_key=key, **self.kwargs)
        client = self.clients[client_key]

        try:
            current_count = self.usage_data["usage"][m_name][key]["daily_reqs"] + 1
            print(f"[MultiKey] 请求中... (模型: {m_name} | Key: {label} | 今日: {current_count}/{m_cfg['rpd']})")

            response = client(prompt=prompt, messages=messages, **kwargs)

            # 更新使用记录
            self.usage_data["usage"][m_name][key]["daily_reqs"] += 1
            self.usage_data["usage"][m_name][key]["last_used"] = time.time()
            self._save_usage()

            self.history.append(client.history[-1])
            return response

        except Exception as e:
            error_msg = str(e).lower()
            # 瞬态错误：429 限流 / 配额耗尽 / 503 过载
            if any(x in error_msg for x in ["429", "quota", "resource_exhausted", "503", "unavailable", "high demand", "overloaded"]):
                print(f"  [MultiKey] {m_name} | {label} 触发受限: {str(e)}")
                self.usage_data["usage"][m_name][key]["last_used"] = time.time()
                
                if "quota" in error_msg or "resource_exhausted" in error_msg:
                    print(f"  [MultiKey] 判定为模型 {m_name} 的配额已尽，今日下线 {label}...")
                    self.usage_data["usage"][m_name][key]["daily_reqs"] = m_cfg["rpd"]
                
                self._save_usage()
                
                # 重试（可能触发切换 Key 或切换模型）
                max_retries = len(self.api_keys) * 2
                if retry_count < max_retries:
                    kwargs['__multi_key_retry'] = retry_count + 1
                    kwargs['__current_model_idx'] = current_model_idx # 保持当前模型索引，逻辑会自动在 _get_available_key 中切换 key 或切换模型
                    time.sleep(1.0)
                    return self.__call__(prompt, messages, **kwargs)
                else:
                    raise
            else:
                raise




def configure_dspy(
    keys_file: str | Path | None = None,
    models: list[dict] | None = None,
    **kwargs
) -> SmartMultiKeyLM:
    """
    一站式配置函数：从配置文件加载密钥并配置 DSPy。

    Args:
        keys_file: 密钥 JSON 文件路径
        models: 手动提供模型列表，覆盖配置文件
        **kwargs: 传递给 LM 的额外参数
    """
    config = load_config(keys_file)
    
    lm = SmartMultiKeyLM(
        api_keys=config["keys"],
        models_config=models or config["models"],
        labels=config["labels"],
        **kwargs,
    )

    dspy.configure(lm=lm)
    m_names = [m["name"].split("/")[-1] for m in (models or config["models"])]
    print(f"[MultiKey] DSPy 已配置 | 密钥数: {len(config['keys'])} | 模型列表: {' -> '.join(m_names)}")
    return lm


def configure_dspy_light(
    keys_file: str | Path | None = None,
    **kwargs
) -> SmartMultiKeyLM:
    """
    配置专用于轻量级任务的 LM（如 compaction / CondenseTaskDescription）。

    模型回退顺序：
      1. light_models（配置文件中 light_models 字段，支持多模型各自独立 rpm/rpd）
      2. 若 light_models 配额全部耗尽，自动回退到 models 列表中未出现的其他模型

    此 LM **不会**调用 dspy.configure()，需要用 dspy.context(lm=light_lm) 局部使用。

    Args:
        keys_file: 密钥 JSON 文件路径，默认 api_keys.json
        **kwargs: 传递给 LM 的额外参数
    """
    config = load_config(keys_file)
    all_models: list[dict] = config["models"]
    light_models_raw = config.get("light_models")

    if light_models_raw:
        # 标准化：每个条目可能是 dict（新格式）或 str（旧格式兼容）
        light_chain: list[dict] = []
        for entry in light_models_raw:
            if isinstance(entry, dict):
                light_chain.append(entry)
            elif isinstance(entry, str):
                # 旧格式：纯模型名，尝试从 models 列表中找匹配配置
                matched = next((m for m in all_models if m["name"] == entry), None)
                light_chain.append(matched or {"name": entry, "rpm": 14, "rpd": 500})

        # 把 models 列表中未出现在 light_chain 里的模型追加为最终回退
        light_names = {m["name"] for m in light_chain}
        others = [m for m in all_models if m["name"] not in light_names]
        final_models = light_chain + others
    else:
        # 没有配置 light_models，直接复用主模型列表
        final_models = all_models

    lm = SmartMultiKeyLM(
        api_keys=config["keys"],
        models_config=final_models,
        labels=config["labels"],
        **kwargs,
    )

    short_names = [m["name"].split("/")[-1] for m in final_models]
    print(f"[MultiKey-Light] 轻量 LM 已创建 | 密钥数: {len(config['keys'])} | 模型回退: {' -> '.join(short_names)}")
    return lm


# Alias for backward compatibility
get_gemini_manager = configure_dspy


# --- 包 __init__ 导出 ---
__all__ = [
    "SmartMultiKeyLM",
    "get_gemini_manager",
    "configure_dspy",
    "configure_dspy_light",
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
