# -*- coding: utf-8 -*-
"""标题级痛点分析（通用工具）—— 自动规避"作品展示帖霸榜"

用法:
    python analyze_title_level.py <data_dir> <themes.json> [-o out.md] [--focus <focus.json>]

    <data_dir>    fetch_subreddit.py 产出的目录（*.json 与 *.jsonl 都会读，
                  每篇含 id/title/score/selftext/...；中断未合并的流水也能直接分析）
    <themes.json> 主题表：{"主题名": "正则", ...}，用于给帖子打主题标签
    -o out.md     输出 markdown（默认 painpoints.md）
    --focus       可选：品类定向挖掘配置 {"组名": "正则", ...}，
                  命中 >= --focus-min 组数的帖会被单独列出（默认 2 组）

为什么需要这个（实测教训，2026-10）:
  r/esp32 这类高活跃sub 里，"I built an X" 作品展示帖score 可达 2031，
  比任何痛点帖都高。若用全文关键词过滤，排前列的全是晒作品。
  → 实测同一份数据（7055 帖）：全文判据召回 2819 帖（39%，污染严重）
    → 标题级判据收敛到847 帖（纯度可用）
  原理：晒作品帖的标题几乎不会写成疑问句或抱怨句，所以判据放标题级。

分类输出四类:
  complaint 标题含抱怨/失败信号   →痛点
  help      标题为疑问求助句→ 痛点（工程社区里求助帖占多数）
  showcase  标题为作品展示        → 剔除
  other     其余

主题表用法示例（themes_esp32.json 见同目录）:
  {
    "电源/电池": "batter|charg|power|vcc|5v|3\\.3v",
    "连接稳定性": "wifi|ble|bluetooth|disconnect|mqtt"
  }
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

# ---------- 标题级痛点判据（领域无关，可直接复用）----------

# 疑问 / 求助型标题
TITLE_Q = re.compile(
    r"^\s*(why |how (do|can|to|should|would|is)|what (is|are|should)|when |where |"
    r"can'?t |cannot |couldn'?t |won'?t |doesn'?t |does not |isn'?t |not |"
    r"anyone (know|else|have|any)|any(one|body) (know|idea|advice|help)|"
    r"looking for|need (help|advice|some)|help|advice|trouble|issue|problem|"
    r"stuck|struggl|no idea|what am i|is this (normal|expected|a problem|working)|"
    r"should i|would it|am i (wrong|doing)|which |what'?s the (best|right|difference))",
    re.I,
)

# 抱怨 / 翻车型标题（英文社区通用信号词）
TITLE_NEG = re.compile(
    r"(broken|break(?:s|ing)? (up|apart|down)|broke|died|dead|burn|smoke|smoking|"
    r"bricke?d|unbrick|fake|counterfeit|clone|defective|doa|"
    r"stopped working|no longer works|not working|doesn'?t work|won'?t work|"
    r"overheat|too hot|melt|"
    r"(disappoint|frustrat|regret|nightmare|terrible|horrible|awful|worst|useless|"
    r"worthless|garbage|junk|sucks|rip.?off|scam|bad experience)"
    r"|(gave up|give up|abandon|never again|last time|moved on|switched to)"
    r"|(hard|struggl|difficult|trouble) (to|with)|hate|hated|angry|annoying|infuriating|"
    r"inaccurate|unreliable|flaky|intermittent|"
    r"warning|be careful|beware|avoid|caveat|lessons? learned|warning:|"
    r"can'?t get|can'?t figure|can'?t make|couldn'?t get|couldn'?t figure|"
    r"not detectable|not recognized|not recognised|not showing up|not responding|"
    r"not charging|won'?t charge|not powering|out of memory|stack overflow|"
    r"bootloop|boot loop|keeps? resetting|randomly (reboot|disconnect|crash))",
    re.I,
)

# 作品展示帖（标题级）——这类不是痛点
SHOWCASE_TITLE = re.compile(
    r"^\s*(i (built|made|created|designed|finished|completed|ported|trained|added|got|"
    r"replaced|found|crammed|started|used|pushed|served|watch)"
    r"|my \w|we (built|made|did|ported)|show(t|r)?case|introducing|"
    r"look at|check out|presenting|sharing|progress|update|weekend|fun|"
    r"\[.*(pics?|photos?|video|build|project).*\])",
    re.I,
)


def day(u):
    return datetime.fromtimestamp(u or 0, tz=timezone.utc).strftime("%Y-%m-%d")


def heat(p):
    return (p.get("score") or 0) + (p.get("num_comments") or 0)


def title(p):
    return p.get("title") or ""


def body(p):
    return p.get("selftext") or ""


def fulltext(p):
    return title(p) + " " + body(p)


def classify(p):
    """返回 (类别, 命中的主题列表)"""
    ti = title(p)
    if SHOWCASE_TITLE.search(ti) and not TITLE_NEG.search(ti):
        return "showcase", []
    if TITLE_NEG.search(ti):
        return "complaint", []
    if TITLE_Q.search(ti):
        return "help", []
    return "other", []


def load_posts(data_dir):
    """合并目录下所有 *.json 与 *.jsonl，按 id 去重。

    防御（均有实测事故对应）：
      - 顶层非数组的 JSON 直接跳过（meta/聚合产物等）
      - API 偶发返回非 dict 元素，直接 p["id"] 会崩 → 跳过
      - .jsonl 里崩溃残留的半截行 → 跳过
    支持 .jsonl 的意义：fetch 中断且未完成合并时，也能直接对增量流水做分析。
    """
    posts, seen, files = [], set(), 0
    patterns = []
    if Path(data_dir).is_dir():
        patterns += sorted(Path(data_dir).glob("*.json"))
        patterns += sorted(Path(data_dir).glob("*.jsonl"))
    for f in patterns:
        if f.name.endswith("_posts.json"):   # 历史合并产物，避开
            continue
        files += 1
        try:
            if f.suffix == ".jsonl":
                items = []
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except Exception:  # noqa: BLE001  崩溃半截行
                        pass
            else:
                d = json.loads(f.read_text(encoding="utf-8"))
                items = d if isinstance(d, list) else None
                if items is None:
                    print(f"  [skip] {f.name}: 顶层不是数组（{type(d).__name__}）")
                    continue
        except Exception as e:  # noqa: BLE001
            print(f"  [skip] {f.name}: {e}")
            continue
        for p in items:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                posts.append(p)
    if not files:
        print(f"[warn] {data_dir} 下没有找到 *.json / *.jsonl 数据文件")
    return posts


def load_regex_map(path, what):
    """读 {"名称": "正则"} JSON 并编译；坏正则/坏结构给明确报错而不是 traceback。"""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"[fatal] {what} 文件读取失败: {path} ({e})")
    if not isinstance(raw, dict) or not all(
            isinstance(v, str) for v in raw.values()):
        sys.exit(f"[fatal] {what} 文件结构应为 {{\"名称\": \"正则\"}}: {path}")
    out = {}
    for k, v in raw.items():
        try:
            out[k] = re.compile(v, re.I)
        except re.error as e:
            sys.exit(f"[fatal] {what}「{k}」的正则无效: {v!r} ({e})")
    return out


def fmt(p, themes, i, note=""):
    link = "https://www.reddit.com" + (p.get("permalink") or "")
    out = [
        f"**{i}. {title(p).strip()}**",
        f"   r/{p.get('subreddit')} · score {p.get('score')} · "
        f"{p.get('num_comments')} 评论 · {day(p.get('created_utc'))}",
        f"   <{link}>",
    ]
    if themes:
        out.append(f"   主题: {'、'.join(themes)}")
    if note:
        out.append(f"   ★ {note}")
    ex = re.sub(r"\s+", " ", body(p)).strip()[:400]
    if ex:
        out.append(f"> {ex}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", help="fetch_subreddit.py 产出的数据目录")
    ap.add_argument("themes", help="主题表 JSON：{\"主题名\": \"正则\", ...}")
    ap.add_argument("-o", "--output", default="painpoints.md", help="输出 markdown")
    ap.add_argument("--focus", help="品类定向配置 JSON：{\"组名\": \"正则\", ...}")
    ap.add_argument("--focus-min", type=int, default=2, help="定向命中组数阈值（默认 2）")
    ap.add_argument("--top", type=int, default=40, help="每类输出 top N（默认 40）")
    args = ap.parse_args()

    posts = load_posts(args.data_dir)
    if not posts:
        print("没有数据。先跑 fetch_subreddit.py 抓取；若 fetch 中途失败（exit 2），"
              "重跑同一命令续传。")
        return 1
    posts.sort(key=lambda p: -heat(p))

    themes = load_regex_map(args.themes, "主题表")
    focus = load_regex_map(args.focus, "--focus") if args.focus else {}

    buckets = defaultdict(list)
    for p in posts:
        k, _ = classify(p)
        p["_themes"] = [n for n, rx in themes.items() if rx.search(fulltext(p))]
        buckets[k].append(p)

    # 品类定向挖掘
    focus_hits = []
    if focus:
        for p in posts:
            hit = [n for n, rx in focus.items() if rx.search(fulltext(p))]
            if len(hit) >= args.focus_min:
                p["_focus_tags"] = hit
                focus_hits.append(p)
        focus_hits.sort(key=lambda p: (-len(p["_focus_tags"]), -heat(p)))

    def tcount(lst):
        d = defaultdict(int)
        for p in lst:
            for k in p["_themes"]:
                d[k] += 1
        return d

    th_c, th_h = tcount(buckets["complaint"]), tcount(buckets["help"])

    us = [p.get("created_utc") for p in posts if p.get("created_utc")]
    L = [
        "# 痛点分析（标题级判据）",
        "",
        f"**样本** {len(posts)} 帖 · {day(min(us))} .. {day(max(us))}" if us else f"**样本** {len(posts)} 帖",
        "",
        f"- 体验差/翻车类（抱怨）：**{len(buckets['complaint'])}** 帖",
        f"- 卡住了/弄不通类（求助）：**{len(buckets['help'])}** 帖",
        f"- 剔除作品展示帖：{len(buckets['showcase'])} 帖",
    ]
    if focus:
        L.append(f"- 品类定向命中（≥{args.focus_min} 组）：**{len(focus_hits)}** 帖")
    L += [
        "",
        "> 判据：标题级。全文关键词过滤会被 score 2000+ 的晒作品帖霸榜"
        "（实测同一份数据 2819 帖 → 847 帖）。引用前仍需读原文复核语义。",
        "",
        "## 主题频次",
        "",
        "| 主题 | 抱怨类 | 求助类 |",
        "|---|---:|---:|",
    ]
    for k in sorted(set(th_c) | set(th_h), key=lambda x: -(th_c[x] + th_h[x])):
        L.append(f"| {k} | {th_c.get(k, 0)} | {th_h.get(k, 0)} |")

    L += ["", "---", "", "# 一、体验差 / 翻车类（按 score 排）", ""]
    for i, p in enumerate(sorted(buckets["complaint"], key=lambda p: -(p.get("score") or 0))[:args.top], 1):
        L += [fmt(p, p["_themes"], i), ""]

    L += ["", "---", "", "# 二、卡住了 / 弄不通类（按 score+comments 排）", ""]
    for i, p in enumerate(buckets["help"][:args.top], 1):
        L += [fmt(p, p["_themes"], i), ""]

    if focus:
        L += ["", "---", "", f"# 三、品类定向（命中 ≥{args.focus_min} 组）", ""]
        for i, p in enumerate(focus_hits[:args.top], 1):
            L += [fmt(p, p["_themes"], i, "、".join(p["_focus_tags"])), ""]

    Path(args.output).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.output}  样本 {len(posts)} | 抱怨 {len(buckets['complaint'])} "
          f"| 求助 {len(buckets['help'])} | showcase {len(buckets['showcase'])}"
          + (f" | 定向 {len(focus_hits)}" if focus else ""))
    print("--- 主题频次 (抱怨/求助) ---")
    for k in sorted(set(th_c) | set(th_h), key=lambda x: -(th_c[x] + th_h[x])):
        print(f"  {k:<26} {th_c.get(k, 0):4d} / {th_h.get(k, 0):4d}")


if __name__ == "__main__":
    sys.exit(main())
