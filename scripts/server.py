# AgentDock Clone v3 — ChatGPT 网页直控本机的本地 MCP Server
# 依赖: pip install fastmcp send2trash
# 运行: python server.py  →  Streamable HTTP，路径 /<SECRET>/mcp
#
# v3 权限模型：完全放开，唯一的护栏是「硬删除拦截」
#   - run_command / write_file / edit_file 无审批，直接执行
#   - 硬删除（Remove-Item/rm/del/rd/rmdir/Clear-Content/git clean/format/diskpart...）
#     一律拦截，模型拿不到硬删接口
#   - 删除请走 recycle_delete 工具：文件进 Windows 回收站，可恢复
#
# 沿用 v2 的能力：
#   1. 结构化日志（JSONL，含 session/tool/ok/耗时/结果大小）
#   2. 会话隔离（每个 session 独立的日志标记与错误信息）
#   3. 统一错误处理（ERROR [CODE] msg，模型看到可读信息而非 traceback）
#   4. 工作区白名单（AGENTDOCK_ROOTS，文件读写只在允许目录内）

import base64
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import time

from fastmcp import FastMCP

# ── 配置 ──────────────────────────────────────────────────────────────
SECRET = os.environ.get("AGENTDOCK_SECRET", "change-me-to-a-long-random-string")
DEFAULT_ROOTS = os.environ.get("AGENTDOCK_ROOTS", r"D:\Develop\ai_workspace")
ALLOWED_ROOTS = [r for r in DEFAULT_ROOTS.split(";") if r.strip()]
LOG_DIR = pathlib.Path(
    os.environ.get(
        "AGENTDOCK_LOG_DIR",
        str(pathlib.Path(__file__).resolve().parent.parent / "logs"),
    )
)
LOG_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("AGENTDOCK_PORT", "8322"))

# ── 硬删除拦截：模型不提供不可恢复的删除能力 ───────────────────────────
# 词边界 (?<![A-Za-z0-9_-]) 防止 "format"/"confirm"/"third" 里的 rm/del/rd 被误判
_B = r"(?<![A-Za-z0-9_-])"
_E = r"(?![A-Za-z0-9_-])"

_HARD_DELETE: list[tuple[str, str]] = [
    # ── PowerShell cmdlet 与别名
    (r"\bRemove-Item\b", "Remove-Item"),
    (rf"{_B}rm{_E}", "rm"),
    (rf"{_B}del{_E}", "del"),
    (rf"{_B}rd{_E}", "rd"),
    (rf"{_B}rmdir{_E}", "rmdir"),
    (rf"{_B}erase{_E}", "erase"),
    (rf"{_B}ri(?=\s)", "ri(别名)"),
    (r"\bClear-Content\b", "Clear-Content"),
    (r"\bClear-RecycleBin\b", "Clear-RecycleBin(清空回收站)"),
    # ── .NET / VB 直接删除
    (r"\]\s*::\s*Delete\w*", ".NET Delete"),
    (r"\]\s*::\s*Remove\w*Directory", ".NET RemoveDirectory"),
    # ── Python / Node 删除
    (rf"{_B}os\.{_B}(remove|unlink|rmdir|removedirs)", "os.remove"),
    (rf"{_B}shutil\.{_B}(rmtree|move)", "shutil.rmtree"),
    (rf"{_B}fs\.{_B}(unlinkSync|rmSync|rmdirSync|unlink)", "fs.rmSync"),
    # Node 里 fs 常被写成 require('fs').rmSync(...)，不要求 fs 与点相邻
    (rf"\.\s*(rm|rmSync|rmdir|rmdirSync|unlink|unlinkSync)\s*\(", "fs 删除方法"),
    (rf"\.{_B}unlink\s*\(", "Path.unlink()"),
    (rf"{_B}(Path|PurePath)\s*\([^)]*\)\s*\.{_B}(rmdir|unlink)\s*\(", "Path.rmdir()"),
    # ── 目录镜像 / 影子副本
    (r"\brobocopy\b[^|;]*\s(/MIR|/PURGE)\b", "robocopy /MIR|/PURGE"),
    (r"\bvssadmin\b[^|;]*\bdelete\b", "vssadmin delete"),
    (r"\bwmic\b[^|;]*\bdelete\b", "wmic delete"),
    # ── git 破坏性操作
    (r"\bgit\s+clean\b[^|;]*-[a-z]*f", "git clean -f"),
    (r"\bgit\s+reset\b[^|;]*--hard", "git reset --hard"),
    (r"\bgit\s+checkout\b[^|;]*\s--\s", "git checkout --"),
    (r"\bgit\s+restore\b", "git restore"),
    # ── 磁盘级破坏
    (r"\bFormat-\w+\b|\bformat\s+[A-Za-z]:", "format"),
    (r"\bdiskpart\b|\bcipher\s+/w\b", "diskpart/cipher"),
    (r"\bfsutil\b[^|;]*(delete|setzerodata)", "fsutil"),
]

