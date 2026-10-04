#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评论树补刀（SKILL.md 模板 C）— 抓某帖完整评论树并提取高赞评论

用法:
    python comment_tree.py <post_id> [post_id2 ...] [-t topN] [-o out.md]
    python comment_tree.py 1uff7ix                  # 单帖，默认 top 12
    python comment_tree.py 1uff7ix 1u64d64 -t 8     # 批量，每帖 top 8
    python comment_tree.py 1uff7ix -t 20 -o c.md    # 结果同时存文件

兼容旧用法 `comment_tree.py <post_id> <topN>`（第二个参数为纯数字时按 topN 解析）。

可靠性: 网络/5xx/429 退避重试 3 次；error JSON 显式报错（不再静默输出 0 条）；
批量模式下单帖失败不影响其余帖。exit 0=全部成功, 2=部分/全部失败。
注意: API 对不存在的帖子返回 200 + 空 data，与"零评论帖"无法区分——
"0 条去重评论"既可能是无评论也可能是 ID 写错，帖 ID 应来自 fetch 结果。
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

URL = "https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=t3_{}"
UA = "reddit-research/1.2"
RETRY = 3


def fetch_comments(pid):
    """抓一帖评论树，返回扁平化后的评论列表（含嵌套回复）。失败抛 RuntimeError。"""
    last = None
    for i in range(RETRY):
        try:
            req = urllib.request.Request(URL.format(pid), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(d, dict) and "error" in d:
                raise RuntimeError(f"服务端 error: {d['error']}")
            out = []
            flatten(d.get("data", d) if isinstance(d, dict) else d, out)
            return out
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (i + 1))
                continue
            raise RuntimeError(last)          # 4xx 重试无意义
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"重试 {RETRY} 次仍失败: {last}")


def flatten(node, out):
    """递归拍平评论树（含 more 折叠对象里的子树）。"""
    if isinstance(node, list):
        for n in node:
            flatten(n, out)
    elif isinstance(node, dict):
        if node.get("body") and node.get("id"):
            out.append(node)
        for v in node.values():
            if isinstance(v, (list, dict)):
                flatten(v, out)


def render(pid, topn):
    """抓取并格式化一帖的 topN 高赞评论，返回文本行列表。"""
    cs = fetch_comments(pid)
    seen, uniq = set(), []
    for c in cs:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            uniq.append(c)
    uniq.sort(key=lambda c: -(c.get("score") or 0))
    lines = [f"post {pid}: {len(uniq)} 条去重评论, 取 top {min(topn, len(uniq))}", ""]
    for i, c in enumerate(uniq[:topn], 1):
        body = re.sub(r"\s+", " ", c.get("body") or "").strip()
        day = datetime.fromtimestamp(c.get("created_utc") or 0,
                                     tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"--- [{i}] score={c.get('score')} u/{c.get('author')} {day}")
        lines.append(f"    https://www.reddit.com{c.get('permalink', '')}")
        lines.append(f"    {body[:600]}")
        lines.append("")
    return lines


def main():
    ap = argparse.ArgumentParser(description="评论树抓取 + 高赞评论提取（支持批量/重试）")
    ap.add_argument("post_ids", nargs="+", help="帖子 ID（可多个；带不带 t3_ 前缀都行）")
    ap.add_argument("-t", "--top", type=int, default=12, help="每帖取 top N 高赞（默认 12）")
    ap.add_argument("-o", "--out", help="结果同时写入该文件（默认只打印）")
    args = ap.parse_args()

    # 兼容旧用法: comment_tree.py <id> <topN>
    ids = [p.removeprefix("t3_").strip() for p in args.post_ids]
    topn = args.top
    if len(ids) == 2 and ids[1].isdigit() and len(ids[1]) <= 3:
        topn, ids = int(ids[1]), ids[:1]

    chunks, failed = [], []
    for pid in ids:
        if not pid:
            continue
        try:
            chunks.append("\n".join(render(pid, topn)))
        except RuntimeError as e:
            failed.append(f"{pid}: {e}")
            print(f"  [fail] {pid}: {e}", file=sys.stderr)
        time.sleep(0.35)

    text = "\n".join(chunks) if chunks else "(无成功帖子)"
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\n已写入 {args.out}", file=sys.stderr)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
