<div align="center">

# YoncAgent

专为 INTP + ADHD 人群设计的智能 Notion 任务管理与增强系统。

[![GitHub stars](https://img.shields.io/github/stars/alandelone/yonc_agent?style=for-the-badge)](https://github.com/alandelone/yonc_agent/stargazers)
[![Python](https://img.shields.io/badge/python-3.10+-blue?style=for-the-badge&logo=python&logoColor=white)]()

</div>

## 这是什么？ (What is this?)

YoncAgent 基于 Python，整合了 DSPy 与 Gemini 多模型能力，旨在辅助前额叶功能。它将抽象宏大的目标强制“降维”拆解为可执行的物理动作，帮助你摆脱面对模糊任务时的卡壳状态。
- **WBS 4 级任务分解**：精准将任务划分为 Deliverables → Work Packages → Activities → Atomic Actions。
- **智能模式判定**：自动区分项目类任务（WBS 确定性分解）与探索类任务（OKR 愿景分解）。
- **自动化同步引擎**：无缝拉取 Notion 页面内容，进行 Diff 比对防重复写入，并记录偏好习惯以供长期微调。
- **多 Key 负载均衡**：内置 API Key 切换机制，突破单 Key 限流瓶颈。

## 快速开始 (Quick Start)

在不到一分钟内将 Agent 运行起来。

```bash
# 1. 克隆项目
git clone https://github.com/alandelone/yonc_agent.git
cd yonc_agent

# 2. 安装依赖
pip install -r requirements.txt
```

**环境变量配置**  
在根目录创建 `.env` 文件：
```env
NOTION_API_KEY=secret_xxx
YONCTASK_CONFIG_PAGE_ID=page_id_xxx
```

**API 负载均衡配置**  
在 `unlimited_llmapi/api_keys.json` 中添加你的 Gemini Keys：
```json
[
  {"key": "YOUR_KEY_1", "model": "gemini-1.5-flash"},
  {"key": "YOUR_KEY_2", "model": "gemini-1.5-flash"}
]
```

**运行核心指令**  
```bash
python main.py sync   # 同步 Notion 状态
python main.py tag    # 智能识别并补充标签 (Themes & Modes)
python main.py split  # 执行 4 级 WBS 任务拆解
python main.py push-sync  # 不调用 LLM，按规则修正后直接回写 Notion
```

`push-sync` 会在回写前增加两层保障：
- 不管 LLM 结果如何，都会再做一层规则修正：自动补 Theme（按 context/邻近段落）；WBS 默认保持空，除非已有值或由 LLM 产出（`llm_pipeline.py`）。
- 回写 Notion 时会重排标题富文本：`WBS emoji -> Theme(code+bold+color) -> Mode(按配置样式) -> 其他emoji -> 清理后的标题`（`sync_engine.py`）。

## 项目结构 (Project Structure)

```text
__pycache__/
data/
tests/
unlimited_llmapi/
README.md
completion.py
config.py
config_reader.py
llm_pipeline.py
main.py
notion_client.py
requirements.txt
state_manager.py
sync_engine.py
task_reader.py
```

## 核心文档 (Documentation)

| 核心组件 | 说明 |
|-----------|-------------|
| `main.py` | CLI 入口，支持 `sync`, `tag`, `split` 与 `poll` 核心指令。 |
| `llm_pipeline.py` | **核心大脑**。定义 WBS 分类器与各层级精炼器，使用 DSPy 进行安全性约束。 |
| `sync_engine.py` | 负责处理 Notion Block 的深度写入以及本地状态同步，包含防重复逻辑。 |
| `config_reader.py` | 解析 Notion 配置页，支持 Task Theme、优先级的颜色与 Emoji 匹配。 |
| `unlimited_llmapi/` | **基础设施层**。管理多模型 API Key 的轮询切换、报错重试与 Token 优化。 |
| `state_manager.py` | 本地化 JSON 文件持久保存，确保同步过程中数据的原子性。 |

## 🎯 WBS 任务分解方法论

系统严格遵循以下 4 级分层逻辑，确保任务“零决断点”：

| 层级 (Level) | 名称 | 核心定义 | 语法规范 |
| :--- | :--- | :--- | :--- |
| **L1** | **Goal** | 最终交付的目标或愿景 | 名词/动名词 |
| **L2** | **Deliverable** | 为达成 L1 所需的核心组件 | **名词** (MECE原则) |
| **L3** | **Work Package** | 完成 Deliverable 的具体工作包 | **名词** |
| **L4** | **Activity** | 最小颗粒度的执行步骤 | **动词 + 物理动作** |
| **Atomic** | **Refinement** | 针对 L4 的执行细节增强 | 预测耗时 (<=2h) |

> [!TIP]
> **OKR 模式**：当 L1 任务被定义为探索性（OKR）时，系统不仅生成分解项，还会自动提取 **Objective** 与 **Key Results** 以保持目标对齐。

## 参与贡献 (Contributing)

本项目通过构建“外挂前额叶”极大辅助了 ADHD 人群的任务执行。如果你想帮助优化分解算法或提交增强功能，欢迎提交 Pull Request。
本地你可以通过修改 `tunable.jsonl` 来调整分解算法的个性化参数。

<a href="https://github.com/alandelone/yonc_agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=alandelone/yonc_agent" />
</a>

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=alandelone/yonc_agent&type=Date)](https://star-history.com/#alandelone/yonc_agent&Date)

</div>
