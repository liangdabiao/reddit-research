---
name: reddit-research
description: Reddit 用户调研与痛点挖掘：从 subreddit 抓取真实用户讨论，输出带原帖链接的痛点分析、口碑判断与竞品对比。当用户说"调研 reddit"、"看看 r/xxx 在聊什么"、"reddit 用户怎么看 xxx"、"某品牌/品类在 reddit 的口碑"、"reddit 高赞帖"，或做市场调研、选品、竞品分析、SEO 内容生产需要 Reddit 真实用户声音时使用。只读采集，不含发帖/评论自动化。
agent_created: true
---

# Reddit 调研

## Overview

通过 Arctic Shift 档案 API（免认证）抓取 subreddit 帖子与评论树，做痛点提取、口碑判断与竞品对比。所有结论必须附 Reddit 原帖链接。

**核心原则：读 Reddit 数据走 Arctic Shift，不要直连 reddit.com 抓取。**

## 工作流决策

| 需求 | 走哪条 | 产出 |
|---|---|---|
| "r/xxx 最近在聊什么"、"用户主要抱怨什么" | **轻量流程**（本文"痛点提取 SOP"） | 痛点清单 + 计数 |
| 品类 / 品牌 / 竞品 / 选品 / 口碑 / SEO / 内容生产 | **深度流程**：先完整读 [`references/deep_research_10_modules.md`](references/deep_research_10_modules.md) | 10 模块结构化报告 |

命中第二行任一关键词时，**先加载深度文档再开始采集**，不要仅凭本文档就拉数据。

深度流程 = 本文采集手段 + 深度文档中的 10 模块输出框架、KOC 软文剔除、数字闭环校验。轻量流程的 8 条 SOP 规则在深度流程中同样强制适用。

## 标准工作流

1. **确认范围** —— 确定目标 subreddit 与时间窗，先用小 `limit` 探测活跃度与数据新鲜度。
2. **全量拉取** —— 按时间窗分页拉下帖子，落盘 JSON。执行 `scripts/fetch_subreddit.py`；端点参数、分页规则、错误码见 [`references/api_endpoints.md`](references/api_endpoints.md)。
3. **本地过滤** —— 关键词搜索通道不可靠，一律在本地对标题 + 正文做正则过滤。**品牌名几乎只出现在正文和评论里，不在标题**（实测 4 个假发品牌 `?title=` 全站查询命中 0 帖）。
4. **痛点结构化** —— 按下方 SOP 8 条执行，产出主题归类与热度排序。执行 `scripts/analyze_title_level.py`，主题表参考 `assets/themes_esp32.json`。
5. **评论树补刀** —— 对高热帖抓完整评论树，提取高赞评论。执行 `scripts/comment_tree.py`。
6. **数字闭环校验** —— 报告每个统计量必须能从原始数据复算；引用帖 ID 逐个回查 score/comments。
7. **输出** —— 按"输出格式"成文，每条结论附原帖链接。

## ⚠️ 四个必须先知道的坑

违背任何一条都会得出错误结论或浪费大量时间。

**1. 「URL 加 .json」不可用。** 匿名 `.json` 端点已封（403）；官方 API 自 2025-11 起人工审批基本不批。走 Arctic Shift。

**2. 服务端关键词过滤已失效，错误形态极具误导性。** 全站查询返回 **400**；带 sub 限定返回 **422**，且伪装成 `"Timeout. Maybe slow down a bit"`。**看到 400/422 且 URL 带关键词参数 → 直接改走全量拉取，不要重试**（实测退避 6 次仍失败，曾在此浪费 39 分钟）。细节见 `references/api_endpoints.md`。

**3. 高热度社区必须剔除"作品展示帖"，判据要提到标题级。** r/esp32 里 `I built an ESP32 E-ink alarm clock!` 这类晒作品帖 score 高达 2031，比任何痛点帖都高。同一份 7055 帖样本：全文判据召回 2819 帖（39%），排前列全是晒作品；**标题级判据收敛到 847 帖**，纯度才可用。晒作品帖的高 score 是有用信息（说明该 sub 活跃），但只能用于"内容生态"，不能当痛点。

