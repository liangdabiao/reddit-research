# Reddit 深度调研 SOP（10 模块框架）

> **本文档是 `reddit-research` skill 的深度调研分支。**
> 什么时候用它：要回答「某品类/某品牌的海外用户真实反馈是什么」，且需要产出可直接用于 SEO 内容 / 产品决策的结构化素材。
> 什么时候不用：只想快速看某个sub 最近的舆论 → 直接走 SKILL.md「痛点提取 SOP」的轻量流程。

---

## 〇、开工前必读：三个会浪费大量时间的坑

### 坑1：「URL 加 .json」本机不可用

原始方法论说「在帖子 URL 末尾加 .json，复制全部数据粘贴给 AI」。**这条路在服务器 / 数据中心 IP 上走不通**：

- 匿名 `.json` 端点已被封（403）
- reddit.com 对数据中心 IP 大面积返回 Blocked
- old.reddit 依赖易碎页面结构，且 Reddit 已计划下线

**替代方案：Arctic Shift（免认证社区档案 API）**——本文档所有数据来源。
Base URL：`https://arctic-shift.photon-reddit.com`

### 坑2：服务端关键词过滤通道已彻底失效（错误形态极具误导性）

**这是本次调研最大的时间黑洞，必须记住。**

| 请求形态 | 实际返回 |
|---|---|
| 全站无 sub 限定：`?title=xxx` / `?selftext=xxx` / `?body=xxx` | **HTTP 400 Bad Request** |
| 带 sub 限定：`?subreddit=X&title=xxx` | **HTTP 422** `Unprocessable Entity` |
| 带 sub 限定（并发稍多时） | **HTTP 422** `{"error":"Timeout. Maybe slow down a bit"}` |
| 无关键词：`?subreddit=X&limit=100&sort=desc` | ✅ 正常 |

**⚠️ 那个 "Timeout. Maybe slow down a bit" 极具欺骗性**——它让人以为是请求太快，于是加退避重试。但对关键词查询而言，**重试永远无效**（实测退避到 6 次仍失败），纯属浪费 **39 分钟**。

**正确处置：看到 400 / 422 且带关键词参数 → 立刻判定走「全量拉取 + 本地过滤」，不要重试。**

开工前先跑这条自检（返回 JSON 而非 error/400/422 → 关键词搜索可用，可走模板 A）：

```bash
curl -s -o /dev/null -w "%{http_code}" "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=BuyItForLife&title=test&limit=1" -H "User-Agent: reddit-research/1.0"
```

### 坑3：品牌名几乎不出现在标题里

实测 `?title=unice` / `?title=luvme` / `?title=nadula` / `?title=alipearl` 全站查询命中 **0 帖**。

**品牌调研必须搜正文（`selftext`）和评论（`/api/comments/search?body=`）**——而这两条通道现在又恰好失效（见坑2）。所以现实答案是：**按 sub 全量拉取 → 本地正则过滤品牌名**。

```python
BRAND_RX = {
    "Unice":   re.compile(r"\buni\s?ce\b|unice", re.I),   # 注意写变体
    "Luvme":   re.compile(r"\bluv\s?me\b", re.I),
    "Nadula":  re.compile(r"\bnadula\b", re.I),
    "AliPEARL": re.compile(r"\bali\s?pearl\b|alipearl", re.I),  # Ali Pearl / Alipearl
}
```

**「零声量」本身也是结论**：AliPEARL 在 63,400 帖样本中提及 0 帖（已用 `ali pearl` / `alip?earl` / `pearl hair` 多轮排查）→ 该品牌在欧美社区根本没建立讨论资产。

---

## 一、数据采集 SOP

### 步骤 1：选sub（先探活跃度）

```bash
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=<SUB>&limit=2&sort=desc" -H "User-Agent: reddit-research/1.0"
```

看 `created_utc` 是否为近期（> 1 年前 = 已停更，样本不足不能用于结论）。
本次假发调研的实测结果：r/Wigs 活跃 ✓、r/curlyhair ✓、r/alopecia ✓（但仅 300 帖）、r/tasmota 90 天只有 6 帖（❌ 停活，不可用）。

### 步骤 2：全量分页拉取（唯一可靠路径）

用 `scripts/fetch_subreddit.py`（纯标准库，无需 jq）：

```bash
py -3 scripts/fetch_subreddit.py <subreddit> <days> <out.json>     # Windows
python3 scripts/fetch_subreddit.py <subreddit> <days> <out.json># macOS/Linux
```

