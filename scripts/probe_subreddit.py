#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sub 活跃度探测（SKILL.md 标准工作流第 1 步，替代手工 curl）

用法:
    python probe_subreddit.py <sub> [<sub2> ...] [--days 30]
    python probe_subreddit.py LocalLLaMA deepseek singularity

每个 sub 输出: 最新帖时间（新鲜度）+ 近 N 天帖子总量（样本量预估）+ 活跃度判定。
判定规则: 近 N 天 0 帖 → 疑似停更/不存在（不可用于结论，见 deep_research 文档坑1）；
          日均 < 1 帖 → 低活跃，样本可能不足。

端点说明（2026-10 实测）:
    帖量: /api/posts/search/aggregate?subreddit=X&aggregate=subreddit&after=&before=
          返回 {"data":[{"key":"esp32","count":"1173"}]}  # 注意 count 是字符串
          ⚠️ 没有 groupBy 参数（写 groupBy 会报 Unknown query parameter）
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://arctic-shift.photon-reddit.com"
UA = "reddit-research/1.2"
RETRY = 3


def get(url):
    """带重试的 GET。429/5xx/422 均退避重试（aggregate 的 422 是瞬态过载，
    实测同参数重发即 200——注意这与关键词查询的 422 不同，那种重试永远无效）。"""
    last = None
    for i in range(RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(d, dict) and d.get("error"):
                raise RuntimeError(d["error"])
            return d
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (422, 429) or e.code >= 500:
                time.sleep(1.5 * (i + 1))
                continue
            raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"重试 {RETRY} 次仍失败: {last}")


def probe(sub, days):
    now = int(time.time())
    after = now - days * 86400
    newest = None
    try:
        d = get(f"{BASE}/api/posts/search?subreddit={sub}&limit=1&sort=desc")
        data = d.get("data") if isinstance(d, dict) else None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            newest = data[0]
    except RuntimeError as e:
        print(f"  r/{sub}: ✗ 最新帖查询失败 — {e}")
        return
    count = None
    try:
        d = get(f"{BASE}/api/posts/search/aggregate?subreddit={sub}"
                f"&aggregate=subreddit&after={after}&before={now}")
        data = d.get("data") if isinstance(d, dict) else None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            try:
                count = int(data[0].get("count", 0))
            except (TypeError, ValueError):
                count = 0
        elif data == []:
            count = 0
    except RuntimeError as e:
        print(f"  r/{sub}: ⚠ aggregate 查询失败（{e}），仅展示最新帖")

    if newest is None:
        print(f"  r/{sub}: ✗ 无任何帖子 — sub 可能不存在或拼错")
        return
    u = newest.get("created_utc") or 0
    day = datetime.fromtimestamp(u, tz=timezone.utc).strftime("%Y-%m-%d")
    age_d = max(0, (now - u) // 86400) if u else None
    title = str(newest.get("title") or "")[:60]
    line = f"  r/{sub:<22} 最新帖 {day}"
    if count is not None:
        line += f" | 近 {days} 天 ≈ {count} 帖 (日均 {count / days:.1f})"
    print(f"{line}\n      {title}")
    if count == 0:
        print(f"      ✗ 近 {days} 天 0 帖 → 疑似停更/不存在，不可用于结论")
    elif count is not None and count < days:
        print("      ⚠ 日均不足 1 帖 → 低活跃，样本可能不足，考虑换 sub 或拉长时间窗")
    if age_d is not None and age_d > 90:
        print(f"      ⚠ 最新帖已是 {age_d} 天前 → 数据陈旧")


def main():
    ap = argparse.ArgumentParser(description="sub 活跃度探测（新鲜度 + 近 N 天帖量）")
    ap.add_argument("subs", nargs="+", help="subreddit 名，可多个，不带 r/")
    ap.add_argument("--days", type=int, default=30, help="统计窗口（默认 30 天）")
    args = ap.parse_args()
    print(f"=== 活跃度探测（窗口 {args.days} 天）===")
    for s in args.subs:
        probe(s.strip().removeprefix("r/"), args.days)
        time.sleep(0.35)
    return 0


if __name__ == "__main__":
    sys.exit(main())
