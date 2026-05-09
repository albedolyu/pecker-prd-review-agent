# 啄木鸟 7.5 小时自动开发计划 - 深层优化报告底稿

开始时间: 2026-05-09 01:02 +08:00

## 本轮目标

围绕 PM 试用反馈做深层优化，而不是只换模型或调并发参数:

- 断线/刷新后不要让 PM 重新跑评审。
- 四个 worker 超时要减少无意义重跑，降低中转站 524/timeout 概率。
- 逐条确认页要更适合 PM 判断，少一点后端和模型术语。
- 原文区要尽量定位到被指出的问题位置。
- 保留 LangGraph/legacy 回滚口，避免团队版上线时不可控。

参考经验:

- LangGraph persistence/checkpointing: 把长流程显式拆成可观察节点，失败后能围绕节点恢复。
  https://docs.langchain.com/oss/python/langgraph/persistence
- OpenAI Evals: 把主观质量反馈沉淀成可重复的评测样例，而不是靠单次肉眼判断。
  https://github.com/openai/evals

## 已完成改动

### 1. Phase 2/3 草稿恢复补强

- Phase 2 评审完成后立即保存包含 `review_result` 的草稿。
- 进入逐条确认页前再次保存，避免页面跳转/刷新丢结果。
- Phase 3 决策每 700ms 自动保存，PM 接受/驳回/改写后断线可恢复。
- 生成报告成功后保存 phase 4 草稿和后端报告 Markdown。
- 草稿 payload 增加 `mode`，恢复时保留轻评审/深评审选择。
- 保存 reviewer 时增加兜底: 优先 store reviewer，缺失时使用签名 reviewResult reviewer。

### 2. PM 友好解释层

- 新增 `explainReviewItemForPm`，把每条评审意见转换为:
  - PM 要判断什么
  - 建议怎么处理
  - 是否偏研发实现细节
- 确认页 item 卡片新增「PM 要判断」区域，保留原始问题和建议，但先给 PM 可操作判断。
- 将 PM-facing 的 `ai_coding` 标签从 `AI Coding` 调整为「实现风险」。

### 3. 原文定位增强

- 新增 `findPrdAnchorMatch`:
  - 先匹配 location 原文
  - 再匹配 evidence quote
  - 再识别 `line N` / `第 N 行`
  - 最后按长关键词 token fallback
- 确认页原文区新增「已定位原文 / 未精确定位」状态。
- 找到位置时高亮对应原文；找不到时保留完整 PRD，避免误导 PM。

### 4. 大 PRD 上下文压缩阈值可配置

- `PECKER_PRD_CONTEXT_AUTO_CHARS` 新增为部署可调阈值。
- 团队版 `.env.example` 建议 18KB 以上自动切成「结构索引 + 本维度摘录」。
- 目标是避免四个 worker 对中大型 PRD 重复塞全文，降低网关超时概率。

## 新增/更新测试

- `web/tests/draft-persistence.test.ts`
- `web/tests/pm-friendly.test.ts`
- `web/tests/prd-anchor.test.ts`
- `web/tests/report-contract-store.test.ts`
- `tests/test_drafts_isolation.py`
- `tests/test_prd_context_packet.py`

## 验证结果

- Python 全量: `1379 passed, 6 warnings`
- Web Vitest 全量: `17 files / 106 tests passed`
- TypeScript: `npx tsc --noEmit` 通过
- ESLint: 0 errors，剩余 6 个 `<img>` 性能 warning，均为既有图片组件使用方式
- `git diff --check` 通过

## 当前剩余风险

- 本轮解决的是「Phase 3 刷新/断线恢复」，不是「Phase 2 SSE 断线后服务端继续跑并可续连」。后者需要引入后台 job + result polling，属于下一层架构改造。
- context packet 会减少超时风险，但中转站 524 本质上仍受上游稳定性影响；需要继续用真实 PRD 观测成功率和耗时。
- PM 友好解释层是确定性投影，不会改模型原始输出；如果 worker 输出本身太抽象，还需要继续压 prompt tone 和规则样例。

## 下一步建议

- 增加 `/api/review/jobs/{id}` 后台任务模式，让 Phase 2 断线也能续接。
- 把 PM 驳回原因和改写文本自动汇总到 admin 看板，形成第一批真实校准集。
- 用 3-5 份真实 PRD 做稳定性回归，记录: 成功率、总耗时、失败 worker、是否触发 context packet。
- 如果中转站仍频繁 524，把 worker 默认切到 `gpt54 + context packet`，苍鹰继续保留 `gpt55`。
