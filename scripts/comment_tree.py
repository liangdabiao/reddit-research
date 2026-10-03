# -*- coding: utf-8 -*-
"""评论树补刀（SKILL.md 模板 C）— 抓高赞评论
用法: python comment_tree.py <post_id> [topN]
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=t3_{}"


def flatten(node, out):
    if isinstance(node, list):
        for n in node:
            flatten(n, out)
    elif isinstance(node, dict):
        if node.get("body") and node.get("id"):
            out.append(node)
        for v in node.values():
            if isinstance(v, (list, dict)):
                flatten(v, out)


def main():
    pid, topn = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12
    req = urllib.request.Request(URL.format(pid), headers={"User-Agent": "reddit-research/1.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = []
    flatten(d.get("data", d), out)
    seen, uniq = set(), []
    for c in out:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        uniq.append(c)
    uniq.sort(key=lambda c: -(c.get("score") or 0))
    print(f"post {pid}: {len(uniq)} 条去重评论, 取 top {topn}\n")
    for i, c in enumerate(uniq[:topn], 1):
        body = re.sub(r"\s+", " ", c.get("body") or "").strip()
        day = datetime.fromtimestamp(c.get("created_utc") or 0, tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"--- [{i}] score={c.get('score')} u/{c.get('author')} {day}")
        print(f"    https://www.reddit.com{c.get('permalink','')}")
        print(f"    {body[:600]}\n")


if __name__ == "__main__":
    main()
