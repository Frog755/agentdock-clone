# v3 功能冒烟测试：全权限 + 硬删除拦截 + 回收站删除
# 用法:
#   $env:AGENTDOCK_SECRET='<你的 secret>'; python smoke_test.py [port]

import asyncio
import os
import pathlib
import sys

from fastmcp import Client

SECRET = os.environ.get("AGENTDOCK_SECRET", "change-me-to-a-long-random-string")
PORT = sys.argv[1] if len(sys.argv) > 1 else "8322"
URL = f"http://127.0.0.1:{PORT}/{SECRET}/mcp"
TMP = pathlib.Path(r"D:\Develop\ai_workspace\agentdock-clone\.smoke")
VICTIM = TMP / "victim.txt"


def show(title: str, result) -> None:
    text = result.content[0].text if hasattr(result, "content") else str(result)
    body = text if len(text) < 500 else text[:500] + " ...(truncated)"
    print(f"\n=== {title} ===\n{body}")


async def main() -> None:
    async with Client(URL) as c:
        tools = [t.name for t in await c.list_tools()]
        print(f"[tools] {len(tools)}: {tools}")

        TMP.mkdir(parents=True, exist_ok=True)
        VICTIM.write_text("important data", encoding="utf-8")

        # ① 全权限：无需审批直接执行
        show("write_file 新建（无审批）", await c.call_tool("write_file", {
            "path": str(TMP / "created.txt"), "content": "hello v3",
            "session": "v3"}))
        show("write_file 覆盖（无审批）", await c.call_tool("write_file", {
            "path": str(TMP / "created.txt"), "content": "overwritten",
            "session": "v3"}))
        show("run_command（无审批）", await c.call_tool("run_command", {
            "command": "Write-Output 全权限已生效", "session": "v3"}))

        # ② 硬删除拦截
        blocked = passed = 0
        for cmd in [
            f"Remove-Item -Force '{VICTIM}'",
            f"del {VICTIM}",
            f"rm -rf {TMP}",
            f"rd /s /q {TMP}",
            f"rmdir /s /q '{TMP}'",
            f"Clear-Content -Path '{VICTIM}'",
            "git clean -fd",
            "format D:",
        ]:
            r = await c.call_tool("run_command", {"command": cmd, "session": "v3"})
            if r.content[0].text.startswith("ERROR [DENIED]"):
                blocked += 1
            else:
                passed += 1
                print(f"  [漏网] {cmd}")
        print(f"\n[硬删除拦截] 拦截 {blocked}/8，漏网 {passed}")
        print(f"[victim.txt 是否仍在] {VICTIM.exists()}")

        # ③ 回收站删除
        show("recycle_delete", await c.call_tool("recycle_delete", {
            "path": f"{VICTIM}|{TMP / 'created.txt'}", "session": "v3"}))
        left = [p.name for p in TMP.glob("*")] if TMP.exists() else []
        print(f"[TMP 剩余] {left}")

        # ④ 其他能力
        show("read_file", await c.call_tool("read_file", {
            "path": r"D:\Develop\ai_workspace\deepseek_workspace\agentdock-clone\README.md",
            "limit": 3, "session": "v3"}))
        show("search_files", await c.call_tool("search_files", {
            "pattern": r"\.py$",
            "root": r"D:\Develop\ai_workspace\deepseek_workspace\agentdock-clone",
            "session": "v3"}))
        show("越权路径", await c.call_tool("read_file", {
            "path": r"C:\Windows\System32\drivers", "session": "v3"}))
        print("\nv3 smoke done")


if __name__ == "__main__":
    asyncio.run(main())
