# -*- coding: utf-8 -*-
"""filter_and_rank.py — 本地吐槽过滤 + 主题归类 + 热度排序 (纯标准库)

用法:
    python3 filter_and_rank.py posts.json -o report.md
    python3 filter_and_rank.py posts.json --keywords "battery|charging" --top 20

输入:  fetch_subreddit.sh 产出的 JSON 数组
输出:  markdown 报告 — 主题分布 + 每主题 top 帖 (标题/热度/日期/原帖链接/摘录)

⚠️ 关键词过滤是"召回"不是"判定": 引用前必须人工读原文确认语义。
   实测误命中案例: "finally cracked it"(=搞定了, 正面) 会被 crack 命中。
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone

# Windows GBK 控制台中文输出兜底
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 吐槽/痛点信号词 (英文社区通用, 按需增删或用 --keywords 覆盖)
DEFAULT_NEG = (
    r"disappoint|frustrat|regret|waste of money|money grab|cash grab|beware|warning"
    r"|avoid|scam|rip.?off|terrible|horrible|worst|stopped working|won.?t work"
    r"|doesn.?t work|not working|cracked|\bcrack|defect|refund|return(ing|ed)?\b"
    r"|warranty|won.?t charge|not charging|\bbroke\b|broken|fell apart|falling apart"
    r"|peel|greedy|useless|unreliable|inaccurate|poor quality|quality control"
    r"|ghosted|ignored|garbage|junk|angry|annoy|let down|\bhate\b|disappointing"
    r"|overpriced|not worth|faulty|malfunction|nightmare|worthless|sucks|awful"
)

# 主题表: 按你的产品域改这里 (示例为消费级可穿戴; 一帖可归多主题)
DEFAULT_THEMES = {
    "subscription/paywall": r"subscription|membership|paywall|monthly fee|pay.?wall|cash grab|greedy",
    "battery/charging": r"batter|charg|drain|\bdead\b|died|power",
    "durability/finish": r"scratch|crack|chip|coating|\bfinish\b|peel|dent|discolor|scuff",
    "accuracy/data": r"inaccurate|accuracy|unreliable|wrong data|off by|sleep stag|heart rate",
    "customer service/warranty": r"customer (service|support)|warranty|refund|return|rma|replacement|ghosted|support ticket",
    "app/software": r"\bapp\b|sync|\bbug\b|glitch|crash|update|firmware|login|server",
    "build quality/defect": r"defect|\bbroke\b|broken|stopped working|quality control|faulty|malfunction",
    "sizing/fit": r"\bsize|sizing|\bfit\b|too (big|small|tight|loose)|resize",
    "price/value/regret": r"waste of money|overpriced|not worth|\bregret|too expensive|ripoff",
}


def day(u):
    return datetime.fromtimestamp(u, tz=timezone.utc).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="fetch_subreddit.sh 产出的 JSON 数组文件")
    ap.add_argument("-o", "--output", default="report.md", help="输出 markdown (默认 report.md)")
    ap.add_argument("--keywords", default=DEFAULT_NEG, help="吐槽信号词正则 (覆盖默认词表)")
    ap.add_argument("--themes", help="自定义主题表 JSON 文件: {\"主题名\": \"正则\", ...}")
    ap.add_argument("--top", type=int, default=12, help="每主题输出 top N 帖 (默认 12)")
    args = ap.parse_args()

    posts = json.load(open(args.input, encoding="utf-8"))
    neg = re.compile(args.keywords, re.I)
    themes = {k: re.compile(v, re.I) for k, v in (
        json.load(open(args.themes, encoding="utf-8")) if args.themes else DEFAULT_THEMES
    ).items()}

    def text(p):
        return (p.get("title") or "") + " " + (p.get("selftext") or "")

    complaints = [p for p in posts if neg.search(text(p))]
    buckets = {k: [] for k in themes}
    buckets["other/unclassified"] = []
    for p in complaints:
        hit = False
        for k, rx in themes.items():
            if rx.search(text(p)):
                buckets[k].append(p)
                hit = True
        if not hit:
            buckets["other/unclassified"].append(p)

    def heat(p):
        return (p.get("score") or 0) + (p.get("num_comments") or 0)

    us = [p["created_utc"] for p in posts] or [0]
    lines = [
        "# Reddit 吐槽调研报告",
        "",
        f"- 样本: {len(posts)} 帖, 时间跨度 {day(min(us))} .. {day(max(us))}",
        f"- 命中吐槽信号: {len(complaints)} 帖 (关键词召回, 引用前需人工复核语义)",
        "",
        "## 主题分布 (一帖可归多主题)",
        "",
        "| 主题 | 命中帖数 |",
        "|---|---|",
    ]
    for k in sorted(buckets, key=lambda x: -len(buckets[x])):
        lines.append(f"| {k} | {len(buckets[k])} |")

    for k in sorted(buckets, key=lambda x: -len(buckets[x])):
        lst = sorted(buckets[k], key=lambda p: -heat(p))[: args.top]
        if not lst:
            continue
        lines += ["", f"## {k} (n={len(buckets[k])})", ""]
        for p in lst:
            link = "https://www.reddit.com" + (p.get("permalink") or "")
            excerpt = re.sub(r"\s+", " ", p.get("selftext") or "").strip()[:220]
            lines.append(
                f"- **{(p.get('title') or '').strip()}** "
                f"(score:{p.get('score')}, comments:{p.get('num_comments')}, {day(p['created_utc'])})"
            )
            lines.append(f"  <{link}>")
            if excerpt:
                lines.append(f'  > "{excerpt}"')

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {args.output}: {len(complaints)}/{len(posts)} 帖命中吐槽信号")
    for k in sorted(buckets, key=lambda x: -len(buckets[x])):
        print(f"  {k:<32} {len(buckets[k])}")


if __name__ == "__main__":
    main()
