#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评论级分析（评论主题频次 + 商业信号统计）——「评论分析」目标的主工具

用法:
    python analyze_comments.py <comments.json|目录...> <themes.json> [-o out.md]
                               [--scope 正则] [--signals signals.json] [--top N]

    输入         comment_tree.py -j 保存的评论 JSON（数组；也可给目录，读其中 *.json）
    themes.json  主题表 {"主题名": "正则"}（与 analyze_title_level.py 用同一张表）
    --scope      只保留正文命中该正则的评论（调研目标相关性过滤，宁少勿跑题）
    --signals    商业信号表 {"信号名": "正则"}（默认内置四类，可用品类专属表覆盖，
                 参考 assets/signals.json）
    --top        每主题/每信号输出的代表评论条数（默认 5）

产出（markdown）:
  1. 评论级主题频次 —— 「同一问题有多少条评论在附和」，比帖子级频次细一级；
     帖子级告诉你"多少人开帖说"，评论级告诉你"多少人共鸣"，二者相乘才是痛点的真实规模
  2. 每主题代表评论（score 排序，带原楼链接，可直接进报告引用池）
  3. 商业信号统计 —— 购买意图 / 付费意愿 / 弃用流失 / 退货退款的计数与代表引语。
     「I'd pay $50 for something that doesn't do this」是商业机会调研里最值钱的
     一类证据，必须结构化提取而不是靠写报告时人工翻评论

配套流程:
    python scripts/comment_tree.py <id1> <id2> ... -t 20 -j comments.json
    python scripts/analyze_comments.py comments.json assets/themes_xx.json -o comments.md

纯标准库。exit 0=有产出；1=无数据。
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REMOVED_BODIES = ("[removed]", "[deleted]")

# 商业信号默认表（与 assets/signals.json 同源；--signals 可整表覆盖）
DEFAULT_SIGNALS = {
    "购买意图": r"just (ordered|bought|picked up|got (mine|one))|about to (buy|order|pull the trigger)"
               r"|thinking of (buying|getting|ordering)|on my (buy |wish )?list|waiting for (a )?sale"
               r"|purchased (it|one|mine|this)|placed (my|an) order|in my cart",
    "付费意愿": r"(would|'d|will) pay (up to |around |even |easily )?[$]?[0-9]+|pay (extra|more|a premium|double)"
               r"|worth every (penny|dollar|cent)|no hesitation paying|take my money",
    "弃用/流失": r"switched to|moved (to|on from) |stopped using|gave up on"
               r"|canceled my (order|subscription)|cancelled my (order|subscription)"
               r"|abandoned|went back to|no longer (use|buy|wear)",
    "退货/退款": r"return(ed|ing)? (it|mine|this|them)|sent (it|this|them) back|got a (full )?refund"
               r"|request(ed|ing)? a refund|chargeback|dispute[d]? the charge|money back",
}


def day(u):
    return datetime.fromtimestamp(u or 0, tz=timezone.utc).strftime("%Y-%m-%d")


def is_noise(c):
    body = (c.get("body") or "").strip().lower()
    if body in REMOVED_BODIES:
        return True
    author = (c.get("author") or "").lower()
    return author == "automoderator" or author.endswith("_bot")


def load_comments(paths):
    """从文件或目录加载评论 JSON 数组，按 id 去重、剔除噪音。"""
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(pp.glob("*.json"))
        else:
            files.append(pp)
    seen, out = set(), []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  [skip] {f.name}: {e}")
            continue
        if not isinstance(d, list):
            print(f"  [skip] {f.name}: 顶层不是数组（{type(d).__name__}）")
            continue
        for c in d:
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            if not cid or cid in seen or is_noise(c):
                continue
            seen.add(cid)
            out.append(c)
    return out


def fmt_comment(c, i=None, maxlen=400):
    body = re.sub(r"\s+", " ", c.get("body") or "").strip()
    score = c.get("score")
    score = "?" if score is None else score
    link = c.get("permalink")
    if not link:
        parent = (c.get("link_id") or "").removeprefix("t3_")
        link = f"/comments/{parent}/_/{c.get('id')}" if parent else ""
    prefix = f"{i}. " if i else ""
    return (f'{prefix}"{body[:maxlen]}" — u/{c.get("author")} · score {score} · '
            f'{day(c.get("created_utc"))}\n   https://www.reddit.com{link}')


def load_regex_map_from(raw, what):
    out = {}
    for k, v in raw.items():
        try:
            out[k] = re.compile(v, re.I)
        except re.error as e:
            sys.exit(f"[fatal] {what}「{k}」的正则无效: {v!r} ({e})")
    return out


