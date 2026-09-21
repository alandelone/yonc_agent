# Yonc × UuMA × Hermes 集成契约

版本：1.0（2026-09-21）

## 权威边界

- Yonc API 是项目图与拆分草案的唯一写入边界。
- UuMA 是 Agent task/run、Direct Run、停止、结果与审计的唯一控制边界。
- Hermes `yonc` 仅拥有 `uuma-worker` 与 `yonc-project`，没有 Control MCP、通用终端、电脑控制或自主委派权限。

## 数据库与服务身份

部署必须显式传入已存在的 `YONC_GRAPH_DB`。`GET /api/v2/health` 返回规范化数据库路径、不可逆短身份、schema、图版本和节点数；启动与检查脚本会比对目标路径，端口上已有其他服务时拒绝接管。

## 会话与提交

每个 UI 拆分拥有持久 `split_session_id` 和不可变 proposal version。编辑、聊天和校验只保存草案。缺席节点不是删除；移除必须在 `suggested_removals` 中明确列出，接受后也保留节点和历史，已完成节点拒绝移除。

UI 用户通过 **Accept & Commit** 明确提交。Agent 写入同时要求：

1. Hermes 进程持有、不暴露给模型的服务 token；
2. 可信本地 UI 为具体 session/proposal/graph version 创建的单次授权；
3. 授权未过期、未消费且版本仍一致。

重试同一授权会被拒绝；图或提案变化会使授权失效。

## 运行关联

直接对话和 UI 拆分均先通过 Worker MCP 注册运行。Yonc 对话读取项目图，但 Agent run 成功不改变用户项目节点的完成状态。迟到或失败结果只进入 UuMA 运行记录，不回退已提交项目状态。
