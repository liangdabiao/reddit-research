---
name: reddit-research
description: Reddit 深度调研：通过 Arctic Shift API（免认证、已实测可用）抓取 subreddit 帖子、评论树、做痛点/口碑分析。当用户说"调研 reddit"、"看看 r/xxx"、"reddit 用户怎么看"、"reddit 上 xxx 的反馈/痛点/口碑"、"reddit 高赞帖"，或做市场/产品/竞品/选品调研需要 Reddit 数据源时使用。覆盖：主路径 Arctic Shift（免认证）+ 全量拉取本地过滤 SOP + 分页与重试 + 评论树 + 备路径（OAuth MCP / 付费 / 历史档案）+ 痛点提取 SOP + 来源引用格式。
---

# Reddit 调研方法论（Arctic Shift 主路径）

> 一句话：**读 Reddit 数据 → 用 Arctic Shift（免认证档案 API），不要直连 reddit.com 抓取。**
> 最近实测验证：2026-07-05。文中所有"实测"均指该日期或文中另注日期。

## 〇、为什么不直接抓 reddit.com

- 匿名 `.json` 端点已被封（403）；官方 API 自 2025-11 起人工审批基本不批新申请。
- reddit.com 对数据中心 IP 大面积返回 "Blocked"，脚本只能本机+VPN 手动跑，无法自动化。
- old.reddit HTML 抓取依赖易碎的页面结构，且 Reddit 已计划下线 old.reddit。

Arctic Shift 是 Reddit 社区档案（非 reddit.com 域名），**免认证、能自动化、能挂服务器跑**，是目前个人研究场景的最优解。

## 一、何时用本方法论

- "去 reddit 看看 xxx 的评价/反馈/讨论/痛点"
- "调研 r/xxx"、"reddit 用户怎么看 xxx"
- 市场调研、选品调研、竞品分析需要真实用户声音
- 需要某个帖子的完整评论树

**不在范围内（别误用）**：
- 实时监控（数据滞后约 36 小时）→ 需实时走官方 Reddit API（OAuth）
- 发帖/评论/私信/管号 → 本方法论只读；社群互动请人肉操作，勿自动化（封号 + ToS 风险）

## 二、主路径：Arctic Shift API

**Base URL**：`https://arctic-shift.photon-reddit.com`

- 无需认证，`curl` / WebFetch 直接调用
- 请求时带上 User-Agent（礼貌 + 便于对方排查）：`-H "User-Agent: reddit-research/1.0"`
- 速率：每秒几次没问题；批量抓取建议顺序执行不加并发
- **数据滞后约 36 小时**，不适合实时事件监控

### 端点速查表

| 端点 | 功能 | 关键参数 |
|------|------|---------|
| `/api/posts/search` | 搜/列帖子 | `subreddit`, `limit`(1–100), `sort`(asc/desc), `before`/`after`(epoch 秒), `title`, `selftext`, `author`, `flair` |
| `/api/comments/search` | 搜/列评论 | 同上（正文过滤参数为 `body`） |
| `/api/comments/tree?link_id=t3_<帖ID>` | 某帖完整评论树（含折叠评论） | `link_id` 必须带 `t3_` 前缀 |
| `/api/posts/ids` / `/api/comments/ids` | 按 ID 批量取 | 每次最多 500 个 |
| `/api/posts/search/aggregate` | 聚合统计 | `groupBy`: date/author/subreddit |
| `/api/time_series` | 关键词讨论量随时间趋势 | — |

**limit 实测（2026-07）**：有效范围 **1–100**；传 `auto` 也只返回 100，传 >100 直接报错 `'limit' must be between 1 and 100`。（旧资料说 auto 能返回 100–1000，已过时。）

### ⚠️ 端点可用性快照（2026-07-05 实测）

| 能力 | 状态 |
|------|------|
| 纯列表拉取（`subreddit` + `limit` + `sort` + `before`） | ✅ 可用 |
| 评论树 `comments/tree` | ✅ 可用 |
| **服务端关键词过滤**（posts 的 `title`/`selftext`、comments 的 `body`） | ❌ 返回 `{"error":"Under maintenance"}` |

**用前自检一条命令**（若返回帖子 JSON 而非 error，说明关键词搜索已恢复，可走模板 A；否则走模板 B）：

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=BuyItForLife&title=test&limit=1" -H "User-Agent: reddit-research/1.0"
```

### 模板 A：服务端关键词搜索（可用时最省事）

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=ouraring&title=subscription&limit=100" -H "User-Agent: reddit-research/1.0"
```

多个 subreddit / 多个关键词就发多条请求，合并后按 `id` 去重。

### 模板 B：全量拉取 + 本地过滤（当前推荐主路径）

关键词搜索维护中也不影响调研——**按时间窗把 subreddit 帖子全量翻页拉下来，在本地做关键词过滤**。一个 20 万订阅的活跃 sub 约 60–80 帖/天，拉 3 个月也就 5000–6000 条，几分钟搞定。

分页规则（实测验证）：
1. 首页：`?subreddit=X&limit=100&sort=desc`（不带 `before`）
2. 取本页最小 `created_utc`，下一页带 `before=<该值-1>`（`-1` 防死循环；极小概率漏掉同一秒内被截断的帖子，可接受）
3. **空响应先重试 2–3 次再判定到头**——实测偶发瞬时空响应，重试即恢复
4. 全部拉完后按 `id` 去重

