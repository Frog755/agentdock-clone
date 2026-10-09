"""护栏单元测试（纯函数级，无需启动 MCP 服务，可直接在 CI 里跑）

验证两件事：
  A. 30 个硬删除绕过向量全部被 _hard_delete_hits 命中
  B. 12 个正常命令全部不被命中（检查误杀）

用法: python scripts/guard_test.py   （有失败时 exit code = 1）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，直接输出特殊符号会 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from server import _hard_delete_hits, _normalize  # noqa: E402

X = r"D:\Develop\ai_workspace\agentdock-clone\.smoke\victim.txt"
D = r"D:\Develop\ai_workspace\agentdock-clone\.smoke"

B64 = "aW1wb3J0IG9zOyBvcy5yZW1vdmUocidDOlx4Jw=="

ATTACKS = [
    ("直接 Remove-Item", f"Remove-Item -Force '{X}'"),
    ("cmd del", f'cmd /c "del {X}"'),
    ("PowerShell alias ri", f"ri '{X}'"),
    ("alias erase", f"erase {X}"),
    ("rm -rf", f"rm -rf {D}"),
    ("rd /s /q", f"rd /s /q {D}"),
    ("rmdir", f"rmdir /s /q '{D}'"),
    ("Clear-Content", f"Clear-Content '{X}'"),
    ("大小写混淆 ReMoVe-ItEm", f"ReMoVe-ItEm -Force '{X}'"),
    ("反引号拆词", f"Remove`-Item -Force '{X}'"),
    ("变量字符串拼接", f"$c='Remove'+'-Item'; & $c -Force '{X}'"),
    (".NET File.Delete", f"[System.IO.File]::Delete('{X}')"),
    (".NET Directory.Delete", f"[System.IO.Directory]::Delete('{D}')"),
    ("VB DeleteFile", f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{X}')"),
    ("python os.remove", f"python -c \"import os; os.remove(r'{X}')\""),
    ("python os.unlink", f"python -c \"import os; os.unlink(r'{X}')\""),
    ("python shutil.rmtree", f"python -c \"import shutil; shutil.rmtree(r'{D}')\""),
    ("python Path.unlink", f"python -c \"from pathlib import Path; Path(r'{X}').unlink()\""),
    ("node fs.rmSync", f"node -e \"require('fs').rmSync('{D}')\""),
    ("robocopy /MIR", f"robocopy '{D}\\empty' '{D}' /MIR"),
    ("robocopy /PURGE", f"robocopy src '{D}' /PURGE"),
    ("git clean -fdx", "git clean -fdx"),
    ("git reset --hard", "git reset --hard HEAD~5"),
    ("git checkout --", "git checkout -- ."),
    ("git restore", "git restore ."),
    ("清空回收站", "Clear-RecycleBin -Force"),
    ("wmic delete", "wmic shadowcopy delete"),
    ("vssadmin delete shadows", "vssadmin delete shadows"),
    ("fsutil setzerodata", "fsutil file setzerodata C:\\x 0"),
    ("cipher /w", "cipher /w:C:\\x"),
    ("Format-Volume", "Format-Volume -DriveLetter D"),
    ("diskpart", "diskpart /s script.txt"),
    ("base64 内嵌载荷", f"python -c \"import base64;exec(base64.b64decode('{B64}'))\""),
]

BENIGN = [
    ("git status", "git status"),
    ("查看目录", "Get-ChildItem"),
    ("python 版本", "python --version"),
    ("pytest", "pytest -q"),
    ("含 format 单词", "Write-Output format confirmed"),
    ("含 confirm 单词", "Write-Output confirm ok"),
    ("含 model 单词", "Write-Output model ready"),
    ("含 third 单词", "Write-Output third party"),
    ("含 delish 单词", "Write-Output delish"),
    ("含 rmdirVar 变量名", "Write-Output $rmdirVar"),
    ("npm 构建", "npm run build"),
    ("查看进程", "Get-Process | Select-Object -First 3"),
]


def main() -> int:
    failures: list[str] = []

    print("=" * 60)
    print("A. 硬删除绕过向量 —— 期望全部命中")
    print("=" * 60)
    for name, cmd in ATTACKS:
        hits = _hard_delete_hits(cmd)
        ok = bool(hits)
        print(f"  [{'拦截' if ok else '漏网!!'}] {name}  {hits or ''}")
        if not ok:
            failures.append(f"绕过未被拦截: {name}  →  {cmd}")

    print("\n" + "=" * 60)
    print("B. 正常命令 —— 期望全部放行")
    print("=" * 60)
    for name, cmd in BENIGN:
        hits = _hard_delete_hits(cmd)
        ok = not hits
        print(f"  [{'放行' if ok else '误杀!!'}] {name}  {hits or ''}")
        if not ok:
            failures.append(f"正常命令被误杀: {name}  →  {cmd}")

    print("\n" + "=" * 60)
    print(f"归一化自检: 'Remove'+'-Item' → {_normalize(chr(39) + 'Remove' + chr(39) + '+' + chr(39) + '-Item' + chr(39))!r}")
    print(f"拦截 {len(ATTACKS) - len(failures)}/{len(ATTACKS)} 攻击向量；失败 {len(failures)} 项")
    for f in failures:
        print("  ✗ " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())