def main():
    ap = argparse.ArgumentParser(
        description="评论级分析：主题频次 + 商业信号（配合 comment_tree.py -j 使用）")
    ap.add_argument("inputs", nargs="+", help="评论 JSON 文件或目录（comment_tree.py -j 产物）")
    ap.add_argument("themes", help="主题表 JSON：{\"主题名\": \"正则\"}")
    ap.add_argument("-o", "--output", default="comments_analysis.md", help="输出 markdown")
    ap.add_argument("--scope", help="调研目标相关性正则：只保留正文命中的评论")
    ap.add_argument("--signals", help="商业信号表 JSON（默认内置，参考 assets/signals.json）")
    ap.add_argument("--top", type=int, default=5, help="每主题/每信号代表评论条数（默认 5）")
    args = ap.parse_args()

    comments = load_comments(args.inputs)
    if not comments:
        print("没有评论数据。先用 comment_tree.py -j <ids> 保存评论，再跑本脚本。")
        return 1

    scope_rx = None
    if args.scope:
        try:
            scope_rx = re.compile(args.scope, re.I)
        except re.error as e:
            sys.exit(f"[fatal] --scope 正则无效: {args.scope!r} ({e})")
        before = len(comments)
        comments = [c for c in comments if scope_rx.search(c.get("body") or "")]
        print(f"[scope] 相关性过滤: {before} -> {len(comments)} 条")
        if not comments:
            print("[scope] 过滤后 0 条——检查 scope 正则或评论数据是否与调研目标相关。")
            return 1

    try:
        themes_raw = json.loads(Path(args.themes).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"[fatal] 主题表读取失败: {args.themes} ({e})")
    themes = load_regex_map_from(themes_raw, "主题表")

    if args.signals:
        try:
            sig_raw = json.loads(Path(args.signals).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            sys.exit(f"[fatal] 商业信号表读取失败: {args.signals} ({e})")
    else:
        sig_raw = DEFAULT_SIGNALS
    signals = load_regex_map_from(sig_raw, "商业信号表")

    # ---- 评论级主题频次 ----
    theme_hits = defaultdict(list)
    for c in comments:
        body = c.get("body") or ""
        for name, rx in themes.items():
            if rx.search(body):
                theme_hits[name].append(c)

    # ---- 商业信号 ----
    signal_hits = defaultdict(list)
    for c in comments:
        body = c.get("body") or ""
        for name, rx in signals.items():
            if rx.search(body):
                signal_hits[name].append(c)

    # ---- 渲染 ----
    ts = [c.get("created_utc") for c in comments if c.get("created_utc")]
    L = [
        "# 评论级分析",
        "",
        f"**样本** {len(comments)} 条评论 · "
        + (f"{day(min(ts))} .. {day(max(ts))}" if ts else "时间未知"),
    ]
    if scope_rx is not None:
        L.append("**scope**: 已按调研目标正则过滤，仅保留相关评论")
    L += ["", "## 主题频次（评论级）", "",
          "| 主题 | 评论数 | 占比 |", "|---|---:|---:|"]
    for name in sorted(theme_hits, key=lambda k: -len(theme_hits[k])):
        n = len(theme_hits[name])
        L.append(f"| {name} | {n} | {n * 100.0 / len(comments):.1f}% |")
    unmatched = len(comments) - len({c["id"] for lst in theme_hits.values() for c in lst})
    L += ["", f"> 未命中任何主题的评论 {unmatched} 条——占比高说明主题表没覆盖评论区语言，回炉扩表。"]

    L += ["", "## 各主题代表评论（score 排序）", ""]
    for name in sorted(theme_hits, key=lambda k: -len(theme_hits[k])):
        top = sorted(theme_hits[name], key=lambda c: -(c.get("score") or 0))[:args.top]
        L.append(f"### {name}（{len(theme_hits[name])} 条）")
        L.append("")
        for i, c in enumerate(top, 1):
            L.append(fmt_comment(c, i))
            L.append("")

    L += ["", "## 商业信号（评论级）", "",
          "| 信号 | 评论数 | 占比 |", "|---|---:|---:|"]
    for name in signals:
        n = len(signal_hits.get(name, []))
        L.append(f"| {name} | {n} | {n * 100.0 / len(comments):.1f}% |")
    L += ["", "> 付费意愿与购买意图是机会评估的规模证据；弃用/退货是风险与竞品切入口。"]
    for name in signals:
        hits = signal_hits.get(name, [])
        if not hits:
            continue
        top = sorted(hits, key=lambda c: -(c.get("score") or 0))[:args.top]
        L += [f"### {name}（{len(hits)} 条）", ""]
        for i, c in enumerate(top, 1):
            L.append(fmt_comment(c, i))
            L.append("")

    Path(args.output).write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"wrote {args.output}  评论 {len(comments)} 条 | 主题命中 "
          f"{sum(len(v) for v in theme_hits.values())} 次 | "
          + " | ".join(f"{k} {len(signal_hits.get(k, []))}" for k in signals))
    print("--- 评论级主题频次 ---")
    for name in sorted(theme_hits, key=lambda k: -len(theme_hits[k])):
        print(f"  {name:<26} {len(theme_hits[name]):4d}")


if __name__ == "__main__":
    sys.exit(main())
