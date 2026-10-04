# Arctic Shift API 参考

> 完整方法与工作流见 `SKILL.md`。本文档仅在需要端点参数、错误码细节或备路径时加载。
> 实测日期：2026-10-04（脚本重写 + aggregate 参数修正）、2026-10-03（端点可用性快照）、2026-07-05（limit 范围）。

## Base URL 与通用约定

```
https://arctic-shift.photon-reddit.com
```

- 免认证，`curl` 直接调用
- 请求带 User-Agent：`-H "User-Agent: reddit-research/1.2"`
- 速率：每秒几次无问题；**单个 sub 的分页必须串行**（限速 + 保序）；**多个 sub 之间可并行**（各自独立进程/输出/日志，见 deep_research 坑2b）
- 数据滞后约 36 小时，不适合实时事件监控

## 端点速查

| 端点 | 功能 | 关键参数 |
|------|------|---------|
| `/api/posts/search` | 搜/列帖子 | `subreddit`, `limit`(1–100), `sort`(asc/desc), `before`/`after`(epoch 秒), `title`, `selftext`, `author`, `flair` |
| `/api/comments/search` | 搜/列评论 | 同上（正文过滤参数为 `body`） |
| `/api/comments/tree?link_id=t3_<帖ID>` | 某帖完整评论树（含折叠评论） | `link_id` 必须带 `t3_` 前缀；不存在的帖返回 200 + 空 data，与零评论帖无法区分 |
| `/api/posts/ids` / `/api/comments/ids` | 按 ID 批量取 | 每次最多 500 个 |
| `/api/posts/search/aggregate` | 聚合统计 | **`aggregate`**（取值 `created_utc` / `author` / `subreddit`）+ `subreddit` + `after`/`before`。⚠️ **没有 `groupBy` 参数**（会报 Unknown query parameter）。返回 `{"data":[{"key":"esp32","count":"1173"}]}`，**count 是字符串**。偶发 HTTP 422 为瞬态过载，重发即恢复（与关键词查询的永久 422 不同） |
| `/api/time_series` | 关键词讨论量随时间趋势 | 未实测验证，用前先自检 |

**limit 实测**：有效范围 **1–100**。传 `auto` 也只返回 100，传 >100 直接报 `'limit' must be between 1 and 100`。（旧资料称 auto 可返回 100–1000，已过时。）

## ⚠️ 端点可用性快照（2026-10-03 复测）

| 能力 | 状态 |
|------|------|
| 纯列表拉取（`subreddit` + `limit` + `sort` + `before`） | ✅ 可用（唯一稳定通道） |
| 评论树 `comments/tree` | ✅ 可用 |
| **服务端关键词过滤**（posts 的 `title`/`selftext`、comments 的 `body`） | ❌ 不可用，且错误形态具有误导性 |

### 三种错误形态对照表

| 请求形态 | 实际返回 | 判定 |
|---|---|---|
| 全站无 sub 限定 `?title=x` / `?selftext=x` / `?body=x` | **HTTP 400** | 服务端拒绝该组合 |
| 带 sub 限定 `?subreddit=X&title=x` / `&body=x` | **HTTP 422** 或 `{"error":"Timeout. Maybe slow down a bit"}` | 关键词过滤不可用，**不是限流** |
| 无关键词 `?subreddit=X&limit=100&sort=desc` | ✅ 正常 | 纯列表通道健康 |

**关键：`422 "Timeout. Maybe slow down a bit"` 极具误导性。** 它诱导加退避重试，但对关键词查询重试永远无效（实测退避 6 次仍 400/422），曾在此浪费 39 分钟。
**看到 400 或 422 且 URL 带关键词参数 → 立即改走全量拉取 + 本地过滤，不要重试。**

### 自检命令

返回帖子 JSON → 关键词搜索已恢复，可用服务端过滤；返回 error/400/422 → 走全量拉取：

```bash
curl -s -o /dev/null -w "%{http_code}" "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=BuyItForLife&title=test&limit=1" -H "User-Agent: reddit-research/1.0"
```