# 20 字符 ≈ 15 字节已足够装下 "os.remove"；阈值太高会漏掉短载荷
# （末尾的 = 不计入字符类，所以 "xxx==" 这种实际有效长度比视觉短）
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_CONCAT = re.compile(r"(['\"])([^'\"]*?)\1\s*\+\s*(['\"])([^'\"]*?)\3")


def _normalize(command: str) -> str:
    """归一化命令文本，让绕过手法失效：
    1. 去掉 PowerShell 反引号转义（Remove`-Item → Remove-Item）
    2. 折叠字符串拼接（'Remove'+'-Item' → Remove-Item）
    3. 解码内嵌 base64 载荷并一并送检（base64 藏命令）"""
    text = command.replace("`", "")
    prev = None
    while prev != text:
        prev = text
        text = _CONCAT.sub(r"\2\4", text)
    payloads = []
    for blob in _B64_BLOB.findall(text):
        try:
            payloads.append(
                base64.b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8", "ignore")
            )
        except Exception:
            continue
    return text + ("\n" + "\n".join(payloads) if payloads else "")


def _hard_delete_hits(command: str) -> list[str]:
    text = _normalize(command)
    return [name for pat, name in _HARD_DELETE if re.search(pat, text, re.I)]


def _clip(value: object, n: int = 200) -> object:
    return value[:n] + "…" if isinstance(value, str) and len(value) > n else value


# ── 结构化日志 ────────────────────────────────────────────────────────
def _log(session: str, tool: str, ok: bool, ms: int, args: dict, result: str) -> None:
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="milliseconds"),
        "session": session,
        "tool": tool,
        "ok": ok,
        "duration_ms": ms,
        "args": {k: _clip(v) for k, v in args.items()},
        "result_bytes": len(result),
    }
    line = json.dumps(rec, ensure_ascii=False)
    try:
        with open(
            LOG_DIR / f"agentdock-{dt.date.today().isoformat()}.jsonl",
            "a",
            encoding="utf-8",
        ) as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


# ── 统一错误处理 + 日志包装 ───────────────────────────────────────────
def _run(tool: str, session: str, args: dict, fn) -> str:
    t0 = time.perf_counter()
    try:
        out = fn()
        ms = int((time.perf_counter() - t0) * 1000)
        _log(session, tool, True, ms, args, str(out))
        return str(out)
    except PermissionError as e:
        msg = f"ERROR [DENIED] {e}"
    except subprocess.TimeoutExpired:
        msg = "ERROR [TIMEOUT] 命令执行超时"
    except FileNotFoundError as e:
        msg = f"ERROR [NOT_FOUND] {e}"
    except Exception as e:
        msg = f"ERROR [{type(e).__name__}] {e}"
    ms = int((time.perf_counter() - t0) * 1000)
    _log(session, tool, False, ms, args, msg)
    return msg


def _check_path(path: str) -> pathlib.Path:
    p = pathlib.Path(path).resolve()
    if ALLOWED_ROOTS and not any(
        str(p).lower().startswith(str(pathlib.Path(r).resolve()).lower())
        for r in ALLOWED_ROOTS
    ):
        raise PermissionError(
            f"路径不在允许的根目录内: {p}（允许: {', '.join(ALLOWED_ROOTS)}）"
        )
    return p


