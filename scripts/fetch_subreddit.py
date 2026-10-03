#!/usr/bin/env python3
"""reddit-research: Arctic Shift 全量分页拉取（SKILL.md 模板 B）

用法: python fetch_subreddit.py <subreddit> <days> <out.json>
纯标准库，无依赖（Windows 需 py -3 / python）。
分页规则: 首页不带 before，之后 before=本页最小 created_utc - 1；空响应重试 2-3 次再判定到头。
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
UA = "reddit-research/1.0"
KEEP = ("id", "title", "score", "num_comments", "created_utc",
        "permalink", "selftext", "author", "subreddit", "link_flair_text")
MAX_RETRY = 3


def fetch(url, tries=MAX_RETRY):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            d = json.loads(body)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d.get("data", [])
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    print(f"  [warn] give up after {tries} tries: {last}")
    return None


def trim(p):
    o = {k: p.get(k) for k in KEEP}
    if isinstance(o.get("selftext"), str):
        o["selftext"] = o["selftext"][:1200]
    fl = o.get("link_flair_text")
    o["link_flair_text"] = fl if isinstance(fl, str) else None
    return o


def main():
    sub, days, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    cutoff = int(time.time()) - days * 86400
    seen, pages, oldest = {}, 0, None
    before = None
    print(f"[{sub}] 拉取近 {days} 天 (created_utc >= {cutoff})")

    while True:
        url = f"{BASE}?subreddit={sub}&limit=100&sort=desc"
        if before is not None:
            url += f"&before={before}"
        data = fetch(url)
        if data is None:
            break
        if not data:
            break
        fresh = 0
        for p in data:
            pid = p.get("id")
            if not pid or pid in seen:
                continue
            seen[pid] = trim(p)
            fresh += 1
        pages += 1
        oldest = min(p.get("created_utc", 0) for p in data)
        print(f"  page {pages:3d} | raw={len(data):3d} new={fresh:3d} total={len(seen):5d} oldest={oldest}")
        if oldest < cutoff:
            break
        before = oldest - 1
        time.sleep(0.35)

    posts = [p for p in seen.values() if (p.get("created_utc") or 0) >= cutoff]
    posts.sort(key=lambda p: -(p.get("created_utc") or 0))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False)
    print(f"[{sub}] 完成: {len(posts)} 帖 ({pages} 页) -> {out}\n")


if __name__ == "__main__":
    main()