## 模板 A：服务端关键词搜索（当前不可用，仅自检 200 时使用）

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=ouraring&title=subscription&limit=100" -H "User-Agent: reddit-research/1.0"
```

⚠️ 即使该通道恢复，品牌/产品名调研仍需注意：**品牌名几乎不出现在标题，而在正文和评论里**。实测假发品牌 `unice/luvme/nadula/alipearl` 的 `?title=` 全站查询命中 **0 帖**。必须同时覆盖 `selftext`（正文）与 `/api/comments/search?body=`（评论层），三者合并去重才完整。

## 模板 B：全量拉取 + 本地过滤（当前推荐主路径）

分页规则（已实测验证，`fetch_subreddit.py` 已内置）：

1. 首页：`?subreddit=X&limit=100&sort=desc`（不带 `before`）
2. 取本页最小 `created_utc`，下一页带 `before=<该值-1>`（`-1` 防死循环；若某一秒内帖子数 >100，边界秒的同刻帖可能截断，正常 sub 不会遇到）
3. **空响应先重试 2–3 次再判定到头**——实测偶发瞬时空响应，重试即恢复（脚本已自动做）
4. 全部拉完后按 `id` 去重

执行脚本（纯标准库，无需 jq；增量落盘 + 断点续传 + 崩溃不丢数据）：

```bash
python3 scripts/fetch_subreddit.py <subreddit> <days> <out.json> [--fresh]
```

产物与行为：

| 文件 | 说明 |
|---|---|
| `<out>.json` | 最终结果（窗口内帖子列表，时间倒序）；分析脚本读这个 |
| `<out>.jsonl` | 每页增量流水——崩溃/中断不丢；也是续传依据 |
| `<out>.meta` | 窗口元数据（cutoff 定死，续传不漂移）；换 sub 重用同路径会报错，加 `--fresh` 或换路径 |
| `<out>.log` | 运行日志（含每页 raw/new/total/oldest） |

退出码：**0**=完整完成；**2**=部分数据（网络放弃或 Ctrl+C，**重跑同一命令续传**）；**1**=参数错误。
开跑前用 `probe_subreddit.py --days <窗口>` 拿精确帖量预估页数（页数 = 帖量/100 向上取整），超 50 页先与用户确认。

字段裁剪建议（原始单帖 ~4KB，多为无用元数据）：

```
{id, title, score, num_comments, created_utc, permalink, selftext(截断到千字左右), author}
```

## 模板 C：评论树

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=t3_1uff7ix" -H "User-Agent: reddit-research/1.0"
```

或直接用脚本（无需 jq，支持批量/重试，单帖失败不拖垮整批）：

```bash
python3 scripts/comment_tree.py <post_id> [<post_id2> ...] [-t topN] [-o out.md]
```

有 jq 时的等价命令：

```bash
... | jq -r '[.. | objects | select(.body? and .score?)] | unique_by(.id) | sort_by(-.score) | .[0:10][] | "[s=\(.score)] \(.author): \(.body | gsub("\n";" ") | .[0:200])\n  https://www.reddit.com\(.permalink)"'
```

## 备路径（主路径不满足时）

| 路径 | 何时用 | 要点 |
|------|--------|------|
| Arctic Shift Web UI | 人工浏览验证 | https://arctic-shift.photon-reddit.com/search |
| reddit-mcp-buddy + OAuth | 需要 MCP 工具风格 / 更高速率 | 需自建 Reddit App（client_id/secret）；**匿名模式实测不可用**（Reddit 已封匿名 token）。https://github.com/karanb192/reddit-mcp-buddy |
| Apify Fast Reddit Scraper | 紧急 + 一次性 + 愿付费 | $2/1k 条；黑盒，合规性无法验证。https://apify.com/practicaltools/apify-reddit-api |
| Academic Torrents 历史档案 | 需要 GB 级历史数据（2005–2024） | 3.28 TB，top 40k subs；解析工具 https://github.com/Watchful1/PushshiftDumps |

**废弃方案（不要再试）**：Pushshift.io（2023-04 关闭）；旧版 PRAW 免审批教程（2023 前，已过时）；匿名 reddit.com `.json`（已封，403）。

## 为什么不直接抓 reddit.com

- 匿名 `.json` 端点已封（403）；官方 API 自 2025-11 起人工审批基本不批新申请
- reddit.com 对数据中心 IP 大面积返回 "Blocked"，无法自动化
- old.reddit HTML 抓取依赖易碎页面结构，且 Reddit 已计划下线 old.reddit

Arctic Shift 是 Reddit 社区档案（非 reddit.com 域名），免认证、可自动化、可挂服务器，是目前个人研究场景的最优解。

## 参考链接

1. Arctic Shift（数据来源，作者 ArthurHeitmann）：https://github.com/ArthurHeitmann/arctic_shift
2. Arctic Shift Web UI：https://arctic-shift.photon-reddit.com/search
3. reddit-mcp-buddy：https://github.com/karanb192/reddit-mcp-buddy
4. PushshiftDumps 解析工具：https://github.com/Watchful1/PushshiftDumps
5. Academic Torrents 档案：https://academictorrents.com/details/1614740ac8c94505e4ecb9d88be8bed7b6afddd4