**4. 电商 / 美妆 / 假发类 sub 必须剔除 KOC 软文。** r/Wigs 的 AutoModerator 要求晒单必贴购买链接 → 品牌方与 KOC 直接伪装用户发帖。检测正则：

```
utm_(source|medium|campaign)=[^&\s]*(rdkoc|reddit|seeding)|shop\.<品牌域名>\.com|<品牌官网域名>/
```

**实测被剔除的恰好是分数最高的正面评价**（Luvme 298 分、217 分，Unice 136 分）。不剔除会得出与事实完全相反的结论。检测为 0 帖时不能默认干净——先人工看 top 10 高分帖正文有无品牌官网裸链。

## 痛点提取 SOP

拿到数据后按此流程结构化，勿只堆砌原文。

1. **过滤** —— 用吐槽/痛点信号词过关键词闸。
2. **人工复核误命中** —— 关键词过滤是"召回"不是"判定"。实测：`"finally cracked it"`（=搞定了，正面）会被 `crack` 命中；`"HRV is cracked"`（=数值很强，正面）同理。引用前必须读原文确认语义。
3. **判据落到标题级，剔除展示帖** —— 见坑 3。同时显式排除标题模式 `^(i (built|made|created)|my \w|we (built|did)|showcase|introducing|progress|update|weekend|fun)`。
4. **求助型痛点单独立类** —— 工程/硬件社区的痛点绝大多数是"求助帖"（`why does...` / `how do I...` / `not working` / `need help`）而非吐槽帖。只按吐槽词表过滤会漏掉 60% 以上。实测抱怨:求助 ≈ 1:3.7。
5. **主题归类** —— 按产品域定主题表，一帖可归多主题。
6. **热度排序** —— 每主题内按 `score + num_comments` 排序取 top。注意二者可能倒挂：`score 35 / comments 71` 常比 `score 200 / comments 10` 更说明问题。
7. **评论树补刀** —— 高赞评论往往比帖子本身更锋利，**评论区经常把归因彻底推翻**（原帖控告厂商，26 分高赞评论指出是另一家的责任）。
8. **剔除软文** —— 见坑 4。适用 r/Wigs、r/Hair、r/curlyhair、r/Makeup 等。

## 输出格式

```
## 调研结论
[核心发现，3-5 句]

## 关键痛点（按频次/热度排序）
1. [痛点主题] — [样本内命中 N 帖] — 代表帖：[链接]
...

## 矛盾与不确定
[用户意见分歧处；样本偏差说明]

## 来源清单
[全部引用，按下方格式]
```

### 来源引用格式（强制）

```
- "用户原话（英文）" / "中文翻译" — r/sub [帖ID] (score:X, comments:Y, YYYY-MM-DD) — https://www.reddit.com/r/sub/comments/帖ID/
```

链接由返回数据里的 `permalink` 拼 `https://www.reddit.com` 前缀得到；评论对象同样带 `permalink`。

## 合规与边界（发布前必读）

- **定位**：个人/一次性市场与产品研究。Arctic Shift 与 Academic Torrents 均为未经 Reddit 明确授权的社区档案，此类使用通常被默许，但无任何保证。
- **禁止**：做成对外产品功能；用于 AI 模型训练（Reddit 2024+ ToS 明令禁止）；转售数据。
- **只读**：本 skill 不含任何发帖/评论/点赞自动化——那是封号 + ToS 红线。
- **引用礼仪**：公开报告引用时保留原帖链接与作者名，勿整段搬运超出合理引用范围。

## 资源

| 路径 | 用途 | 何时加载 |
|---|---|---|
| `scripts/fetch_subreddit.py` | 分页全量拉取（纯标准库，无需 jq） | 采集阶段直接执行 |
| `scripts/comment_tree.py` | 评论树抓取 + 高赞评论提取 | 补刀阶段直接执行 |
| `scripts/analyze_title_level.py` | 标题级痛点分析（规避展示帖霸榜） | 分析阶段直接执行 |
| `assets/themes_esp32.json` | 主题表模板，按调研品类改写 | 编写主题表时参考 |
| `references/api_endpoints.md` | 端点参数、错误码、备路径、历史档案 | 需要端点细节或排障时 |
| `references/deep_research_10_modules.md` | 10 模块深度调研框架与完整指令 | 命中深度流程关键词时**必须先读** |
