# 对抗测试（变异测试，端到端）：启动 server 后，通过 MCP 协议真实调用每个工具，
# 验证硬删除护栏能否被绕过、是否会误杀正常命令
#
# 用法:
#   $env:AGENTDOCK_SECRET='<你的 secret>'; python bypass_test.py [port]
#
# 判定：每个攻击向量必须被拦截（DENIED）；每个正常向量必须放行
# 向量表复用 guard_test.py，改一处两处同步生效

import asyncio
import os
import sys

from fastmcp import Client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard_test import ATTACKS, BENIGN  # noqa: E402

SECRET = os.environ.get("AGENTDOCK_SECRET", "change-me-to-a-long-random-string")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8322"
URL = f"http://127.0.0.1:{PORT}/{SECRET}/mcp"


def show(title: str, result) -> None:
    text = result.content[0].text if hasattr(result, "content") else str(result)
    body = text if len(text) < 500 else text[:500] + " ...(truncated)"
    print(f"\n=== {title} ===\n{body}")


async def classify(c, cmd: str) -> str:
    r = await c.call_tool("run_command", {"command": cmd, "session": "adv"})
    return r.content[0].text


async def main() -> None:
    async with Client(URL) as c:
        print("=" * 72)
        print("A. 攻击向量 —— 期望全部拦截")
        print("=" * 72)
        leaks = []
        for name, cmd in ATTACKS:
            out = await classify(c, cmd)
            ok = out.startswith("ERROR [DENIED]")
            print(f"  [{'拦截' if ok else '漏网!!'}] {name}")
            if not ok:
                leaks.append((name, cmd, out.strip().splitlines()[-1][:80]))

        print("\n" + "=" * 72)
        print("B. 正常向量 —— 期望全部放行（检查误杀）")
        print("=" * 72)
        fp = []
        for name, cmd in BENIGN:
            out = await classify(c, cmd)
            ok = not out.startswith("ERROR [DENIED]")
            print(f"  [{'放行' if ok else '误杀!!'}] {name}")
            if not ok:
                fp.append((name, cmd, out.strip().splitlines()[-1][:80]))

        print("\n" + "=" * 72)
        print(f"→ 拦截 {len(ATTACKS) - len(leaks)}/{len(ATTACKS)}，漏网 {len(leaks)}；"
              f"放行 {len(BENIGN) - len(fp)}/{len(BENIGN)}，误杀 {len(fp)}")
        for n, cmd, tail in leaks + fp:
            print(f"  - {n}\n      {cmd[:70]}\n      → {tail}")
        print("结论: " + ("通过" if not leaks and not fp else "需要加固"))
        sys.exit(1 if (leaks or fp) else 0)


if __name__ == "__main__":
    asyncio.run(main())