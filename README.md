# reddit-research

免认证、可自动化的 **Reddit 调研方法论**——给 AI agent 直接读的版本。

不用申请 Reddit API、不用登录态、不用代理直连 reddit.com。主路径走 [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) 社区档案 API，实测可挂服务器自动化跑。适合市场调研、竞品分析、用户痛点挖掘。

> 最近实测验证：2026-07-05（含各端点可用性快照）。

## 给 AI 用（推荐入口）

把下面这段话直接发给你的 AI（Claude Code / Codex / Cursor 等均可）：

```
帮我调研 Reddit 上「<你的主题，例如：Oura Ring 用户都在抱怨什么>」。
方法论先读这个文档并严格照做（含分页/重试/引用格式）：
https://raw.githubusercontent.com/Quriov/reddit-research/main/SKILL.md
参考脚本在同仓库 examples/ 目录。最终报告每条结论都要附 Reddit 原帖链接。
```

Claude Code 用户也可以把本仓库整个目录放进 `~/.claude/skills/reddit-research/` 当作 skill 使用（SKILL.md 自带 frontmatter）。

## 给人用（30 秒上手）

```bash
# 1. 列出某 subreddit 最新 100 帖（免认证，直接跑）
curl -s "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=ouraring&limit=100&sort=desc" -H "User-Agent: reddit-research/1.0"

# 2. 全量翻页拉取近 N 页（含重试/去重/字段裁剪）
./examples/fetch_subreddit.sh ouraring 60 posts.json

# 3. 本地关键词过滤 + 主题归类 + 热度排序，输出带原帖链接的 markdown
py -3 examples/filter_and_rank.py posts.json -o report.md    # Windows
python3 examples/filter_and_rank.py posts.json -o report.md  # macOS/Linux
```

## 仓库结构

| 文件 | 用途 |
|------|------|
| [SKILL.md](SKILL.md) | 方法论主文档：端点速查、分页/重试 SOP、评论树、备路径、痛点提取 SOP、引用格式、合规边界 |
| [examples/fetch_subreddit.sh](examples/fetch_subreddit.sh) | 分页全量拉取脚本（curl + jq） |
| [examples/filter_and_rank.py](examples/filter_and_rank.py) | 本地吐槽过滤 + 主题归类 + 热度排序（纯标准库） |

## 边界与合规

- 数据滞后约 **36 小时**，不适合实时监控；**只读**，不含任何发帖/互动自动化。
- 定位是**个人/一次性研究**：Arctic Shift 为未经 Reddit 官方授权的社区档案，勿做成产品功能、勿用于 AI 训练（Reddit ToS 明令禁止）、勿转售数据。
- 详细边界见 [SKILL.md 第五节](SKILL.md#五合规与边界发布前必读)。