分页规则（已实测验证）：
1. 首页 `?subreddit=X&limit=100&sort=desc`（不带 `before`）
2. 取本页最小 `created_utc`，下一页带 `before=<该值-1>`（`-1` 防死循环）
3. **空响应先重试 2–3 次再判定到头**（偶发瞬时空响应）
4. 全部拉完后按 `id` 去重

**大sub 要有耐心**：r/Hair 半年 = 19,800 帖 / 198 页；r/curlyhair = 10,800 帖 / 108 页。单线程顺序跑，别并发（SKILL.md 已注明）。

### 步骤 3：合并 + 品牌本地过滤

```python
seen, posts = set(), []
for f in glob.glob('data/*.json'):
    if any(k in f for k in ('all_posts', 'brand_hits', 'analysis')): continue
    d = json.load(open(f, encoding='utf-8'))
    if not isinstance(d, list): continue# 防御：偶发畸形响应
    for p in d:
        if not isinstance(p, dict): continue       # 防御：非 dict 元素会让 p["id"] 崩
        if p.get('id') and p['id'] not in seen:
            seen.add(p['id']); posts.append(p)
```

> ⚠️ **实测踩坑**：`fetch_wig_subs.py` 在最后汇总时崩了（`TypeError: string indices must be integers`），
> 原因是某个 sub 的 API 响应里混进了非 dict 元素。**合并时必须加`isinstance(p, dict)` 防御**，
> 否则整批数据在最后一步归零。

### 步骤 4：评论树补刀（**高赞评论往往比帖子本身更锋利**）

选高互动帖（`score` + `num_comments` 排序）抓完整评论树：

```bash
py -3 scripts/comment_tree.py <post_id> [topN]
```

用 `scripts/comment_tree.py`。本次实测价值：

