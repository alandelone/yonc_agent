# Hermes `yonc` 部署与回滚

## 首次部署或更新

在 PowerShell 中明确指定两个仓库和正式数据库：

```powershell
.\scripts\deploy-hermes.ps1 `
  -UumaRoot C:\test_codespace\UuMA `
  -DatabasePath C:\test_codespace\yonc_agent\data\project_graph.sqlite3 `
  -Port 8765
```

脚本先备份数据库和被管理的 profile 文件，再安装固定依赖、构建 UI、执行加法迁移、创建或更新 `yonc` profile、安装 SOUL/skill/guard/audit、启动 loopback 服务、重启 gateway 并验证数据库身份。二次执行复用数据库与 profile；不会部署 Scholar、KAG 或硬件组件。

若依赖已安装，可加 `-SkipInstall`。若 gateway 由外部服务管理，可加 `-SkipGatewayRestart`，随后由管理员重启并运行检查。

## 使用

- Hermes：选择 `yonc` profile 后直接对话。
- UI：打开 `http://127.0.0.1:<port>`，拆分编辑会自动保存草案；只有 **Accept & Commit** 写入正式图。
- 日志：`data/runtime/logs/`。
- 部署清单：`data/deployments/<timestamp>/manifest.json`。

## 检查

```powershell
.\scripts\check-hermes-deployment.ps1 `
  -UumaRoot C:\test_codespace\UuMA `
  -DatabasePath C:\test_codespace\yonc_agent\data\project_graph.sqlite3 `
  -Port 8765
```

检查失败时不要宣告部署完成。先核对端口、健康响应里的数据库路径、profile config 中的两个 MCP 和 guard 插件。

## 回滚

```powershell
.\scripts\rollback-hermes-deployment.ps1 -ManifestPath <manifest.json>
```

回滚会停止本次托管的 Yonc 进程并恢复 profile/config 文件。它不会覆盖、删除或回退项目数据库。数据库备份保存在部署目录，只有确认没有更新后的有效写入且人工决定恢复时才单独使用。
