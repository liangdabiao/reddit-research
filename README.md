# reddit-research

免认证、可自动化的 **Reddit 深度调研方法论**——商业机会 / 选品 / 产品反馈决策导向，给 AI agent 直接读的版本。

不用申请 Reddit API、不用登录态、不用代理直连 reddit.com。主路径走 [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) 社区档案 API。**主用途是商业决策**：痛点评分卡、商业信号（采用/流失/付费意愿）、竞品口碑矩阵、进入/不进入结论；SEO 内容素材是可选附录。完整实战案例见 [examples/demo_deepseek_flash41.md](examples/demo_deepseek_flash41.md)。

> 最近实测验证：2026-11-06（全端点复测 + DeepSeek Flash 4.1 全流程实战）。

## 一、核心原理（为什么这样设计）

这六个原理是整个 skill 的骨架，每一条都对应真实踩过的坑。**违背任何一条，报告就会出错**。

### 原理 1：三层分析架构——AI 找全、正则数对、AI 判定

规则（正则/关键词）**不能用来理解内容**——同一痛点换个措辞正则就漏，不同痛点同词就串，"flash" 裸词会撞上 Gemini Flash。所以理解工作全部由 LLM 语义层承担：

```
层1 语义理解（LLM）   开放式主题归纳（无预设聚类）、读原文判定每条引用、归因综合
层2 计数（正则）      只对已定义的主题/信号做计数 → 可复算、零成本、可审计
层3 交叉对照         AI 归纳的主题 ∩ 正则频次 → 差异 = 漏报/误报清单 → 扩表重跑
```

规则层唯一的存在理由是**数字闭环**：报告里每个数字，任何人都能用一条命令重算验证（AI 直接输出的数字不可审计）。分工铁律：**AI 负责找全和判定，正则只负责数数**。关键词命中永远只是"召回"，引用前必须读原文确认语义——关键词是线索不是结论。

### 原理 2：研究问题先行

采集前先用三行字钉死：品类/产品、要回答的决策问题（选品？竞品口碑？）、目标用户。没有它，后续所有筛选（选哪些 sub、主题表放什么词、哪些帖算"相关"、评论树给谁抓）都没有准绳——数据里有什么就写什么，报告必然跑题。

### 原理 3：只读与全量——数据可得性决定一切

- 匿名抓 reddit.com 已死（403 / Blocked / 官方 API 不批），唯一稳定通道是 **Arctic Shift 社区档案**（免认证、可自动化、滞后约 36 小时）
- 服务端关键词过滤不可依赖（全站查询 400 持续拒绝；带 sub 的查询常返回**瞬态** 422 "Timeout"——重试即恢复，不是永久失效，2026-11-06 实测推翻旧结论）
- 所以主路径 = **按 sub 全量拉取 + 本地过滤**：一次拉取同时覆盖标题和正文，所有统计量能从同一数据集复算

### 原理 4：反污染三件套——不剔除偏差源，结论会反转

1. **展示帖剔除**：高热度社区里 "I built an X" 晒作品帖 score 可达 2000+，霸榜任何热度排序。判据落到标题级（晒作品帖标题几乎不写问句/抱怨句）；必看「Top30 高互动帖中展示帖占比」——潮玩实测 86.7%，按热度取 top 会得出"口碑极好、无痛点"的反向结论
2. **软文（KOC）剔除**：电商/美妆类 sub 的 AutoModerator 要求晒单贴购买链接 → 品牌方伪装用户发帖。实测被剔除的恰是分数最高的"好评"，不剔除 = 镜像错误结论。每个品类独立实测，不要跨品类沿用假设
3. **噪音评论剔除**：`[removed]`/机器人评论不能当用户声音引用

### 原理 5：评论树定向补刀——评论经常比帖子更锋利，但必须抓对帖

只看帖子正文会漏掉最关键的事实（原帖控告厂商，26 分高赞评论指出是另一家的责任）。但**评论树只抓痛点/口碑层的帖**，不抓全局热度 top——全局 top 大概率是展示帖，评论区只会是 "Awesome!"，写进痛点报告就是答非所问。

### 原理 6：分层与口径纪律——数字闭环是发稿闸门

- 情绪三分：pain（抱怨/求助）/ praise（纯称赞）/ neutral（归痛点），混池会让好评率虚高
- 求助帖单独立类：工程/技术社区痛点大多数是求助（why does / how do I / not working），不是吐槽；只按吐槽词表会漏 60% 以上（实测抱怨:求助 ≈ 1:3.7）
- 双口径标注：原始提及量 vs 剔除软文后有效集，两组数不得混用
- **发稿前必须跑 `verify_citations.py`**：报告里每个引用帖 ID/score/comments/日期逐条回查数据集，exit 1 = 有编造或抄错的引用，清零才能发

## 二、核心流程（六步流水线）

```
① 研究问题界定        三行字：品类/决策问题/目标用户（没有准绳 = 必然跑题）
   ↓
② 探活与选sub         probe_subreddit.py：活跃度 + 近N天精确帖量 + 相关性抽检
   ↓                  窗口估算页数（>50页先确认或砍窗口；默认 90 天）
③ 全量拉取            fetch_subreddit.py：增量落盘 + 断点续传（中断重跑同一命令即可）
   ↓                  多 sub 并行、单 sub 串行
④ 帖级分析            analyze_title_level.py：标题级分类 + 数据体检（数据构成 /
   ↓                  --scope 相关性）+ 主题频次（趋势列）+ 痛点评分卡 + 帖级商业信号
   ↓                  ── AI 开放式主题归纳与正则对照，扩表重跑（AI找全、正则数对）
⑤ 评论树定向补刀      comment_tree.py -j：只抓痛点/口碑层 top（脚本直接给命令）
   ↓                  → analyze_comments.py：评论级主题频次 + 商业信号 + 代表引语
⑥ 事实底稿 → 报告     写作 AI 只面对核实过的底稿（B1-B7 模块与数据层绑定）
   ↓
⑦ 数字闭环校验        verify_citations.py：exit 0 才发稿
```

