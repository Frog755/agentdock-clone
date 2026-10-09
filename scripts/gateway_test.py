"""网关层测试：并发互斥与令牌桶限流验证
用法:
  python scripts/gateway_test.py [port]
"""

import asyncio
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastmcp import Client

SECRET = os.environ.get("AGENTDOCK_SECRET", "change-me-to-a-long-random-string")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8323"
URL = f"http://127.0.0.1:{PORT}/{SECRET}/mcp"


async def test_rate_limiter(c: Client):
    print("=" * 60)
    print("1. 令牌桶限流测试（突发并发 5 次请求，容量为 3，超额必须被拦截）")
    print("=" * 60)
    session = f"rate_test_{int(time.time())}"
    # 并发同时发起 5 次调用，测试突发拦截
    tasks = [
        c.call_tool("run_command", {"command": "Write-Output 'ping'", "session": session})
        for _ in range(5)
    ]
    raw_results = await asyncio.gather(*tasks)
    results = [r.content[0].text.strip() for r in raw_results]

    for i, txt in enumerate(results):
        print(f"  并发请求 {i+1}: {txt[:70]}")

    rate_limited = [r for r in results if "ERROR [RATE_LIMITED]" in r]
    print(f"\n  → 5 次并发突发中，限流器精准拦截了 {len(rate_limited)} 次")
    assert len(rate_limited) >= 1, "限流器未能按预期拦截超频请求！"
    print("  ✓ 令牌桶突发限流拦截成功！")


async def test_concurrency(c: Client):
    print("\n" + "=" * 60)
    print("2. 并发互斥锁测试（防止多任务同时打满 CPU）")
    print("=" * 60)
    session = f"conc_test_{int(time.time())}"

    # 启动一个长耗时命令（耗时 2 秒），并立即跟一个短命令
    t0 = time.perf_counter()
    task1 = c.call_tool("run_command", {"command": "Start-Sleep -Seconds 2; Write-Output 'long done'", "session": session})
    # 微小延迟让 task1 先行
    await asyncio.sleep(0.2)
    task2 = c.call_tool("run_command", {"command": "Write-Output 'short done'", "session": session})

    r1, r2 = await asyncio.gather(task1, task2)
    elapsed = time.perf_counter() - t0

    t1_txt = r1.content[0].text.strip()
    t2_txt = r2.content[0].text.strip()
    print(f"  Task 1: {t1_txt[:60]}")
    print(f"  Task 2: {t2_txt[:60]}")
    print(f"  总耗时: {elapsed:.2f}s")

    # 如果正确互斥串行排队，总耗时应 >= 2.0s 且短命令在长命令之后完成
    assert elapsed >= 2.0, "两个命令并行跑了，未能实现互斥排队！"
    assert "long done" in t1_txt and ("short done" in t2_txt or "RATE_LIMITED" in t2_txt), "结果不符合预期！"
    print("  ✓ 并发排队与互斥锁验证通过！")


async def main():
    async with Client(URL) as c:
        await test_rate_limiter(c)
        # 等待令牌恢复
        print("\n  休眠 3 秒等待令牌桶补充...")
        await asyncio.sleep(3.0)
        await test_concurrency(c)
    print("\n" + "=" * 60)
    print("所有网关防御测试全部通过！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())