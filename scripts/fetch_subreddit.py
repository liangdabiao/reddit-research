#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reddit-research: Arctic Shift 全量分页拉取（健壮版，SKILL.md 模板 B）

用法:
    python fetch_subreddit.py <subreddit> <days> <out.json> [--fresh] [--quiet]
    python fetch_subreddit.py esp32 30 data/esp32.json

产物（out = data/esp32.json 时）:
    data/esp32.json        最终结果：窗口内帖子列表，按时间倒序（分析脚本读这个）
    data/esp32.jsonl       增量流水：每抓一页立即 append，崩溃/中断不丢已抓数据
    data/esp32.json.meta   采集窗口元数据：续传时固定 cutoff，避免重跑时窗口漂移
    data/esp32.log         运行日志（排障用）

可靠性设计（每条都对应实测踩过的坑，见 references/api_endpoints.md）:
    1. 自动创建输出目录（曾因目录不存在，172 页抓完后最后一步 open() 失败整批归零）
    2. 每页增量落盘 jsonl + 最终原子合并（写临时文件后 os.replace，合并中途崩溃不毁旧结果）
    3. 断点续传：中断/失败后重跑同一命令，从 jsonl 断点继续，已抓部分不重拉
       （注意：续传只向下补更老的帖子；断点之后的新帖不会被补进来，
         需要覆盖新帖时删掉 .jsonl/.json.meta 或加 --fresh 重跑）
    4. API 响应防御：非 dict 元素跳过、data 非列表报错（非 dict 元素曾致 AttributeError 整批归零）
    5. 空响应按文档规则重试 3 次再判定到头（偶发瞬时空响应，不重试会静默截断数据）
    6. 网络/5xx/429 退避重试 4 次；4xx 快速失败不浪费时间重试
    7. 退出码：0=完整完成；2=部分数据（网络放弃或 Ctrl+C，已保存可续传）；1=用法/参数错误
    8. 防卡死：连续多页 0 新帖（服务端异常重复返回同一页）自动终止

纯标准库，无第三方依赖。Windows 控制台中文输出已处理。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
UA = "reddit-research/1.2"
KEEP = ("id", "title", "score", "num_comments", "created_utc",
        "permalink", "selftext", "author", "subreddit", "link_flair_text")
SELFTEXT_MAX = 1200

NET_RETRY = 4        # 网络错误 / 5xx / 429 / error JSON 的重试次数
EMPTY_RETRY = 3      # 空响应重试次数（文档：偶发瞬时空响应，重试即恢复）
PAGE_SLEEP = 0.35    # 分页间隔（秒），顺序执行不并发
STALL_PAGES = 3      # 连续 N 页 0 新帖 → 判定服务端异常，终止


class FetchError(Exception):
    """重试耗尽或不可重试的错误"""