def _ps(command: str, timeout: int = 120) -> str:
    """在 pwsh / powershell 里执行一条命令并返回截断后的输出。"""
    for shell in ("pwsh", "powershell"):
        try:
            r = subprocess.run(
                [shell, "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            break
        except FileNotFoundError:
            continue
    else:
        raise FileNotFoundError("找不到 pwsh 或 powershell")
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    return (out + f"\n[exit code: {r.returncode}]")[-8000:]


mcp = FastMCP(name="AgentDock")


# ── 命令执行 ──────────────────────────────────────────────────────────
@mcp.tool
def run_command(command: str, session: str = "default") -> str:
    """在本地执行 PowerShell 命令（权限完全放开，无需审批）。
    唯一限制：硬删除命令被拦截，删除请改用 recycle_delete 工具。"""

    def body() -> str:
        hits = _hard_delete_hits(command)
        if hits:
            raise PermissionError(
                f"硬删除已禁用（检测到: {', '.join(hits)}）。"
                f"删除文件请调用 recycle_delete 工具，文件会进 Windows 回收站，可随时恢复。"
            )
        return _ps(command)

    return _run("run_command", session, {"command": command, "session": session}, body)


# ── 回收站删除（唯一删除通道）──────────────────────────────────────────
@mcp.tool
def recycle_delete(path: str, session: str = "default") -> str:
    """把文件或目录移入 Windows 回收站（可恢复）。这是本机唯一允许的删除方式。
    path 可为单个路径，或用 | 分隔多个路径。"""

    def body() -> str:
        from send2trash import send2trash

        results = []
        for raw in [p.strip() for p in path.split("|") if p.strip()]:
            target = _check_path(raw)
            if not target.exists():
                results.append(f"SKIP 不存在: {target}")
                continue
            try:
                send2trash(str(target))
                results.append(f"OK 已移入回收站: {target}")
            except Exception as e:
                results.append(f"FAIL {target}: {type(e).__name__} {e}")
        return "\n".join(results)

    return _run("recycle_delete", session, {"path": path, "session": session}, body)


# ── 文件读写 ──────────────────────────────────────────────────────────
@mcp.tool
def read_file(
    path: str, offset: int = 1, limit: int = 400, session: str = "default"
) -> str:
    """读取本地文件（带行号）。offset 为起始行，limit 为最多返回行数。"""
    return _run(
        "read_file",
        session,
        {"path": path, "offset": offset, "limit": limit},
        lambda: "\n".join(
            f"{i + offset:>5}  {ln}"
            for i, ln in enumerate(
                _check_path(path)
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()[offset - 1 : offset - 1 + limit]
            )
        ),
    )


@mcp.tool
def write_file(path: str, content: str, session: str = "default") -> str:
    """创建或完全覆盖一个本地 UTF-8 文件（无需审批）。"""
    target = _check_path(path)

    def body() -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"OK 已写入 {target}（{len(content)} 字符）"

    return _run(
        "write_file", session, {"path": path, "session": session}, body
    )


@mcp.tool
def edit_file(
    path: str, old_string: str, new_string: str, session: str = "default"
) -> str:
    """把文件中出现的 old_string（必须恰好出现 1 次）替换为 new_string。"""
    return _run(
        "edit_file",
        session,
        {"path": path, "session": session},
        lambda: _edit(path, old_string, new_string),
    )


def _edit(path: str, old_string: str, new_string: str) -> str:
    p = _check_path(path)
    text = p.read_text(encoding="utf-8")
    n = text.count(old_string)
    if n != 1:
        raise ValueError(f"old_string 出现 {n} 次（要求恰好 1 次），请加长匹配串")
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return "OK 替换成功"


@mcp.tool
def list_dir(path: str = ".", session: str = "default") -> str:
    """列出一个本地目录的内容（类型/大小/名称，最多 200 条）。"""
    return _run(
        "list_dir",
        session,
        {"path": path, "session": session},
        lambda: "\n".join(
            f"{'DIR ' if e.is_dir() else 'FILE'}  "
            f"{e.stat().st_size if e.is_file() else '':>10}  {e.name}"
            for e in sorted(
                _check_path(path).iterdir(),
                key=lambda x: (x.is_file(), x.name.lower()),
            )[:200]
        )
        or "(空目录)",
    )


@mcp.tool
def search_files(
    pattern: str, root: str = ".", session: str = "default"
) -> str:
    """在工作区内按文件名子串或正则搜索文件，返回最多 100 条相对路径。"""
    def body() -> str:
        base = _check_path(root)
        if not base.is_dir():
            raise FileNotFoundError(f"目录不存在: {base}")
        hits = [
            str(p.relative_to(base))
            for p in sorted(base.rglob("*"))
            if p.is_file() and len(p.parts) < 12 and re.search(pattern, p.name, re.I)
        ][:100]
        return "\n".join(hits)[:8000] or "(无匹配)"

    return _run(
        "search_files",
        session,
        {"pattern": pattern, "root": root, "session": session},
        body,
    )


if __name__ == "__main__":
    print(f"[AgentDock v3] 工作区根: {ALLOWED_ROOTS or '(不限)'}")
    print(f"[AgentDock v3] 日志目录: {LOG_DIR}")
    print(f"[AgentDock v3] 权限: 完全放开，仅拦截硬删除（删除走 recycle_delete 进回收站）")
    print(f"[AgentDock v3] MCP 路径: http://127.0.0.1:{PORT}/{SECRET}/mcp")
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=PORT,
        path=f"/{SECRET}/mcp",
        stateless_http=True,
    )