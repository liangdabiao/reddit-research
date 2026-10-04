# reddit-research

免认证、可自动化的 **Reddit 调研方法论**——给 AI agent 直接读的版本。

不用申请 Reddit API、不用登录态、不用代理直连 reddit.com。主路径走 [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) 社区档案 API，实测可挂服务器自动化跑。适合市场调研、竞品分析、用户痛点挖掘、SEO 内容生产。

> 最近实测验证：2026-10-03（含各端点可用性快照）。

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

按其中的 10 模块框架执行（讨论总结 / 痛点 / 现有方案 / 看重特性 / 竞品提及 /
用户场景 / 客户语言 / 搜索意图 / PAA / 图片创意），每个模块不少于 5 条。
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
2. **服务端关键词过滤已失效** —— 全站查询返回 400，带 sub 限定返回 422 且伪装成 `"Timeout. Maybe slow down a bit"`。**看到 400/422 且带关键词参数 → 直接改走全量拉取，不要重试**（曾在此浪费 39 分钟）。
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
| [scripts/comment_tree.py](scripts/comment_tree.py) | 评论树抓取 + 高赞评论提取（可批量多帖） |
| [scripts/analyze_title_level.py](scripts/analyze_title_level.py) | 标题级痛点分析（自动规避作品展示帖霸榜） |
| [assets/themes_esp32.json](assets/themes_esp32.json) | 主题表模板，按调研品类改写正则 |

## 边界与合规

- 数据滞后约 **36 小时**，不适合实时监控；**只读**，不含任何发帖/互动自动化。
- 定位是**个人/一次性研究**：Arctic Shift 为未经 Reddit 官方授权的社区档案，勿做成产品功能、勿用于 AI 训练（Reddit ToS 明令禁止）、勿转售数据。
- 详细边界见 [SKILL.md「合规与边界」](SKILL.md#合规与边界发布前必读)。
