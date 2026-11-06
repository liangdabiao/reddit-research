#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_citations.py — 数字闭环校验器（SKILL.md 工作流第 6 步的可执行版）

用法:
    python verify_citations.py <report.md> <data_dir> [--score-tol N]

    <report.md>   待校验的报告 markdown（10 模块报告或痛点分析均支持）
    <data_dir>    fetch_subreddit.py 产出的数据目录（*.json 与 *.jsonl，
                  加载逻辑与 analyze_title_level.py 一致，含 .meta 窗口过滤）
    --score-tol   score 允许误差（默认 0=精确匹配。数据重抓过可放宽，如 5）

校验三件事（对应 deep_research 文档「强制：数字闭环」）:
  1. 报告里每个引用帖 ID 都存在于数据集中（防编造引用——LLM 凑模块条数时
     最容易编造 ID/score，此检查直接拦截）
  2. 引用声明的 score / comments 与数据一致（防数字抄错或张冠李戴）
  3. 引用声明的日期与数据一致（防时间窗口径漂移）

支持两种引用写法:
  a. 强制来源格式:  ... (score:35, comments:71, 2026-01-02) — https://www.reddit.com/r/sub/comments/<id>/
  b. analyze 输出格式: r/sub · score 35 · 71 评论 · 2026-01-02  +  <链接>
  评论链接 .../comments/<postid>/<slug>/<commentid> 只校验帖 ID 是否存在。

exit 0=全部通过；1=发现问题（发稿前必须清零）。
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

LINK_RX = re.compile(
    r"https?://(?:www\.|old\.)?reddit\.com(/r/[^/\s]+/comments/([A-Za-z0-9]+)(?:/[^\s]*)?)")
# (score:35, comments:71, 2026-01-02) — 宽松匹配空格差异
CLAIM_RX = re.compile(
    r"score\s*[:：]?\s*(\d+)\s*[,，/·\s]+comments\s*[:：]?\s*(\d+)", re.I)
# analyze_title_level.py 输出: · score 35 · 71 评论 · 2026-01-02
FMT2_RX = re.compile(r"score\s+(\d+)\s*·\s*(\d+)\s*评论", re.I)
DATE_RX = re.compile(r"(\d{4}-\d{2}-\d{2})")
# 强制来源格式里的 [帖ID]
BRACKET_ID_RX = re.compile(r"\[([A-Za-z0-9]{6,10})\](?!\()")


def day(u):
    return datetime.fromtimestamp(u or 0, tz=timezone.utc).strftime("%Y-%m-%d")


def cutoff_for(f: Path):
    mp = f.parent / (f.stem + ".meta")
    if not mp.exists():
        return None
    try:
        c = json.loads(mp.read_text(encoding="utf-8")).get("cutoff")
        return int(c) if c else None
    except Exception:  # noqa: BLE001
        return None


