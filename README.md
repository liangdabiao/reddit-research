# reddit-research

免认证、可自动化的 **Reddit 调研方法论**——给 AI agent 直接读的版本。

不用申请 Reddit API、不用登录态、不用代理直连 reddit.com。主路径走 [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) 社区档案 API，实测可挂服务器自动化跑。适合市场调研、竞品分析、用户痛点挖掘、SEO 内容生产。

> 最近实测验证：**2026-11-06**（全端点复测，修正 2026-10-03 对 422 的误诊，见下）。

## 给 AI 用（推荐入口）

把下面这段话直接发给你的 AI（Claude Code / Codex / Cursor / WorkBuddy 等均可）：

```
帮我调研 Reddit 上「<你的主题，例如：Oura Ring 用户都在抱怨什么>」。
方法论先读这个 skill 的 SKILL.md 并严格照做（含分页/重试/引用格式）：
<本 skill 目录>/SKILL.md
参考脚本在同目录 scripts/ 下。最终报告每条结论都要附 Reddit 原帖链接。
```

**做品类 / 品牌 / 竞品调研**（要产出可用于 SEO 与产品决策的结构化报告）时，改用深度流程——
在上一段话后面追加：

```
这是深度调研任务。请先完整读取下面这份文档，再开始采集数据：
<本 skill 目录>/references/deep_research_10_modules.md

调研主题：品类=<...>；要回答的决策问题=<...>；目标用户=<...>

按其中的 10 模块框架执行（讨论总结 / 痛点 / 现有方案 / 看重特性 / 竞品提及 /
用户场景 / 客户语言 / 搜索意图 / PAA / 图片创意）。分析纪律：
先界定研究问题再采集；数据体检（相关性 <30% 先修数据）通过后才写报告；
评论树只抓痛点/口碑层的帖；每个模块不足 5 条时如实标注，禁止编造凑数。
```

> ⚠️ 采集数据前务必先读它——文档里的采集顺序、软文剔除、数字闭环要求，
> 直接决定报告结论是否成立。跳过这一步容易得出与事实相反的结论。
>
> ⚠️ 分享时若用 URL 代替本地路径，**必须指向你自己的仓库**。不要引用第三方仓库的
> 地址——那里是未修订的旧版方法论，会让 AI 走回已失效的流程。

也可以把本目录整个放进 `~/.workbuddy/skills/reddit-research/`（或 `~/.claude/skills/reddit-research/`）
当作 skill 使用，SKILL.md 自带 frontmatter，命中场景时会自动加载。

## 开工前必读：五个坑

违背任何一条都会得出错误结论或浪费大量时间。完整说明见 SKILL.md。

1. **「URL 加 .json」不可用** —— 匿名 `.json` 已封（403），走 Arctic Shift。
2. **错误形态判读要分两种（2026-11-06 复测修正）** —— 全站关键词查询（无 sub）返回 **400**，持续拒绝，不要重试；**任何**请求返回的 **422 `"Timeout. Maybe slow down a bit"` 都是瞬态过载**，退避重试 3–5 次即恢复（纯列表请求也会 422，同参数第 2 次重试即 200——旧版"422 永久失效"系误诊）。脚本已内置该重试纪律；把 422 当永久失败会导致采集中途放弃、部分数据被当全量写进报告。
3. **时间窗必须先算样本量** —— 开跑前用 `scripts/probe_subreddit.py` 拿精确帖量、预估页数并与用户确认（曾因未估算，单 sub 89 页串行跑 40 分钟无产出）。默认 90 天窗口；多 sub 并行、禁用 `| tail` 吞进度。
4. **高热度社区必须剔除作品展示帖，判据要提到标题级** —— 晒作品帖 score 可达 2031；同一份 7055 帖样本，全文判据召回 2819 帖（污染严重），标题级判据收敛到 847 帖。潮玩实测 Top30 高互动帖中展示帖占 86.7%——按热度取 top 会得出「口碑极好、无痛点」的反向结论。
5. **电商/美妆/假发类 sub 必须剔除 KOC 软文** —— 实测被剔除的恰好是分数最高的正面评价（298 分、217 分、136 分），不剔除会得出相反结论；但潮玩品类软文仅 0.2%，**每个品类都要独立实测**。

## 仓库结构

| 路径 | 用途 |
|------|------|
| [SKILL.md](SKILL.md) | 主方法论：工作流决策、5 个必知坑、痛点提取 SOP、输出格式、合规边界 |
| [references/deep_research_10_modules.md](references/deep_research_10_modules.md) | **深度调研流程**：10 模块输出框架 + 软文剔除 + 数字闭环。做品类/品牌/竞品调研走这份 |
| [references/api_endpoints.md](references/api_endpoints.md) | 端点速查、limit 范围（1–100）、400/422 错误码对照、备路径、历史档案 |
| [scripts/probe_subreddit.py](scripts/probe_subreddit.py) | sub 活跃度探测：最新帖时间 + 近 N 天精确帖量（页数预估） |
| [scripts/fetch_subreddit.py](scripts/fetch_subreddit.py) | 分页全量拉取：增量落盘 + 断点续传，崩溃/中断不丢已抓数据（纯标准库） |
| [scripts/comment_tree.py](scripts/comment_tree.py) | 评论树抓取 + 高赞评论提取（可批量多帖；自动剔除 [removed]/机器人评论） |
| [scripts/analyze_title_level.py](scripts/analyze_title_level.py) | 标题级痛点分析：展示帖剔除 + praise 三分 + Top30 展示帖占比校验 |
| [scripts/verify_citations.py](scripts/verify_citations.py) | 数字闭环校验器：报告引用帖 ID/score/comments/日期逐条回查数据集，发稿前必须跑 |
| [assets/themes_esp32.json](assets/themes_esp32.json) | 主题表模板，按调研品类改写正则（短词必须加 `\b` 词边界） |

## 边界与合规

- 数据滞后约 **36 小时**，不适合实时监控；**只读**，不含任何发帖/互动自动化。
- 定位是**个人/一次性研究**：Arctic Shift 为未经 Reddit 官方授权的社区档案，勿做成产品功能、勿用于 AI 训练（Reddit ToS 明令禁止）、勿转售数据。
- 详细边界见 [SKILL.md「合规与边界」](SKILL.md#合规与边界发布前必读)。


## 特别致谢

https://linux.do 社区

https://github.com/Quriov/reddit-research  原作的启发
