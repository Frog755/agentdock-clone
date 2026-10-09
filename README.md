# AgentDock Clone v3.3 — ChatGPT 网页直控本机

架构：ChatGPT 网页(自定义连接器) → Cloudflare Tunnel → 本地 FastMCP 网关服务 → 本机文件/命令/回收站

## 核心防护体系（三大护栏）

1. **API Gateway 并发互斥与防卡死**：
   - **串行互斥锁（Concurrency Gate）**：本地命令执行严格单任务互斥，杜绝子进程风暴跑满 CPU。
   - **令牌桶限流（Rate Limiter）**：按 Session 隔离，默认容量 3 次突发、补充速率 1 次/秒；模型幻觉陷入重试死循环时自动拦截（返回 `ERROR [RATE_LIMITED]`），打断调用风暴。
   - **看门狗子进程树强杀（Process Watchdog）**：命令超时时自动触发 `taskkill /F /T` 递归清理整个子进程树，不留任何孤儿游离进程。

2. **硬删除静态阻断网**：
   - **硬删除全部拦截**（不可恢复的操作不给模型留接口）：
     `Remove-Item` `rm` `del` `rd` `rmdir` `erase` `ri`(别名) `Clear-Content`
     `.NET ::Delete` `os.remove` `shutil.rmtree` `Path.unlink` `fs.rmSync`
     `robocopy /MIR|/PURGE` `git clean -f` `git reset --hard` `git checkout --` `git restore`
     `Clear-RecycleBin` `vssadmin/wmic delete` `format` `diskpart` `cipher /w` `fsutil`
   - **绕过手法归一化**：自动折叠反引号拆词（``Remove`-Item``）、字符串拼接（`'Remove'+'-Item'`）、base64 嵌套载荷。

3. **安全删除与工作区约束**：
   - 唯一合法删除通道：`recycle_delete` → 文件直接送入 **Windows 回收站**，随时可逆恢复。
   - 文件系统限定：文件读写限死在 `AGENTDOCK_ROOTS` 白名单内。

## 工具清单（7 个）

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

# 2) 网关与并发限流测试（需要启动 server）
$env:AGENTDOCK_SECRET='<你的 secret>'
python scripts\gateway_test.py 8322    # 网关：并发互斥锁 + 令牌桶突发限流测试

# 3) 端到端真实环境测试
python scripts\smoke_test.py 8322      # 功能：7 工具、护栏、回收站
python scripts\bypass_test.py 8322     # 对抗：33 个绕过向量 + 12 个正常向量
```

当前实测：
- **33/33 绕过全部拦截，12/12 正常命令零误杀**
- **5 次突发调用精准拦截超频请求，单任务互斥执行杜绝 CPU 跑满**

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