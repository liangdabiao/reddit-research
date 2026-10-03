# reddit-research

免认证、可自动化的 **Reddit 调研方法论**——给 AI agent 直接读的版本。

不用申请 Reddit API、不用登录态、不用代理直连 reddit.com。主路径走 [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) 社区档案 API，实测可挂服务器自动化跑。适合市场调研、竞品分析、用户痛点挖掘、SEO 内容生产。

> 最近实测验证：2026-10-03（含各端点可用性快照）。

## 给 AI 用（推荐入口）

把下面这段话直接发给你的 AI（Claude Code / Codex / Cursor / WorkBuddy 等均可）：

```
帮我调研 Reddit 上「<你的主题，例如：Oura Ring 用户都在抱怨什么>」。
方法论先读这个文档并严格照做（含分页/重试/引用格式）：
https://raw.githubusercontent.com/Quriov/reddit-research/main/SKILL.md
参考脚本在同仓库 scripts/ 目录。最终报告每条结论都要附 Reddit 原帖链接。
```

**做品类 / 品牌 / 竞品调研**（要产出可用于 SEO 与产品决策的结构化报告）时，改用深度流程——
在上一段话后面追加：

```
这是深度调研任务。请先完整读取下面这份方法论文档，再开始采集数据：
https://raw.githubusercontent.com/Quriov/reddit-research/main/references/deep_research_10_modules.md

按其中的 10 模块框架执行（讨论总结 / 痛点 / 现有方案 / 看重特性 / 竞品提及 /
用户场景 / 客户语言 / 搜索意图 / PAA / 图片创意），每个模块不少于 5 条。
```

> ⚠️ 采集数据前务必先读它——文档里的采集顺序、软文剔除、数字闭环要求，
> 直接决定报告结论是否成立。跳过这一步容易得出与事实相反的结论。

也可以把本仓库整个目录放进 `~/.claude/skills/reddit-research/` 或
`~/.workbuddy/skills/reddit-research/` 当作 skill 使用（SKILL.md 自带 frontmatter）。

## 给人用（30 秒上手）

```bash
# 1. 列出某 subreddit 最新 100 帖（免认证，直接跑）
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=ouraring&limit=100&sort=desc" -H "User-Agent: reddit-research/1.0"

# 2. 全量翻页拉取近 N 天（含重试/去重/字段裁剪，纯标准库，无需 jq）
python3 scripts/fetch_subreddit.py ouraring 60 posts.json

# 3. 标题级痛点分析（自动规避作品展示帖霸榜）+ 主题归类 + 热度排序
python3 scripts/analyze_title_level.py <数据目录> <主题表.json> -o report.md
```

## 仓库结构

| 路径 | 用途 |
|------|------|
| [SKILL.md](SKILL.md) | 主方法论：工作流决策、4 个必知坑、痛点提取 SOP、输出格式、合规边界 |
| [references/deep_research_10_modules.md](references/deep_research_10_modules.md) | **深度调研流程**：10 模块输出框架 + 软文剔除 + 数字闭环。做品类/品牌/竞品调研走这份 |
| [references/api_endpoints.md](references/api_endpoints.md) | 端点速查、limit 范围、400/422 错误码对照、备路径、历史档案 |
| [scripts/fetch_subreddit.py](scripts/fetch_subreddit.py) | 分页全量拉取（纯标准库，无需 jq） |
| [scripts/comment_tree.py](scripts/comment_tree.py) | 评论树抓取 + 高赞评论提取 |
| [scripts/analyze_title_level.py](scripts/analyze_title_level.py) | 标题级痛点分析（自动规避作品展示帖霸榜） |
| [assets/themes_esp32.json](assets/themes_esp32.json) | 主题表模板，按调研品类改写正则 |

## 边界与合规

- 数据滞后约 **36 小时**，不适合实时监控；**只读**，不含任何发帖/互动自动化。
- 定位是**个人/一次性研究**：Arctic Shift 为未经 Reddit 官方授权的社区档案，勿做成产品功能、勿用于 AI 训练（Reddit ToS 明令禁止）、勿转售数据。
- 详细边界见 [SKILL.md「合规与边界」](SKILL.md#合规与边界发布前必读)。