| 帖子 | 正文说了什么 | 高赞评论补出了什么 |
|---|---|---|
| r/Wigs [1u64d64](https://www.reddit.com/r/Wigs/comments/1u64d64/)（Unice AI 图，49分） | 讨论 Unice 用 AI 模特 | 11 分评论**顺手揭出 LuvMe 同样如此**；8 分评论给出"混纺"具体判据（部分头发上不了色） |
| r/Wigs [1wrf3dk](https://www.reddit.com/r/Wigs/comments/1wrf3dk/)（17分） | 问 raw hair 买过没有 | 9 分评论给出**最有含金量的证据**：退过 600+ 美元、全额退款每次 |
| r/Wigs [1sezw00](https://www.reddit.com/r/Wigs/comments/1sezw00/)（8分） | 怀疑被骗 | 评论区补充**空包事件**与**退货地址是民宅**的具体指控 |

**结论：只看帖子正文会漏掉最关键的事实。评论树是必做步骤，不是可选步骤。**

### 步骤 5：⚠️ 剔除 KOC 软文（本品类最隐蔽的偏差源）

r/Wigs 等sub 的 AutoModerator 规则**要求晒单必须贴购买链接** → 品牌方/合作 KOC 直接在帖内发商品链接伪装普通用户。

检测正则：

```python
PROMO = re.compile(
    r"utm_(source|medium|campaign)=[^&\s]*(rdkoc|reddit|seeding|influencer)"
    r"|\?rdkoc|koc|affiliate|shop\.<品牌域名>\.com|<品牌官网域名>/",
    re.I)
```

**实测后果极其重要**：r/Wigs 内 9 帖被剔除，**而它们恰好就是分数最高的正面评价**（Luvme 298分「I've been wearing this wig everyday!」、217 分「Got my first Luvme wig last week!」、Unice 136 分那篇全被软文）。

**不剔除会得出与事实完全相反的结论。**

注意口径要写清楚：`r/Wigs 内软文 9 帖` 和 `较宽正则跨 sub 命中 39 帖` 是两回事，报告里不要混用。

---

## 二、痛点提取 SOP

按 SKILL.md「痛点提取 SOP」执行，并额外遵守以下**两条硬规则**（均为本次实测得出）：

### 规则1：判据必须落到「标题级」

**为什么**：高热度sub 里"I built an X"作品展示帖score 能到 2031，比任何痛点帖都高。

**实测同一份数据（r/esp32，7,055 帖）三版迭代**：

| 版本 | 判据 | 召回数 | 问题 |
|---|---|---:|---|
| v1 | 全文关键词 | 2,819（39%） | 严重污染，排前列全是晒作品 |
| v2 | 加 showcase 黑名单 | 2,044 | 仍漏 542 帖 |
| **v3** | **标题级判据** | **847** | ✅ 纯度可用 |

**晒作品帖的标题几乎不会写成疑问句/抱怨句** → 正文信号只作辅证。

### 规则2：求助型痛点要单独立类

工程/硬件社区里痛点绝大多数不是"吐槽帖"而是**"求助帖"**（`why does...` / `how do I...` / `not working` / `need help`）。只按吐槽词表过滤会漏掉 60% 以上。

实测 r/esp32：抱怨 178 vs 求助 669（约 1:3.7）——**社区主导情绪是困惑，不是愤怒**。

### 情绪必须三分，不能二分

```
pain   吐槽/失败  → 痛点
praise 纯称赞（且无 pain 信号）→ 特性
neutral 中立/求助  → 归痛点
```

假发品类实测：痛点帖 614 / 2,491 = **25%**。若把 neutral 混进 praise，好评率会虚高。

---

## 三、10 模块输出框架

每个模块**不少于 5 条**，内容必须可直接用于页面生产。

| # | 模块 | 要求 |
|---|---|---|
| 01 | **讨论总结** | 核心诉求 1–2 句 + **声量对比表**（各品牌提及帖数，零声量也要列出） |
| 02 | **主要客户痛点** | 每条写清：什么问题 / 什么情况触发 / **情绪强度高中低**，强度高的排前面 |
| 03 | **当前解决方案** | 用户用什么变通，**注明哪些满意、哪些有明显缺陷** |
| 04 | **用户看重的特性** | **直接从评论提取，不推断、不补充没出现过的内容** |
| 05 | **竞品 / 品牌提及** | 竞品缺陷 → **可转化的差异化优势**；**必须并列正反两面观点，不和稀泥** |
| 06 | **用户场景** | 具体到人群 / 目的 / 时机，每条可直接作 Use Case 开场 |
| 07 | **客户语言** | **保留英文原文** + 建议页面位置 + 搜索意图类型 |
| 08 | **搜索意图分类** | 交易 / 商业调查 / 信息 / 导航 → 对应页面 section |
| 09 | **PAA 素材** | 英文问句 + 中文解释 + 答案方向（不超两句），按优先级排 |
| 10 | **图片内容创意** | 主体 / 页面位置 / **能否直接转 AI 生图Prompt** |

### 强制：来源引用格式

```
- "用户原话（英文）" / "中文翻译" — r/sub [帖ID] (score:X, comments:Y, YYYY-MM-DD) — https://www.reddit.com/r/sub/comments/帖ID/
```

评论同样要引用（格式同上，作者用 `u/用户名，N 分`）。

### 强制：数字闭环

报告里**每个统计量都要能用数据复算**。发稿前跑一遍校验：

```python
# 1) 引用帖 ID 全部存在
ids = {p['id'] for p in posts}
bad = [r for r in refs if r not in ids]# 期望 bad == []
# 2) 引用帖的 score/comments 与报告一致
# 3) 两组口径不同的数字必须分别标注（原始量 vs 剔除软文后有效集）
```

**口径混用是本类报告最常见的错误**。同一份报告里「模块一表格 = 原始提及量」和「结论痛点统计 = 有效集」是两组数，必须在文中显式说明。

---

## 四、10 模块完整指令（可直接复制给 AI）

```
你是一名市场研究分析师，同时具备 SEO 内容策略能力。

下面附有一段关于某个产品类目的 Reddit 讨论数据。请分析这段讨论，为希望在该品类创作SEO 内容或开发产品的人输出一份结构化分析报告。

请按以下模块逐一输出，每个模块不少于 5 条，内容具体可落地。

模块一：讨论总结
这个帖子主要在讨论什么问题，用户的核心诉求是什么，一到两句话概括。

模块二：主要客户痛点
用户最常抱怨或反复提到的问题。每条痛点写清楚：是什么问题，在什么情况下触发，用户的情绪强度是高还是低。情绪强度高的排在前面。

模块三：当前解决方案 / 变通方法
用户目前如何尝试解决这些问题。包括他们在用哪些工具、哪些平台、哪些操作方法。注明哪些方案用户反馈满意，哪些有明显缺陷。

模块四：用户看重的产品特性
用户推荐或称赞的功能和设计。直接从评论里提取，不要推断，不要补充没有出现过的内容。

模块五：竞品 / 品牌提及
被讨论到的产品或品牌，以及用户对它们的具体评价。重点标出：用户在抱怨这些竞品的哪些缺陷，这些缺陷可以转化为差异化优势。

模块六：用户场景
用户在什么具体情境下产生这个需求。场景要具体到人群、使用目的、使用时机。每个场景单独一条，可直接用于 Use Case 文案开场。

模块七：客户语言
用户描述问题时使用的原始关键表达，保留英文原文。每条注明：这个表达适合放在页面哪个位置，以及对应的搜索意图类型（交易型 / 商业调查型 / 信息型 / 导航型）。

模块八：搜索意图分类
把评论里出现的问题和需求，按搜索意图分成四类：
· 交易型：用户想直接用工具，对应 Hero + CTA
· 商业调查型：用户在比较哪个更好，对应 Why Choose + 竞品对比
· 信息型：用户想学怎么做，对应 FAQ + How-To
· 导航型：用户在找某个具体品牌或产品，对应 Blog 比较页
每类列出对应的用户原始表达，并注明建议放在页面哪个 section。

模块九：People Also Ask 素材
评论区里被反复追问但没有人完整回答的问题。每条写成英文标准问句格式，加中文解释，并附上建议的答案方向，不超过两句。优先级最高的排在前面。

模块十：图片内容创意
从用户描述的使用场景中，提取最容易可视化的内容方向。每条写清楚：画面主体是什么、适合用作页面哪个位置的配图、是否可以直接转化为 AI 生图 Prompt。

请确保输出清晰、结构化，每个模块的内容直接可用于 SEO 页面生产，不需要二次加工。

Reddit 讨论数据：
（粘贴 JSON 数据到这里）
```

> **注意**：原始版本这段指令前写的是「URL 加 .json 拿数据」。实际执行时数据必须由
> ArcticShift 采集（见第一节），**且必须先剔除 KOC 软文再喂进来**——否则 AI 会基于
> 品牌方自导自演的好评写出错误结论。

---

## 五、报告骨架（直接照抄）

```markdown
# <品类/品牌> Reddit 用户调研报告

**方法论**：本 skill 的 10 模块框架
**数据源**：Arctic Shift（免认证 API），滞后约 36 小时
**样本**：<N> 帖 / <M> 个 sub（列出各 sub 帖数）
**时间窗**：<起> .. <止>
**评论补充**：对 <K> 个高互动帖抓评论树，去重后 <C> 条评论

> **数据可信度前置声明**
> <软文剔除情况、口径说明、为什么这个声明必须放在最前面>

# 模块一：讨论总结
# 模块二：主要客户痛点（按情绪强度排序）
...
# 模块十：图片内容创意
# 结论：<品牌/品类> 诊断
# 数据来源清单（全部引用，格式见上）
# 附：方法论执行说明（数据链路 + 与原始方法的偏离 + 本次新增的坑）
```

---

## 六、常见错误清单（自查用）

| ❌ 错误 | ✅ 正确做法 |
|---|---|
| 用 `?title=品牌词` 搜品牌 | 品牌名多在正文/评论；且关键词通道已失效 → 全量拉取本地过滤 |
| 看到 422 "slow down" 就退避重试 | 关键词查询重试永远无效 → 直接走全量拉取 |
| 按热度排序取 top 帖 | 先剔除作品展示帖 / 软文帖，否则全是晒单 |
| 只看帖子正文就下结论 | 必抓评论树，最关键的事实常只在高赞评论里 |
| 好评和差评混在一个池子里 | pain / praise / neutral 三分，praise 需排除 pain 信号 |
| 报告里数字无法复算 | 发稿前跑 ID 校验 + score/comments 核对 |
| 原始提及量与有效集数字混用 | 两组数分别标注口径 |
| 只写品牌好话 / 只写坏话 | 竞品评价必须并列正反两面，低分反方观点也要引用 |
| 拿品牌方或联盟站的内容当调研结论 | 品牌官网/竞品软文站是利益相关方，只能当背景，不能当结论 |

---

## 七、合规边界

- **只读**：本方法论不含任何发帖/评论/点赞/私信自动化——那是封号 + ToS 红线。
- **数据性质**：Arctic Shift 是社区档案，非 Reddit 官方授权数据源，仅适合个人/一次性研究。
- **禁止**：做成对外产品功能；用于 AI 模型训练（Reddit 2024+ ToS 明令禁止）；转售数据。
- **引用礼仪**：保留原帖链接与作者名，摘录控制在合理引用范围内。
- **利益相关方内容**：品牌自营站、联盟营销站、竞品软文站的内容**只能当背景参考，不能作为结论来源**。

---

## 附：相关文件

| 文件 | 用途 |
|---|---|
| `SKILL.md` | 主方法论（端点、分页、痛点提取、合规） |
| `scripts/fetch_subreddit.py` | 分页全量拉取（纯标准库，替代依赖 jq 的 shell 版） |
| `scripts/comment_tree.py` | 评论树抓取 + 高赞评论提取 |
| `scripts/analyze_title_level.py` | 标题级痛点分析（剔除展示帖的参考实现） |
| `assets/themes_esp32.json` | 主题表模板（按品类改写正则） |
| `references/api_endpoints.md` | 端点参数、错误码、备路径 |
