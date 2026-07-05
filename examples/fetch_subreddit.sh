#!/usr/bin/env bash
# fetch_subreddit.sh — 从 Arctic Shift 全量翻页拉取某 subreddit 的帖子
#
# 用法:   ./fetch_subreddit.sh <subreddit> [max_pages] [outfile]
# 示例:   ./fetch_subreddit.sh ouraring 60 posts.json
#
# 特性: before 游标分页(新→旧) / 瞬时空响应自动重试 / 字段裁剪 / 按 id 去重
# 依赖: curl + jq
# 产出: outfile 为去重后的 JSON 数组, 字段 {id,title,score,num_comments,created_utc,permalink,selftext,author}
#
# 速度参考: 100 帖/页; 一个日更 60-80 帖的活跃 sub, 60 页 ≈ 近 3 个月。
set -euo pipefail

SUB="${1:?用法: $0 <subreddit> [max_pages] [outfile]}"
PAGES="${2:-30}"
OUT="${3:-${SUB}_posts.json}"
BASE="https://arctic-shift.photon-reddit.com/api/posts/search"
UA="reddit-research/1.0"

command -v jq >/dev/null || { echo "需要 jq: https://jqlang.org/download/" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
before=""

for ((i = 1; i <= PAGES; i++)); do
  url="${BASE}?subreddit=${SUB}&limit=100&sort=desc"
  [ -n "$before" ] && url="${url}&before=${before}"

  # 瞬时空响应是常态, 重试 3 次再判定到头
  n=0
  for try in 1 2 3; do
    resp="$(curl -s "$url" -H "User-Agent: $UA")"
    n="$(echo "$resp" | jq '.data | length' 2>/dev/null || echo 0)"
    [ "$n" != "null" ] && [ "$n" -gt 0 ] 2>/dev/null && break
    n=0
    sleep 1
  done
  if [ "$n" -eq 0 ]; then
    echo "第 ${i} 页为空(已重试), 认为到达档案尽头, 停止。" >&2
    break
  fi

  # 字段裁剪: 原始一条 ~4KB, 只留分析必需字段
  echo "$resp" | jq -c '.data[] | {id, title, score, num_comments, created_utc, permalink, selftext: ((.selftext // "") | .[0:1200]), author}' >> "$tmp"

  oldest="$(echo "$resp" | jq '[.data[].created_utc] | min')"
  before=$((oldest - 1))   # -1 防死循环; 极小概率漏同一秒被截断的帖子, 可接受
  echo "页 ${i}/${PAGES}: +${n} 帖, 游标 created_utc < ${oldest}" >&2
done

jq -s 'unique_by(.id) | sort_by(-.created_utc)' "$tmp" > "$OUT"
total="$(jq 'length' "$OUT")"
span="$(jq -r '"\(([.[].created_utc] | min | todate)[0:10]) .. \(([.[].created_utc] | max | todate)[0:10])"' "$OUT")"
echo "完成: ${total} 帖 (去重后) → ${OUT}, 时间跨度 ${span}" >&2
