# Project DevLog (Milestones & Changes)

---

## [2026-10-09 17:00] v3.3 部署 API 网关防御层（限流 + 互斥排队 + 看门狗）

- **背景/动机**: 响应 X 平台实践关于模型幻觉死循环重试导致物理机打崩的风险，在 MCP 工具调用链前置轻量网关层。
- **核心操作**:
  1. 引入标准库实现的 `TokenBucketLimiter`（按 session 隔离，容量 3.0，速率 1.0/s）。
  2. 部署本地命令执行互斥锁 `_EXEC_LOCK`，单任务严格串行执行，等待超时返回 `ERROR [BUSY]`。
  3. 改造 `_ps` 执行器，命令超时自动通过 `taskkill /F /T` 递归杀掉子进程树，防止后台游离孤儿进程。
  4. 编写 `gateway_test.py` 验证并发突发拦截与串行排队。
- **影响/结果**: 5 次并发突发测试精准拦截超额调用，单任务串行互斥避免 CPU 跑满，测试全部通过。
- **关联文件**:
  - `scripts/server.py`
  - `scripts/gateway_test.py`
  - `README.md`

---

## [2026-10-09 15:30] v3.2 护栏变异测试加固与开源发布

- **背景/动机**: 彻底放弃人工控制台二次审批机制，转为全开放权限 + 文本级硬删除阻断网 + 回收站通道。
- **核心操作**:
  1. 梳理并拦截 33 类硬删除命令（PowerShell、.NET、Python、Node、Git 破坏性操作、磁盘命令等）。
  2. 增加输入归一化算法 `_normalize`，自动折叠反引号拆词、相邻字符串拼接、内嵌 base64 隐藏载荷。
  3. 编写无外部依赖的纯函数级单测 `guard_test.py`。
  4. 清除 Git 历史中误提交的测试 token，开源至 GitHub 并强制推送到 master。
- **影响/结果**: 33/33 攻击向量 100% 拦截，12/12 常用合法命令零误杀；GitHub 仓库建立并保持 clean。
- **关联文件**:
  - `scripts/server.py`
  - `scripts/guard_test.py`
  - `scripts/bypass_test.py`
  - `README.md`