各步的命令、参数、退出码见 [SKILL.md](SKILL.md) 与 [references/](references/)。

## 三、产出框架：商业决策 7 模块（B1–B7）

| # | 模块 | 回答什么问题 |
|---|---|---|
| B1 | 需求概览与人群 | 谁在讨论、什么场景、声量结构 |
| B2 | 痛点清单（评分卡排序） | 痛点是什么、多严重（普遍度×严重度×趋势）、在不在上升 |
| B3 | 现有方案与不满 | 用户怎么变通、哪里是竞争空隙 |
| B4 | 购买决策因素 | 怎么选、为何买/退、价格原话 |
| B5 | 竞品口碑矩阵 | 各品牌正反两面、可转化差异化 |
| B6 | 商业信号 | 采用/流失/付费意愿的规模证据 |
| B7 | 机会与风险结论 | 机会 Top3 / 雷区 Top3 / 需补调研清单 |

SEO 附录包（S1 客户语言 / S2 搜索意图 / S3 PAA / S4 图片创意）只在要做内容时追加。
完整指令、模块↔数据层绑定规则见 [references/deep_research_10_modules.md](references/deep_research_10_modules.md)。

## 四、快速开始

把下面这段发给你的 AI（Claude Code / Codex / Cursor 等均可）：

```
帮我调研 Reddit 上「<品类/产品> 的用户反馈与商业机会」。
这是深度调研任务。先完整读取 skill 文档再开始采集：
<本仓库路径>/SKILL.md 与 <本仓库路径>/references/deep_research_10_modules.md
研究问题：品类=<...>；决策问题=<...>；目标用户=<...>
按商业决策 7 模块（B1-B7）产出报告，每条结论附原帖链接，发稿前跑
scripts/verify_citations.py 校验。
```

第一次跑深度流程前，建议先通读实战案例 [examples/demo_deepseek_flash41.md](examples/demo_deepseek_flash41.md)——它展示了从研究问题到 B7 结论的完整产出长什么样。

## 五、仓库结构

| 路径 | 用途 |
|------|------|
| [SKILL.md](SKILL.md) | 主方法论：工作流决策、五个必知坑、痛点提取 SOP 9 条、输出格式、合规边界 |
| [references/deep_research_10_modules.md](references/deep_research_10_modules.md) | **深度调研 SOP**：商业决策 7 模块框架 + 采集/主题表/评分卡/信号 + AI 归纳对照 + 数字闭环 |
| [references/api_endpoints.md](references/api_endpoints.md) | 端点速查、400/422 错误形态判读（2026-11-06 复测）、备路径 |
| [scripts/probe_subreddit.py](scripts/probe_subreddit.py) | sub 活跃度探测：最新帖时间 + 近 N 天精确帖量（页数预估） |
| [scripts/fetch_subreddit.py](scripts/fetch_subreddit.py) | 分页全量拉取：增量落盘 + 断点续传（纯标准库） |
| [scripts/analyze_title_level.py](scripts/analyze_title_level.py) | 帖级分析：标题级分类 + 展示帖剔除 + 数据体检 + 趋势 + 痛点评分卡 + 商业信号 |
| [scripts/analyze_comments.py](scripts/analyze_comments.py) | 评论级分析：评论主题频次 + 商业信号 + 代表引语 |
| [scripts/comment_tree.py](scripts/comment_tree.py) | 评论树抓取（`-j` 另存全部评论；自动剔除 [removed]/机器人评论） |
| [scripts/verify_citations.py](scripts/verify_citations.py) | 数字闭环校验器：发稿前必须跑 |
| [assets/](assets/) | 主题表与商业信号表模板：`themes_esp32.json`（硬件域）/ `themes_llm.json`（AI 模型域，实测校准）/ `signals.json`（实物电商域）/ `signals_llm.json`（AI 域）——短词必须加 `\b` 词边界 |
| [examples/demo_deepseek_flash41.md](examples/demo_deepseek_flash41.md) · [.html](examples/demo_deepseek_flash41.html) | **完整实战案例**：DeepSeek Flash 4.1 反馈调研（950 帖有效样本，18 条引用通过数字闭环；HTML 版可直接分享） |

## 六、边界与合规

- 数据滞后约 **36 小时**，不适合实时监控；**只读**，不含任何发帖/互动自动化
- 定位是**个人/一次性研究**：Arctic Shift 为未经 Reddit 官方授权的社区档案，勿做成产品功能、勿用于 AI 训练（Reddit ToS 明令禁止）、勿转售数据
- **样本代表性边界**：Reddit 发声的是极端体验者与高活跃少数，不能当市场全貌；报告必须带代表性声明
- 详细边界见 [SKILL.md「合规与边界」](SKILL.md#合规与边界发布前必读)

## 七、成本与精度取舍（实战经验）

实测教训：调研类任务的价值在**结论方向正确 + 证据支撑**，不在数字精确到最后一位。

- 正则/规则调参**最多一轮**；继续不准就改用语义方法（LLM 直读），不要反复调规则
- 采样和截断优先于全量：按价值排序读 top N，不做全量通读
- 长任务并行 + 后台跑，主线程不空等
- 每一步交付前问：边际精度提升值不值得边际成本？默认不值得

## 特别致谢

https://linux.do 社区
https://github.com/Quriov/reddit-research 原作的启发