class Logger:
    def __init__(self, path, quiet=False):
        self.f = open(path, "a", encoding="utf-8")
        self.quiet = quiet

    def __call__(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.f.write(f"{stamp} {msg}\n")
        self.f.flush()
        if not self.quiet:
            print(msg, flush=True)

    def close(self):
        try:
            self.f.close()
        except Exception:  # noqa: BLE001
            pass


def sleep_backoff(i):
    time.sleep(min(2.0 * (i + 1), 12.0))


def fetch(url):
    """请求一页并返回 data 列表。防御非 dict 元素之外的畸形；重试耗尽抛 FetchError。"""
    last = None
    for i in range(NET_RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            d = json.loads(body)
            if not isinstance(d, dict):
                raise RuntimeError(f"响应顶层非对象: {type(d).__name__}")
            if "error" in d:
                raise RuntimeError(f"服务端 error: {d['error']}")
            data = d.get("data", [])
            if not isinstance(data, list):
                raise RuntimeError(f"data 非列表: {type(data).__name__}")
            return data
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            last = f"HTTP {e.code}: {body}"
            if e.code == 429 or e.code >= 500:
                sleep_backoff(i)      # 限流/服务端故障 → 退避重试
                continue
            raise FetchError(last)     # 4xx → 重试无意义，快速失败
        except Exception as e:  # noqa: BLE001  网络/超时/JSON 解析等瞬态错误
            last = f"{type(e).__name__}: {e}"
            sleep_backoff(i)
    raise FetchError(f"重试 {NET_RETRY} 次仍失败: {last}")


def trim(p):
    """裁剪保留字段；返回规范化 dict。调用方需已确认 p 是 dict。"""
    o = {k: p.get(k) for k in KEEP}
    st = o.get("selftext")
    o["selftext"] = st[:SELFTEXT_MAX] if isinstance(st, str) else ""
    fl = o.get("link_flair_text")
    o["link_flair_text"] = fl if isinstance(fl, str) else None
    return o


def side_paths(out: Path):
    """out=data/esp32.json → (esp32.jsonl, esp32.meta, esp32.log)。
    meta/log 后缀不带 .json 结尾，避免被 analyze_title_level.py 的 *.json glob 误读。"""
    base = str(out.with_suffix("")) if out.suffix else str(out)
    return (Path(base + ".jsonl"), Path(base + ".meta"), Path(base + ".log"))


def load_checkpoint(jsonl_path: Path, log):
    """读取增量流水，返回 (seen_ids, 已抓最小 created_utc)。坏行跳过并计数。"""
    seen, oldest, bad = set(), None, 0
    if not jsonl_path.exists():
        return seen, oldest, 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except Exception:  # noqa: BLE001  崩溃时的半截行
                bad += 1
                continue
            if isinstance(p, dict) and p.get("id"):
                seen.add(p["id"])
                u = p.get("created_utc") or 0
                oldest = u if oldest is None else min(oldest, u)
    if bad:
        log(f"  [warn] checkpoint 有 {bad} 行坏数据（崩溃残留），已跳过")
    return seen, oldest, bad


def merge_final(jsonl_path: Path, out: Path, cutoff, log):
    """jsonl → 去重 + 窗口过滤 → 原子写入 out。"""
    seen, uniq = set(), []
    bad = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except Exception:  # noqa: BLE001
                bad += 1
                continue
            if not isinstance(p, dict) or not p.get("id") or p["id"] in seen:
                continue
            seen.add(p["id"])
            if (p.get("created_utc") or 0) >= cutoff:
                uniq.append(p)
    uniq.sort(key=lambda p: -(p.get("created_utc") or 0))
    tmp = Path(str(out) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False)
    tmp.replace(out)  # 原子替换，中途崩溃不毁旧文件
    return len(uniq), bad


def main():
    ap = argparse.ArgumentParser(
        description="Arctic Shift 全量分页拉取（增量落盘 + 断点续传 + 崩溃不丢数据）")
    ap.add_argument("subreddit", help="目标 subreddit，不带 r/ 前缀")
    ap.add_argument("days", type=int, help="时间窗（天）")
    ap.add_argument("out", help="输出 JSON 路径，如 data/esp32.json")
    ap.add_argument("--fresh", action="store_true",
                    help="忽略已有断点，从头重抓（清空 jsonl/meta）")
    ap.add_argument("--quiet", action="store_true", help="只写日志不刷控制台进度")
    args = ap.parse_args()

    sub, days = args.subreddit.strip().removeprefix("r/"), args.days
    if days <= 0:
        print("days 必须为正整数", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)          # 坑1：目录不存在
    jsonl, meta_p, log_p = side_paths(out)
    log = Logger(log_p, quiet=args.quiet)

    if args.fresh:
        for p in (jsonl, meta_p):
            p.unlink(missing_ok=True)

    # 采集窗口：首跑时定死并写入 meta，续传沿用，避免重跑时 cutoff 漂移
    now = int(time.time())
    cutoff = now - days * 86400
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log(f"  [fatal] meta 损坏（{e}），删掉 {meta_p.name} 或加 --fresh 重跑")
            return 1
        if meta.get("subreddit", "").lower() != sub.lower():
            log(f"  [fatal] {meta_p.name} 记录的 sub 是 r/{meta.get('subreddit')}，"
                f"与本次 r/{sub} 不符。换输出路径，或加 --fresh 重抓")
            return 1
        cutoff = int(meta["cutoff"])
    else:
        meta_p.write_text(json.dumps(
            {"subreddit": sub, "days": days, "cutoff": cutoff,
             "started_utc": now, "started": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False, indent=1), encoding="utf-8")

    seen, cp_oldest, _ = load_checkpoint(jsonl, log)
    before = cp_oldest - 1 if cp_oldest is not None else None
    log(f"[r/{sub}] 窗口 {days} 天 (cutoff={cutoff}, "
        f"{datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime('%Y-%m-%d')} 起)"
        + (f" | 断点续传: 已有 {len(seen)} 帖, 从 {cp_oldest} 继续" if seen else ""))

    pages, empty_streak, stall = 0, 0, 0
    complete = False
    stop_reason = ""
    if cp_oldest is not None and cp_oldest < cutoff:
        complete = True                       # 上次已拉过窗口底，无需任何网络请求
        stop_reason = "断点已越过 cutoff，直接合并"
    try:
        while not complete:
            url = f"{BASE}?subreddit={sub}&limit=100&sort=desc"
            if before is not None:
                url += f"&before={before}"
            try:
                data = fetch(url)
            except FetchError as e:
                stop_reason = f"网络放弃: {e}"
                log(f"  [fatal] {stop_reason} — 已增量保存 {len(seen)} 帖，"
                    f"重跑同一命令即可续传")
                break

            if not data:
                empty_streak += 1
                if empty_streak <= EMPTY_RETRY:
                    log(f"  [warn] 空响应 (第 {empty_streak}/{EMPTY_RETRY} 次)，"
                        f"{2 * empty_streak}s 后重试")
                    time.sleep(2 * empty_streak)
                    continue
                complete = True                      # 重试后仍空 → 真到头
                stop_reason = "数据到头（空响应）"
                break

            empty_streak = 0
            pages += 1
            posts, skipped = [], 0
            for p in data:                           # 坑4：非 dict 元素防御
                if isinstance(p, dict):
                    posts.append(trim(p))
                else:
                    skipped += 1
            fresh = 0
            with open(jsonl, "a", encoding="utf-8") as jf:
                for t in posts:
                    pid = t.get("id")
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    jf.write(json.dumps(t, ensure_ascii=False) + "\n")
                    fresh += 1
            if skipped:
                log(f"  [warn] 本页跳过 {skipped} 个非 dict 畸形元素")

            times = [t.get("created_utc") or 0 for t in posts]
            oldest = min(times) if times else 0
            oldest_day = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime(
                "%Y-%m-%d") if oldest else "?"
            log(f"  page {pages:4d} | raw={len(data):3d} new={fresh:3d} "
                f"total={len(seen):6d} oldest={oldest_day}")

            if oldest and oldest < cutoff:
                complete = True
                stop_reason = f"已拉过 cutoff（{oldest_day} < 窗口起点）"
                break

            stall = stall + 1 if fresh == 0 else 0   # 坑8：防服务端重复返回同一页
            if stall >= STALL_PAGES:
                stop_reason = f"连续 {STALL_PAGES} 页 0 新帖，判定服务端分页异常，终止"
                log(f"  [warn] {stop_reason}")
                break

            before = oldest - 1
            time.sleep(PAGE_SLEEP)
    except KeyboardInterrupt:
        stop_reason = "用户中断 (Ctrl+C)"

    total, bad = merge_final(jsonl, out, cutoff, log)
    if bad:
        log(f"  [warn] 合并时跳过 {bad} 行坏数据")
    status = "完整完成" if complete else "部分数据（可续传）"
    log(f"[r/{sub}] {status}: {total} 帖 / {pages} 页 | 原因: {stop_reason} -> {out}")
    log.close()
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
