# -*- coding: utf-8 -*-
"""标题级痛点分析（通用工具）—— 自动规避"作品展示帖霸榜"

用法:
    python analyze_title_level.py <data_dir> <themes.json> [-o out.md] [--focus <focus.json>]
                                  [--scope <正则>] [--showcase-top N]

    <data_dir>    fetch_subreddit.py 产出的目录（*.json 与 *.jsonl 都会读，
                  每篇含 id/title/score/selftext/...；中断未合并的流水也能直接分析。
                  读 *.jsonl 时若存在同名 *.meta，会按其中 cutoff 过滤窗口外帖子，
                  保证分析样本与 fetch 合并产物口径一致）
    <themes.json> 主题表：{"主题名": "正则", ...}，用于给帖子打主题标签
    -o out.md     输出 markdown（默认 painpoints.md）
    --focus       可选：品类定向挖掘配置 {"组名": "正则", ...}，
                  命中 >= --focus-min 组数的帖会被单独列出（默认 2 组）
    --scope       可选：调研目标相关性正则（品类/产品关键词）。输出「数据-目标
                  相关帖占比」审计：<30% 说明数据混入大量无关 sub/话题，先修数据
                  再写报告，否则报告内容必然与调研要求脱节
    --showcase-top N  额外计算「Top N 高互动帖中展示帖占比」（默认 30），
                  >50% 说明该 sub 属情感展示型，痛点必须关键词定向挖掘，
                  不能靠热度排序（否则会得出"口碑极好、无痛点"的反向结论）

输出末尾还会给出「评论树补刀建议」：直接复制可执行的 comment_tree 命令，
选帖来自痛点/口碑层（complaint+help 的热度 top）——**不是全局热度 top**。
全局 top 大概率是展示帖，给晒单帖抓评论只会收获一片 "Awesome!"，
这些夸赞流进痛点报告就是「内容与调研要求不相关」。

为什么需要这个（实测教训，2026-10）:
  r/esp32 这类高活跃sub 里，"I built an X" 作品展示帖score 可达 2031，
  比任何痛点帖都高。若用全文关键词过滤，排前列的全是晒作品。
  → 实测同一份数据（7055 帖）：全文判据召回 2819 帖（40%，污染严重）
    → 标题级判据收敛到847 帖（纯度可用）
  原理：晒作品帖的标题几乎不会写成疑问句或抱怨句，所以判据放标题级。

分类输出五类（判据顺序即优先级，NEG 最高）:
  complaint 标题含抱怨/失败信号   → 痛点
  help      标题为疑问求助句（含问号）→ 痛点（工程社区里求助帖占多数）
  showcase  标题为作品展示        → 剔除
  praise    标题为纯称赞且无 pain 信号 → 口碑/特性素材（情绪三分，避免好评率虚高）
  other     其余（低置信，抽样复核后再用）

主题表用法示例（themes_esp32.json 见同目录）:
  {
    "电源/电池": "batter|charg|power|vcc|\\b5v\\b|3\\.3v",
    "连接稳定性": "wifi|\\bble\\b|bluetooth|disconnect|mqtt"
  }
  ⚠️ 短词（ap/log/can/pin/ram/doc/ota/bt/vin/ble 等）必须加 \\b 词边界，
  否则 "app"/"happy"/"program"/"rotation"/"docker"/"shipping"/"available"
  都会被误命中，主题频次表会整体虚高。
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
# ⚠️ crash 用 (?! ?course) 排除 "crash course"；fail 用 \b 防止匹配误伤
TITLE_NEG = re.compile(
    r"(broken|break(?:s|ing)? (up|apart|down)|broke|died|dead|dying|burn|smoke|smoking|"
    r"bricke?d|unbrick|fake|counterfeit|clone|defective|doa|"
    r"stopped (working|charging|connecting)|no longer works|not working|doesn'?t work|won'?t work|"
    r"overheat\w*|too hot|melt\w*|"
    r"(disappoint\w*|frustrat\w*|regret\w*|nightmare|terrible|horrible|awful|worst|useless|"
    r"worthless|garbage|junk|sucks|rip.?off|scam\w*|bad experience|not worth|waste of (money|time))"
    r"|(gave up|give up|abandon\w*|never again|last time|moved on|switched to)"
    r"|(hard|struggl\w*|difficult|trouble) (to|with)|hate(s|d)?|angry|annoying|infuriating|"
    r"inaccurate|unreliable|unusable|unstable|flaky|intermittent|flimsy|"
    r"warning|be careful|beware|avoid|caveat|lessons? learned|"
    r"can'?t get|can'?t figure|can'?t make|couldn'?t get|couldn'?t figure|"
    r"not detectable|not recognized|not recognised|not showing up|not responding|"
    r"not (charging|connecting|pairing|flashing|booting|syncing|powering)|"
    r"won'?t (boot|start|connect|pair|flash|turn on|power|sync|link)|"
    r"out of memory|stack overflow|"
    r"bootloop|boot loop|keeps? resetting|randomly (reboot|disconnect|crash)"
    r"|\bfail(s|ed|ing|ure|ures)?\b|crash(es|ed|ing)?(?! ?course)"
    r"|reboot(s|ing)?\b|disconnect(s|ed|ing)?\b|drain(s|ed|ing)?\b"
    r"|freezes?|froze|frozen|freezing|lag(s|gy|ging)?\b|jitter\w*|stutter\w*"
    r"|keeps? (re)?(boot\w*|restart\w*|crash\w*|disconnect\w*|freez\w*|reset\w*|dropp\w*|fail\w*)"
    r"|wrong (reading|value|data|result|temp|time)|loses? (connection|power|time|data)"
    # 消费品品质类失败信号（电商/美妆/穿戴调研高频；避开常见误命中，见行内注释）
    r"|\bsheds\b|shedding|shed (a lot|like crazy|everywhere|hair)"   # 避开 "shed some light"/"garden shed"
    r"|tangl\w*|matt(ing|ed)\b|frizz\w*|fray(ed|ing)\b|fad(ed|ing)\b" # 避开 "skin fade"请求、"the fray"名词
    r"|peel(ing|ed)\b|shrink(s|ing|age)?\b|pilling|snag(ged|ging)?\b"
    r"|\bitchy\b|\bitches\b|\bitching\b(?! to\b)"   # 排除习语 "itching to try"
    r"|smells? (bad|awful|terrible|weird|funny|burnt|like (chemical|plastic|burnt))|smelly|stinks?|stinking|\bodor\b"
    r"|slip(s|ped|ping)? (off|down|out)\b|tear(s|ing)?\b|tore\b"
    r"|\bpain(ful)?\b|headache|nightmare fuel)",
    re.I,
)

# 纯称赞信号（praise 判定要求无 pain 信号、非疑问，情绪三分用）
TITLE_POS = re.compile(
    r"(works? (great|perfectly|like a charm|flawlessly|beautifully)|working (great|perfectly|flawlessly)"
    r"|love(d|s)? (it|this|these|them|my)|highly recommend"
    r"|best (purchase|buy|decision|investment|upgrade)"
    r"|game.?changer|must.?have|exceeded (my |our )?expectations"
    r"|worth every (penny|dollar|cent)|no (regrets|complaints)"
    r"|amazing|awesome|flawless|solid (build|quality|choice|pick|performance)"
    r"|very (happy|pleased|satisfied)|super happy|really (happy|impressed|pleased)"
    r"|impressed|10/10|five stars)",
    re.I,
)

# 作品展示帖（标题级）——这类不是痛点
# 前两个分支处理 "Just sharing..." / "Finally finished..." 这类带前缀限定词的展示帖
SHOWCASE_TITLE = re.compile(
    r"^\s*((just|finally) (sharing|showing|showed|showed off|finished|completed|got|built|made|created|ported)"
    r"|i (built|made|created|designed|finished|completed|ported|trained|added|got|"
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
    """返回类别字符串。判据顺序 = 优先级：NEG > Q(含问号) > showcase > praise > other。

    ⚠️ 旧版先判 showcase 再判 NEG/Q，导致大量真痛点帖被展示帖模式吞掉——
    例如 "My ESP32 keeps rebooting"（my \\w 命中 showcase、"keeps rebooting"
    不在旧 NEG 词表）会被误剔出痛点集。现改为 NEG/Q 优先，且含问号的标题
    一律按求助处理（晒作品帖标题几乎不写问号）。"""
    ti = title(p)
    if TITLE_NEG.search(ti):
        return "complaint"
    if TITLE_Q.search(ti) or "?" in ti:
        return "help"
    if SHOWCASE_TITLE.search(ti):
        return "showcase"
    if TITLE_POS.search(ti):
        return "praise"
    return "other"


def cutoff_for(f: Path):
    """读取与数据文件同名的 .meta（fetch_subreddit.py 的窗口元数据），返回 cutoff。
    <sub>.json / <sub>.jsonl → <sub>.meta。没有 meta 返回 None（不做窗口过滤）。"""
    mp = f.parent / (f.stem + ".meta")
    if not mp.exists():
        return None
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        c = m.get("cutoff")
        return int(c) if c else None
    except Exception:  # noqa: BLE001  meta 损坏不阻塞分析
        return None


def load_posts(data_dir):
    """合并目录下所有 *.json 与 *.jsonl，按 id 去重；有 .meta 的文件按 cutoff
    过滤窗口外帖子（jsonl 的最后一页通常已越过窗口底，不过滤会导致分析样本
    比 fetch 合并产物偏大——报告口径于是对不上，数字闭环直接破裂）。

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
    out_of_window = 0
    for f in patterns:
        files += 1
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
            if not pid or pid in seen:
                continue
            if cut is not None and (p.get("created_utc") or 0) < cut:
                out_of_window += 1
                continue
            seen.add(pid)
            posts.append(p)
    if not files:
        print(f"[warn] {data_dir} 下没有找到 *.json / *.jsonl 数据文件")
    if out_of_window:
        print(f"[info] 已按 .meta cutoff 剔除窗口外 {out_of_window} 帖（口径与 fetch 产物一致）")
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
    score = p.get("score")
    score = "?" if score is None else score
    out = [
        f"**{i}. {title(p).strip()}**",
        f"   r/{p.get('subreddit')} · score {score} · "
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
    ap.add_argument("--scope", help="调研目标相关性正则（品类/产品关键词），输出数据体检占比")
    ap.add_argument("--showcase-top", type=int, default=30,
                    help="计算「Top N 高互动帖中展示帖占比」的 N（默认 30）")
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
        k = classify(p)
        p["_themes"] = [n for n, rx in themes.items() if rx.search(fulltext(p))]
        buckets[k].append(p)

    # 规则3 必做校验：Top N 高互动帖中的展示帖占比
    # >50% → 情感展示型，痛点必须关键词定向挖掘（热度排序会得出"无痛点"反向结论）
    top = posts[:args.showcase_top]
    show_ids = {p.get("id") for p in buckets["showcase"]}
    top_show = sum(1 for p in top if p.get("id") in show_ids)
    share = (top_show / len(top) * 100) if top else 0.0
    if share > 50:
        share_verdict = "⚠ >50% → 情感展示型！痛点必须用关键词定向筛选，不能靠热度排序发现"
    elif share <= 30:
        share_verdict = "✓ ≤30% → 热度排序基本可用"
    else:
        share_verdict = "△ 30–50% → 部分可用，引用前需逐帖复核是否晒单"
    if top:
        print(f"Top{len(top)} 高互动帖中展示帖占比: {share:.1f}%  {share_verdict}")

    # ---- 数据体检 1：sub 构成（发现混入无关 sub，如假发调研混进 tasmota）----
    subs = defaultdict(int)
    for p in posts:
        subs[str(p.get("subreddit") or "?")] += 1
    sub_parts = [f"r/{s} {c} ({c * 100.0 / len(posts):.1f}%)"
                 for s, c in sorted(subs.items(), key=lambda kv: -kv[1])]
    shown = "、".join(sub_parts[:10]) + (f" …共 {len(subs)} 个 sub" if len(subs) > 10 else "")
    print(f"数据构成: {shown}")

    # ---- 数据体检 2：与调研目标的相关性审计（--scope）----
    scope_note = ""
    scope_rx = None
    if args.scope:
        try:
            scope_rx = re.compile(args.scope, re.I)
        except re.error as e:
            sys.exit(f"[fatal] --scope 正则无效: {args.scope!r} ({e})")
        relevant = [p for p in posts if scope_rx.search(fulltext(p))]
        rel_share = len(relevant) * 100.0 / len(posts)
        if rel_share < 30:
            scope_verdict = ("✗ <30% → 数据与调研目标严重脱节！无关帖混入太多，"
                             "先检查数据构成/换 sub/收紧时间窗，否则报告必然答非所问")
        elif rel_share < 60:
            scope_verdict = "△ 30–60% → 相关性一般，写报告时必须只取相关帖，无关帖不得引用"
        else:
            scope_verdict = "✓ ≥60% → 数据与目标相关性良好"
        scope_note = f"- **数据-目标相关性：{len(relevant)}/{len(posts)} 帖（{rel_share:.1f}%）** — {scope_verdict}"
        print(scope_note.lstrip("- "))

    # ---- 评论树补刀建议：痛点/口碑层的 top（不是全局 top）----
    def _rank(c):
        return (0 if scope_rx is None or scope_rx.search(fulltext(c)) else 1, -heat(c))

    def _pick(bucket):
        cand = sorted(bucket, key=_rank)[:5]
        if scope_rx is not None:   # scope 模式下严格过滤：无关帖不补位（宁少勿跑题）
            cand = [p for p in cand if scope_rx.search(fulltext(p))]
        return cand

    cands = _pick(buckets["complaint"]) + _pick(buckets["help"])
    suggest_cmd = ""
    if cands:
        ids = " ".join(str(p.get("id")) for p in cands if p.get("id"))
        suggest_cmd = f"python scripts/comment_tree.py {ids} -t 12"
        tail = "，已按 --scope 只保留相关帖" if scope_rx is not None else ""
        print(f"评论树补刀建议（痛点层 top {len(cands)}{tail}，直接复制执行）:\n  {suggest_cmd}")

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
        f"- 纯称赞（praise，可作口碑/特性素材）：{len(buckets['praise'])} 帖",
        f"- 其他（低置信，引用前需逐帖复核）：{len(buckets['other'])} 帖",
    ]
    if top:
        L.append(f"- **Top{len(top)} 高互动帖中展示帖占比：{share:.1f}%** — {share_verdict}")
    if scope_note:
        L.append(scope_note)
    L.append(f"- 数据构成：{shown}")
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

    if suggest_cmd:
        extra = (["", "> 已按 `--scope` 过滤：候选只保留与调研目标相关的帖（宁少勿跑题）。"]
                 if scope_rx is not None else [])
        L += ["", "---", "", "## 下一步：评论树补刀（痛点/口碑层 top，非全局热度 top）", "",
              "```bash", suggest_cmd, "```",
              "",
              "> 选帖来自 complaint+help 层。**不要对全局热度 top 抓评论**——那大概率是",
              "> 展示帖，评论只会是 \"Awesome!\"，写进痛点报告就是答非所问。",
              "> 生态背景最多另选 1–2 个最高分展示帖做参照，引用时注明「展示帖」。"] + extra

    Path(args.output).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {args.output}  样本 {len(posts)} | 抱怨 {len(buckets['complaint'])} "
          f"| 求助 {len(buckets['help'])} | showcase {len(buckets['showcase'])} "
          f"| praise {len(buckets['praise'])} | other {len(buckets['other'])}"
          + (f" | 定向 {len(focus_hits)}" if focus else ""))
    print("--- 主题频次 (抱怨/求助) ---")
    for k in sorted(set(th_c) | set(th_h), key=lambda x: -(th_c[x] + th_h[x])):
        print(f"  {k:<26} {th_c.get(k, 0):4d} / {th_h.get(k, 0):4d}")


if __name__ == "__main__":
    sys.exit(main())
