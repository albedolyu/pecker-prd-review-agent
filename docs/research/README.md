# docs/research — 研究笔记归档

本目录保存**已落地到代码**的研究性笔记。用于追溯设计决策的起源，不是运行时依赖。

## 当前文档

### Claude Code v2.1.107 源码逆向系列（3 轮）

从 `cli.js`（17466 行 minified bundle）提取 harness engineering 模式，用来加固啄木鸟架构。

| 文档 | 覆盖模式 | 对应入库 commit |
|---|---|---|
| `claude-code-harness-patterns.md` | Round 1：重试链 / gate_log / cost 归因 / maxTurns / wiki 验证 / prompt hash / 维度 schema / Permission Gate（8 个基础模式） | `84ec1b9` Phase G CC-patterns |
| `claude-code-advanced-patterns.md` | Round 2：AutoCompact / circuit breaker / tool truncation / telemetry / token tracking（4 个高级模式） | `bbfcfd3` CC advanced patterns |
| `claude-code-deep-patterns.md` | Round 3：cache monitor / event sourcing / effort-aware / deferred tool loading（4 个深度模式） | `b1e1ce0` CC deep patterns |

## 为什么归到这里而不是删掉

- **追溯设计决策**：代码里只有"怎么做"，这里保留"为什么这么做 + 参考源"
- **复利资产**：Claude Code 后续版本演化时，对照这份笔记快速判断哪些模式需要同步升级
- **避免根目录 noise**：原先 3 份散落在仓库根目录造成观感混乱

## 添加新研究笔记的约定

- 只收**已经落地到主代码**的研究产物。未落地的放 `.pecker_drafts/`
- 文件头写明：源码版本 / 日期 / 对应落地 commit
- 入库时顺带在本 README 的表格追一行
