import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
data = json.load(open(r"C:\Users\frog\AppData\Local\Temp\khazix.json", encoding="utf-8-sig"))
ROOT = "2099873865988247870"
replies = [d for d in data if d.get("id") != ROOT]
replies.sort(key=lambda d: (d.get("likes") or 0) + 3 * (d.get("retweets") or 0), reverse=True)
print(f"总条目 {len(data)}，回复 {len(replies)}，按互动排序\n")
for d in replies[:30]:
    t = " ".join((d.get("text") or "").split())
    print("=" * 70)
    print("@%s  likes=%s rt=%s  %s" % (
        d.get("author"), d.get("likes"), d.get("retweets"), (d.get("url") or "")[:60]))
    print(t[:900])
    print()