def load_posts(data_dir):
    """与 analyze_title_level.py.load_posts 同口径：*.json + *.jsonl，id 去重，
    有 .meta 的按 cutoff 过滤。"""
    posts, seen = [], set()
    d = Path(data_dir)
    patterns = []
    if d.is_dir():
        patterns += sorted(d.glob("*.json")) + sorted(d.glob("*.jsonl"))
    elif d.is_file():
        patterns = [d]
    for f in patterns:
        cut = cutoff_for(f)
        try:
            if f.suffix == ".jsonl":
                items = []
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except Exception:  # noqa: BLE001
                        pass
            else:
                raw = json.loads(f.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else None
                if items is None:
                    continue
        except Exception as e:  # noqa: BLE001
            print(f"  [skip] {f.name}: {e}")
            continue
        for p in items:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if not pid or pid in seen:
                continue
            if cut is not None and (p.get("created_utc") or 0) < cut:
                continue
            seen.add(pid)
            posts.append(p)
    return posts


def main():
    ap = argparse.ArgumentParser(
        description="数字闭环校验：报告引用 vs 原始数据（ID 存在性 + score/comments/日期一致性）")
    ap.add_argument("report", help="报告 markdown 路径")
    ap.add_argument("data_dir", help="数据目录（fetch_subreddit.py 产出）")
    ap.add_argument("--score-tol", type=int, default=0,
                    help="score 允许误差（默认 0=精确；数据重抓过可设 5）")
    args = ap.parse_args()

    report = Path(args.report)
    if not report.exists():
        print(f"[fatal] 报告不存在: {report}", file=sys.stderr)
        return 1
    text = report.read_text(encoding="utf-8", errors="replace")

    posts = load_posts(args.data_dir)
    if not posts:
        print(f"[fatal] 数据目录没有可用数据: {args.data_dir}", file=sys.stderr)
        return 1
    by_id = {p.get("id"): p for p in posts if p.get("id")}

    problems, checked = [], set()

    # --- 1) 逐行扫描：同一行可能有多个「引用 = 链接」，需按位置一一配对 ---
    pending_claim = None   # analyze fmt 风格：score 行在上一行，链接在下一行
    pending_date = None
    for raw_line in text.splitlines():
        line = raw_line
        links = list(LINK_RX.finditer(line))
        claims = [m for m in CLAIM_RX.finditer(line)] + [m for m in FMT2_RX.finditer(line)]
        claims.sort(key=lambda m: m.start())
        dates = list(DATE_RX.finditer(line))

        if not links:
            # 无链接的行：记住最近的 score 声明（fmt2 的 score 行在链接上一行）
            if claims:
                c = claims[-1]
                pending_claim = (int(c.group(1)), int(c.group(2)))
            else:
                pending_claim = None
            pending_date = dates[-1].group(1) if dates else None
            continue

        # 有链接的行：声明与链接按出现顺序 1:1 配对（数量不等时取最小，不误报）
        n = min(len(links), len(claims)) if claims else 0
        for i, m in enumerate(links):
            pid = m.group(2)
            checked.add(pid)
            p = by_id.get(pid)
            if p is None:
                problems.append(f"✗ 帖 {pid} 不在数据集中（疑似编造引用或数据目录给错）")
                problems.append(f"    行: {line.strip()[:120]}")
                continue
            claim = None
            if i < n:
                c = claims[i]
                claim = (int(c.group(1)), int(c.group(2)))
            elif len(claims) == 0 and pending_claim is not None and i == 0:
                claim = pending_claim          # fmt2：数字在上一行
            if claim:
                cs, cc = claim
                ps = p.get("score")
                pc = p.get("num_comments")
                if ps is not None and abs(cs - ps) > args.score_tol:
                    problems.append(f"✗ 帖 {pid} score 不符: 报告={cs} 数据={ps}")
                if pc is not None and cc != pc:
                    problems.append(f"✗ 帖 {pid} comments 不符: 报告={cc} 数据={pc}")
            dm = (dates[i].group(1) if i < len(dates)
                  else (pending_date if i == 0 and not dates else None))
            if dm and p.get("created_utc"):
                if dm != day(p["created_utc"]):
                    problems.append(f"✗ 帖 {pid} 日期不符: 报告={dm} 数据={day(p['created_utc'])}")
        pending_claim = None
        pending_date = None

    # --- 2) 强制格式里的 [帖ID]（防止只写 ID 不写链接漏检）---
    for m in BRACKET_ID_RX.finditer(text):
        pid = m.group(1)
        if pid in checked:
            continue
        # t3_ 前缀或纯 base36 帖 ID（Reddit 帖 ID 为 6-8 位 base36；过短的多为普通词）
        if not re.fullmatch(r"[a-z0-9]{6,10}", pid):
            continue
        checked.add(pid)
        if pid not in by_id:
            problems.append(f"✗ 引用 [ {pid} ] 不在数据集中（疑似编造或 ID 抄错）")

    print(f"校验完成: 引用帖 {len(checked)} 个, 数据集 {len(posts)} 帖, 问题 {len(problems)} 个")
    for p in problems:
        print(" " + p)
    if problems:
        print("\n结论: ✗ 未通过数字闭环 — 发稿前必须逐条修正（编造引用=报告无效）")
        return 1
    print("结论: ✓ 全部引用可在数据集中复算，数字闭环通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