现成脚本：[`examples/fetch_subreddit.sh`](examples/fetch_subreddit.sh)（curl+jq，翻页/重试/裁字段/去重一条龙），本地过滤+主题归类见 [`examples/filter_and_rank.py`](examples/filter_and_rank.py)。

字段裁剪建议（原始返回一条帖子 ~4KB，多为无用元数据；只留这些就够分析）：

```
{id, title, score, num_comments, created_utc, permalink, selftext(截断到千字左右), author}
```

### 模板 C：抓某帖完整评论树

从模板 A/B 结果里挑高热帖（`score` 或 `num_comments` 高），用其 `id`（形如 `1uff7ix`）：

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/comments/tree?link_id=t3_1uff7ix" -H "User-Agent: reddit-research/1.0"
```

返回嵌套树。快速提取高赞评论（jq 递归扁平化）：

```bash
... | jq -r '[.. | objects | select(.body? and .score?)] | unique_by(.id) | sort_by(-.score) | .[0:10][] | "[s=\(.score)] \(.author): \(.body | gsub("\n";" ") | .[0:200])\n  https://www.reddit.com\(.permalink)"'
```

## 三、备路径（主路径不满足时）

| 路径 | 何时用 | 要点 |
|------|--------|------|
| Arctic Shift Web UI | 人工浏览验证 | https://arctic-shift.photon-reddit.com/search |
| reddit-mcp-buddy + OAuth | 需要 MCP 工具调用风格 / 更高速率 | 需自己申请 Reddit App（client_id/secret）；**匿名模式实测不可用**（Reddit 已封匿名 token）。https://github.com/karanb192/reddit-mcp-buddy |
| Apify Fast Reddit Scraper | 紧急+一次性+愿付费 | $2/1k 条；黑盒，合规性无法验证。https://apify.com/practicaltools/apify-reddit-api |
| Academic Torrents 历史档案 | 需要 GB 级历史数据（2005–2024） | 3.28 TB，top 40k subs；解析工具 https://github.com/Watchful1/PushshiftDumps |

**废弃方案（不要再试）**：Pushshift.io（2023-04 关闭）；旧版 PRAW 免审批教程（2023 前，已过时）；匿名 reddit.com `.json`（已封）。

## 四、痛点提取 SOP

拿到数据后按此流程结构化（勿只堆砌原文）：

1. **过滤**：吐槽/痛点信号词过关键词闸（英文示例：`disappoint|frustrat|regret|waste of money|broke|refund|warranty|scam|inaccurate|...`，完整词表见 `examples/filter_and_rank.py`）。
2. **⚠️ 人工复核误命中**：关键词过滤是"召回"不是"判定"。实测踩过的坑：`"finally cracked it"`（=搞定了，正面）会被 `crack` 命中；`"HRV is cracked"`（=数值很强，正面）同理。引用前必须读原文确认语义。
3. **主题归类**：按产品域定主题表（如：订阅/电池/准确性/耐用性/客服/尺寸/价格/竞品流失），一帖可归多主题。
4. **排序**：每主题内按 `score + num_comments` 排热度，取 top 引用。
5. **评论树补刀**：对 top 帖跑模板 C，高赞评论往往比帖子本身更锋利。

### 输出格式

```
## 调研结论
[核心发现，3-5 句]

## 关键痛点（按频次/热度排序）
1. [痛点主题] — [样本内命中 N 帖] — 代表帖：[链接]
...

## 矛盾与不确定
[用户意见分歧处；样本偏差说明]

## 来源清单
[全部引用，按下面格式]
```

### 来源引用格式（强制）

```
- "用户原话（英文）" / "中文翻译" — r/sub [帖ID] (score:X, comments:Y, YYYY-MM-DD) — https://www.reddit.com/r/sub/comments/帖ID/
```

链接直接用返回数据里的 `permalink` 拼 `https://www.reddit.com` 前缀即可；评论同理（评论对象里也有 `permalink`）。

## 五、合规与边界（发布前必读）

- **定位**：个人/一次性市场与产品研究。Arctic Shift 与 Academic Torrents 均为未经 Reddit 明确授权的社区档案，此类使用通常被默许，但**无任何保证**。
- **禁止**：做成对外产品功能；用于 AI 模型训练（Reddit 2024+ ToS 明令禁止）；转售数据。
- **只读**：本方法论不含任何发帖/评论/点赞自动化——那是封号 + ToS 红线。
- **引用礼仪**：公开报告里引用时保留原帖链接与作者名即可，勿整段搬运超出合理引用范围。

## 六、参考链接

1. Arctic Shift（数据来源，感谢作者 ArthurHeitmann）：https://github.com/ArthurHeitmann/arctic_shift
2. Arctic Shift Web UI：https://arctic-shift.photon-reddit.com/search
3. reddit-mcp-buddy：https://github.com/karanb192/reddit-mcp-buddy
4. PushshiftDumps 解析工具：https://github.com/Watchful1/PushshiftDumps
5. Academic Torrents 档案：https://academictorrents.com/details/1614740ac8c94505e4ecb9d88be8bed7b6afddd4
