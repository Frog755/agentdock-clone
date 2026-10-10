# Current Project State

- **Active Goal**: 打造轻量安全、无摩擦的 ChatGPT 网页直控本机 FastMCP 网关
- **Current Phase**: v3.4 —— 隧道链路已修复并验证端到端可用（GitHub: Frog755/agentdock-clone）
- **Recent Completed**:
  - [2026-10-09] 33 项硬删除拦截网 + 文本归一化（反引号/拼接/base64 绕过防护）
  - [2026-10-09] 微型 API 网关：令牌桶限流 + 命令并发互斥锁 + 进程树看门狗
  - [2026-10-10] 定位并修复「工具内部错误」：隧道直连被 TLS 劫持，改为走代理 + http2
- **Next Priorities**:
  - [ ] 观察 ChatGPT 网页长链路稳定性（含代理链路掉线兜底）
  - [ ] 按需增加大目录返回结果的智能折叠/分片机制
- **Blockers / Known Risks**:
  - 隧道强依赖本地代理进程存活，代理退出即链路中断（AgDR-0003）
  - 同一隧道禁止并行多个 cloudflared 连接器，否则间歇 502
  - `run_command` 无路径白名单（设计权衡：保留全权限开发能力）
  - 鉴权仅靠 URL 路径中的 SECRET，禁止外泄
