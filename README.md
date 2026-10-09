# AgentDock Clone v3 — ChatGPT 网页直控本机

架构：ChatGPT 网页(自定义连接器) → Cloudflare Tunnel → 本地 FastMCP server → 本机文件/命令/回收站

## 权限模型：完全放开 + 单一硬删除护栏

- `run_command` / `write_file` / `edit_file` **无需任何审批**，直接执行
- **硬删除全部拦截**（不可恢复的操作不给模型留接口）：
  `Remove-Item` `rm` `del` `rd` `rmdir` `erase` `ri`(别名) `Clear-Content`
  `.NET ::Delete` `os.remove` `shutil.rmtree` `Path.unlink`
  `robocopy /MIR|/PURGE` `git clean -f` `git reset --hard` `git checkout --`
  `Clear-RecycleBin` `vssadmin/wmic delete` `format` `diskpart` `cipher /w` `fsutil`
  以及**反引号拆词、变量字符串拼接、base64 内嵌载荷**三种绕过手法
- 删除只有一条路：`recycle_delete` → 文件进 **Windows 回收站**，随时可恢复
- 文件读写限定在工作区白名单内（`AGENTDOCK_ROOTS`）

## 工具清单（8 个）

| 工具 | 作用 |
|---|---|
| `run_command` | 执行 PowerShell（硬删除除外） |
| `recycle_delete` | 移入回收站，支持 `a\|b\|c` 多路径 |
| `read_file` | 读文件，带行号，支持 offset/limit |
| `write_file` | 新建/覆盖写文件 |
| `edit_file` | 精确替换（要求 old_string 唯一） |
| `list_dir` | 列目录 |
| `search_files` | 工作区内按文件名正则搜索 |

> v3.1 移除了 `ask_codex`（本机未安装 Codex CLI，属于死工具）。

## 启动

```powershell
pip install fastmcp send2trash
# 窗口 A：MCP server
$env:AGENTDOCK_SECRET='<你的secret>'; python scripts\server.py
# 窗口 B：隧道
cloudflared tunnel --url http://127.0.0.1:8322 run agentdock
```

可用环境变量：`AGENTDOCK_SECRET`、`AGENTDOCK_PORT`（默认 8322）、`AGENTDOCK_ROOTS`、`AGENTDOCK_LOG_DIR`

ChatGPT 侧：设置 → 应用与连接器 → 高级 → 开发者模式 → 创建连接器，URL 填
`https://<你的域名>/<SECRET>/mcp`，认证选「无身份验证」。

## 测试

```powershell
# 1) 护栏单元测试（纯函数，不需要启动服务，秒级完成）
python scripts\guard_test.py

# 2) 端到端测试（需要先启动 server）
$env:AGENTDOCK_SECRET='<你的 secret>'
python scripts\smoke_test.py 8322       # 功能：7 工具、护栏、回收站
python scripts\bypass_test.py 8322     # 对抗：33 个绕过向量 + 12 个正常向量
```

当前实测：**33/33 绕过全部拦截，12/12 正常命令零误杀**。

向量表只有一份，定义在 `guard_test.py`，`bypass_test.py` 直接 import复用——
新增绕过手法只改一处，两种测试同步生效。

## 安全提醒

- `SECRET` 只写在你自己机器的 `scripts/start.ps1`（已被 `.gitignore` 排除）；
  测试脚本一律从环境变量 `AGENTDOCK_SECRET` 读取，不要把真实值写进代码或提交。
- MCP 路径里的 SECRET 是唯一的鉴权手段，一旦泄露，别人就能直接调你的本机工具。

## 已知边界（诚实说明）

护栏是**命令文本级**的检查，能挡住已知手法，但挡不住运行时动态构造：
例如模型用字符码拼出 `Remove-Item`、用 PowerShell 远程执行、或用「写一个覆盖脚本」变相删除。
真要强保证，还是靠 Windows 文件权限或虚拟机隔离。

## 日志

`logs/agentdock-YYYY-MM-DD.jsonl`，每条含 ts / session / tool / ok / duration_ms / args / result_bytes。