# Pecker 6 小时连续优化开发报告草稿

> 本文档为本轮连续开发的滚动记录，最终收口时再补完整验证矩阵和上线建议。记录中不包含任何 API key、密码或 PRD 正文。

## 已完成
- 复盘页与报告维护记录去排障化
  - 问题：复盘页和报告生成器的可选维护信息仍残留“排障原始记录 / 维护人排障信息”，虽然主要给管理员或显式选项使用，但内网试用期容易被 PM 理解为后端故障页。
  - 改动：复盘页改为“处理原始记录 / 复盘和处理追踪”；报告可选维护折叠区改为“维护人处理记录”，默认 PM 下载报告仍不包含该段。
  - 验证：`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/report-markdown-copy.test.ts`，30 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。
- 后台最近处理轨迹去 token 化
  - 问题：管理员“最近处理轨迹”接口虽然不展示 PRD 正文，但允许字段里仍包含 `tokens_in/tokens_out/input_tokens/output_tokens`，普通排查不需要这些底层计数。
  - 改动：`/api/admin/usage` 的最近任务轨迹只保留耗时、方向、状态、意见条数和压缩视图大小；前端类型同步移除 token 字段，降低内网 UI 泄露成本/底层调用细节的可能性。
  - 验证：`python -m pytest tests\test_admin_usage_summary.py -q`，2 passed；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts`，27 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。

- 后台任务复用指纹纳入资料库内容
  - 问题：断线续接和重复点击保护会复用同一份正在运行的任务；如果 PM 刚更新资料库内容但 PRD 名和资料库名没变，旧指纹可能误判为同一轮评审。
  - 改动：后端 `request_fingerprint` 和前端 `reviewJobResumeKey` 都把资料库页面内容纳入哈希；只存哈希，不保存资料库正文到 job 快照。
  - 验证：先新增红灯用例确认会误复用；修复后 `python -m pytest tests\test_review_jobs_route.py -k "reuse" -q`，3 passed；`npm test -- --run tests/review-job-resume.test.ts`，11 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。
- 网关稳定性建议去“失败方向”表述
  - 问题：网关稳定性摘要里还会建议“失败方向改走备用线路”，和前端统一的“方向未完整返回 / 重新评审”口径不一致。
  - 改动：建议语改为“未完整返回的方向可改用稳定线路或恢复模式”，避免 PM 或运维看到后误以为当前 UI 已支持单方向重跑。
  - 验证：`python -m pytest tests\test_gateway_resilience.py -q`，2 passed；`git diff --check` 通过。
- 专业术语 PM 化词库扩展
  - 问题：同事反馈部分评审意见偏专业，已有词库覆盖接口、回调、幂等、异步、降级等，但对容量、稳定性和数据合规类术语解释不足。
  - 改动：新增 P99/QPS/限流/熔断、队列积压、补偿任务、脱敏/审计/白名单/黑名单解释，并允许单条意见最多带 4 条术语翻译。
  - 验证：先新增真实技术意见样例；修复后 `npm test -- --run tests/pm-friendly.test.ts`，9 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。

- Phase2 可恢复后台任务基础能力
  - 新增 `api/review_jobs.py`，支持任务创建、事件记录、结果快照、用户隔离、取消任务。
  - 新增 `api/routes/review_jobs.py`，提供 `POST /api/review/jobs`、`GET /api/review/jobs/{job_id}`、`GET /api/review/jobs/{job_id}/next-event`、`DELETE /api/review/jobs/{job_id}`。
  - job 路径默认复用现有 `/api/review/run` 的完整 SSE 深评流程，避免质量治理分叉。

- 前端断线续接灰度能力
  - `useReviewStream` 新增后台 job 模式，默认使用可恢复任务；`NEXT_PUBLIC_REVIEW_JOB_MODE=0` 可一键回滚到原 SSE 直连。
  - 使用 reviewer/workspace/prd_name/mode/内容 hash 生成 resume key，浏览器刷新或短断线后可回到同一任务。
  - 取消按钮接入后端 cancel，避免前端停止轮询但后台继续消耗模型调用。
  - 如果浏览器保存的旧任务已经过期、失败或后端重启丢失，前端不再静默新建一轮评审；会提示“无法继续接回，需要重新发起”，避免 PM 误以为在恢复却实际重新烧一轮。
  - 评审流异常文案优先展示后端中文 `detail`，避免预算/权限/网关错误在主界面露出 `API 403`、`HTTP 502` 等技术前缀。
  - SSE 事件里的 `Request timed out`、`HTTP 524`、`API 502` 等原始错误也统一转换成 PM 可理解的“评审响应过慢/服务暂时无法处理”提示，原文只留给维护人排障。

- 后台可观测性
  - admin usage 响应新增 `active_jobs`，管理员可以看到当前/最近 job 的状态、材料名、负责人、最后事件。
  - 后台反馈摘要新增读取 `.pecker_drafts` 中的逐条确认草稿，PM 未最终生成报告时的已处理反馈也能进入统计，且不暴露 PRD 正文。

- 逐条确认断线保护
  - Phase 3 进入后会保存完整评审结果，刷新后可从草稿恢复确认状态。
  - PM 的接受、拒绝、进入改写、切换驳回原因等关键动作现在会立即写入草稿，降低“刚点完就断网导致最后几条丢失”的窗口。
  - 原有防抖保存继续保留，用于兜住备注和改写文本输入。

- PM 可理解性
  - 逐条确认页的 PM 解释增加“白话摘要”，先解释这条意见到底在提醒 PM 判断什么，再展示下一步建议。
  - 白话摘要增加常见研发术语翻译层：遇到 SLA、DDL、枚举、幂等、异步、降级、重试、权限等词时，自动补充“PM 要在 PRD 里落实成什么”。
  - 下载报告的字段改为“资料库 / 评审模式 / 评审编号 / 各方向提交 / 可信度”，移除 `Workspace`、`Review ID`、`worker 贡献`、`Opaque Handle` 等后端表达。
  - 报告底部仅保留“维护人排障信息”，不再输出签名字段，减少 PM 报告里的技术噪音。

- 资料库入口回退
  - 上传页在已选择资料库后，补充“也可以新建资料库”的显性入口。
  - 从新建资料库输入态可一键“继续使用这个资料库”，避免 PM 选错后必须刷新页面。

- 逐条确认定位
  - 逐条确认页左侧 PRD 原文新增“定位摘录”，选中右侧意见后直接展示命中的原文上下文。
  - 锚点匹配从精确位置扩展到依据引用、行号和长 token 兜底，减少 PM 在长文里找问题位置的成本。
  - 命中原文后会显示“第 X 行”或“第 X-Y 行”，让 PM 能更快定位到需要改的段落。
  - 左侧 PRD 原文从纯 Markdown 源码展示升级为带行号的阅读视图，标题和列表有基础层级，同时保留命中位置高亮，方便 PM 在逐条确认时直接对照原文修改。

- Worker 部分失败降级
  - 当多个 worker 超时但至少一个方向已产出可用意见时，不再触发整轮断路器失败。
  - 后端会发 `review_degraded` 事件，前端保留可用意见并提示“部分方向未完整返回”，全员失败或没有可用意见时才要求重试。
  - 前端把超时错误单独归类成“评审响应过慢”，主提示不再直接暴露 `Request timed out` / `Connection timed out` 这类英文系统错误。
  - LangGraph 主编排热路径回归通过：默认走图编排，`PECKER_REVIEW_ORCHESTRATOR=legacy` 可回滚，worker 节点失败隔离、resilience 建议和 majority vote 多轮路径均有测试覆盖。

- GPT 路由一致性
  - 评审接口里的苍鹰成本估算兜底模型从旧 Claude 默认改为 `gpt-5.5`，避免全 GPT 团队版里残留旧模型暗默认。
  - 增加回归测试，防止后续在热路径重新引入旧 Claude 模型名。

- PRD 上下文压缩质量保护
  - 维度压缩视图在抓相关章节时，始终保留 PRD 开头/目标/背景/范围摘要。
  - 目标是在减少 worker 重复读取长 PRD 的同时，不丢失业务意图，降低“快了但判断跑偏”的风险。

- PM 友好文案扫尾
  - 旧版预检/报告组件里的 `wiki`、`K in/out` 等后端表达改成“资料库”“输入/输出处理量”等 PM 可理解措辞。
  - 增加回归测试，防止备用页面重新出现“保存到 wiki”“wiki 内容缺失”等表达。
  - 评审运行页的处理记录默认收起，改成“查看处理明细/收起处理明细”，避免 PM 首屏直接看到偏排障的深色日志面板。
  - 顶部阶段条与旧进度条改成“选资料库 / 读取资料 / 分向评审 / 复核”等 PM 工作流语言，去掉 `workspace`、`wiki`、`Stage`、`4 位编辑`等内部表达。
  - 上传页耗时预期改成“轻评审约 5 分钟 / 深评审通常 3-8 分钟，材料较长时会更久”，避免固定 10 分钟承诺和旧版 90-150 秒估计造成试用落差。
  - 报告页折叠区从“完整 markdown”改成“完整报告预览”，避免 PM 在结果页看到格式实现细节。
  - 旧版上传页的“Workspace / 选择一个 workspace / wiki 页数 / workspace-示例”改成“资料库 / 选择一个资料库 / 资料页数 / 中文资料库名示例”，防止备用入口继续露出后端术语。
  - 报告出口按钮从“导出 Markdown / 下载 .md”改成“下载评审报告”，保留文件格式实现但不在主按钮上打扰 PM。
  - 旧版报告页的运行指标与成本归因收进“维护人排障信息”折叠区，PM 默认只看到结论、报告预览和出口动作。
  - 评审报告每条意见新增“PM 处理提示”，把专业问题翻译成 PM 需要判断的边界、验收或取舍。
  - 管理员使用看板里缺失评审人时显示“未署名”，动作文案也从“保存到知识库/模型噪声”改成“存入资料库/判断不准”。
  - 后端全员失败/额度耗尽提示去技术化，PM 不再看到 `Claude CLI` / `worker`，统一提示“评审额度已用完”或“评审方向未完整返回”。
  - 不输入真实 PRD 的演示报告页也从“Markdown 预览”改为“报告预览”，避免 demo 入口和正式入口文案不一致。
  - 评审复盘页继续去掉 `payload(JSON)`、`seq` 等审计实现词，改成“处理原始记录”和“第 X 步”。
  - 旧版运行页同步改掉 `4 Workers`、固定 90-150 秒预估、`JSON 解析失败`、`超时 - 走空兜底` 等 PM 不该直接看到的表达。
  - 旧版运行页的失败方向原始错误改为默认折叠在“给维护人看的错误原文”里，主提示只告诉 PM 哪些评审方向未完整返回。
  - `/v8-preview` 组件预览页默认关闭，只有显式设置 `NEXT_PUBLIC_ENABLE_V8_PREVIEW=1` 后才展示，避免 PM 在内网环境误入开发态组件样例。
  - `评审记录` 补成真实个人历史页：普通 PM 只能看到自己的材料名、资料库、运行状态和关键动作，不展示 PRD 正文；原 `/runs/diff` 内部样例对比保留在 `NEXT_PUBLIC_ENABLE_INTERNAL_RUNS=1` 开关后面。
  - `/system/health` 和 `/system/prompts` 增加前端管理员门禁，直接输入 URL 的普通 PM 会被引导回评审工作台，不再看到维护人样例/规则配置页。
  - 管理员质量页图表/表格的英文标注继续中文化：`threshold/today/test/score/updated` 改成“目标线 / 今天 / 样例 / 得分 / 更新于”。

- PM 补充线索闭环
  - 逐条确认页和报告页的“我还发现一个问题”不再停留在前端 `console` 占位，已接入 `/api/feedback/missing`。
  - 后端将 PM 补充线索写入 `logs/missing_feedback.jsonl`，只保存问题摘要、位置、归类、材料名、资料库和评审人，不保存 PRD 正文或原始材料。
  - 管理员“团队使用情况”看板新增“PM 补充线索”计数和最近线索列表，便于你看到同事觉得漏评的点。
  - 报告页“测试用例交接”摘要去掉 `blocked/partial/ready` 这类内部枚举，改成“暂不适合生成 / 部分可生成 / 可生成测试用例”，并把按钮文案改成“下载测试交接材料”。
  - 上传页的草稿恢复提示补充“断网或刷新后可继续上次评审，不用重新跑评审”，让 PM 在网络中断后更容易找回逐条确认进度。
  - `/api/me` 新增管理员标记，顶栏“团队看板”只对管理员显示，普通 PM 不再看到点进去会无权限的后台入口。
  - 顶栏“质量看板 / 团队看板”统一收敛为管理员入口，普通 PM 只保留评审记录和使用说明，减少试用期干扰。
  - 旧 E2E 的顶栏断言从 `Runs/System/关于` 更新为当前中文导航，避免后续回归测试把 PM 友好改动误判成失败。
  - 清理“console 占位 / 后续接真数据”类漂移注释，让 PM 补充线索与反馈沉淀的代码说明和现状一致。
  - `.env.example` 的管理员白名单示例补齐为 `lvxinhang`，减少内网部署时漏配后台权限的概率。
  - `.env.example` 里后台任务恢复开关的注释与默认值对齐，明确团队试用应保持启用，避免运维按旧注释误关断线续接。

- 后台任务内存治理
  - `ReviewJobStore` 增加 `max_jobs` 与 `ttl_seconds` 清理策略，过旧的终态任务会自动移除。
  - 清理逻辑不会删除正在运行的任务，避免 PM 断线回来时找不到仍在处理的评审。
  - 取消后台任务后，等待任务完成不会再向上抛 `CancelledError`，取消事件也只记录一次，减少重试/取消场景的后台噪声。
  - 后台 job 新增脱敏 `logs/review_jobs.jsonl` 生命周期轨迹，只记录评审人、资料库、材料名、阶段、方向、成功/失败和条数摘要，不写 PRD 正文、原始材料或完整报告内容。
  - 管理员“团队使用情况”看板新增“最近处理轨迹”，读取脱敏 job 轨迹，服务重启后也能看到最近任务卡在了哪个阶段或哪个方向。
  - 最近处理轨迹补充方向耗时和是否启用 PRD 压缩视图，便于区分“中转站慢”“单方向超时”和“长 PRD 上下文过大”。
  - 后台任务如果已收到 `review_failed`，不会再补发 `result` 事件，避免失败后前端误进入确认结果；刷新后优先回放失败事件。

- 安全卫生检查
  - 对 Git 跟踪源码/文档进行敏感串扫描，确认没有把中转站 API key、团队密码或前序 GitLab 密码写入待交付文件。
  - 运行 secret gate 单测，保留对明文密钥/密码样例的检测能力。
  - 清理 `test_api_auth.py` 的 `datetime.utcnow()` 弃用 warning，降低后续 CI 输出噪声。
- 评审耗时预期对齐
  - 新增 `web/lib/review-eta.ts`，根据 PRD 字数、补充材料长度和资料库规模动态给出轻评审/深评审预计耗时。
  - 上传页和运行页不再固定写死“3-8 分钟”，短材料仍提示“通常 3-8 分钟”，长材料自动上调到“约 6-10 分钟”或“约 10-15 分钟”。
  - 运行页“已超预期”的判断同步改为动态阈值，避免长 PRD 在合理等待区间内被提前标红。
  - 提示文案补充“刷新或断网后可继续等待”，和后台 job 续接能力保持一致，降低 PM 误以为卡死后重复重跑的概率。
- 逐条确认按钮文案收敛
  - 逐条确认页把高频操作从“接受 / 拒绝 / 编辑”统一改成“采纳 / 驳回 / 改写”，更贴近 PM 处理评审意见的语境。
  - 状态标签、快捷键提示和确认成功 toast 同步改文案，但后端 `accept/reject/edit` 枚举保持不变，不影响现有数据结构和反馈权重计算。
- 运行质量检查文案纠偏
  - 健康检查页原先提示“重跑异常方向”，但当前实现实际会重新发起整次评审，已改为“重新评审”。
  - 额度相关提示从“重跑前”改成“重新评审前”，避免 PM 误以为只会补跑失败方向。
- Worker 总超时降级保护
  - `_single_round_async` 的外层总超时不再把已经完成的批次一起丢掉。
  - 新逻辑按批次维护 deadline：已完成方向保留结果，当前批次未完成和后续未启动方向标记为 timeout，并通过 `on_worker_done` 补发事件给前端。
  - 这样当中转站只拖住后半批方向时，PM 仍能看到已完成方向的可用意见，而不是整轮被误判为全员失败。
- 管理后台草稿进度可见
  - `/api/admin/usage` 新增 `active_drafts`，从 `.pecker_drafts` 读取脱敏草稿进度。
  - 只返回评审人、资料库、材料名、阶段、意见条数和已处理条数，不返回 PRD 正文、报告全文或意见正文。
  - 团队看板新增“进行中的草稿”，admin 可以看到同事是否停在逐条确认或报告阶段，便于处理“断网回来找不到进度”的反馈。

## 当前验证

- `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py -q`：12 passed
- `python -m pytest tests\test_admin_feedback_summary.py tests\test_admin_usage_summary.py -q`：5 passed
- `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly.test.ts`：9 passed
- `npx tsc --noEmit`：passed
- `python -m pytest -q`：1393 passed, 6 warnings
- `npm test`：18 files / 110 tests passed
- `npm run lint`：passed，剩余 6 个既有 `<img>` warning
- `git diff --check`：passed
- `python -m pytest tests\test_worker_failure_classify.py -q`：12 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：11 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：14 passed
- `python -m pytest tests\test_default_model_routes_gpt_only.py -q`：6 passed
- `npm test -- --run tests/workspace-entry.test.ts tests/prd-anchor.test.ts`：7 passed
- `python -m pytest tests\test_worker_batching.py tests\test_worker_failure_classify.py -q`：14 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/review-job-resume.test.ts`：4 passed
- `python -m pytest tests\test_review_jobs_route.py -q`：4 passed
- `python -m pytest tests\test_prd_context_packet.py -q`：5 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：8 passed
- `python -m pytest tests\test_review_job_store.py -q`：9 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/draft-persistence.test.ts`：5 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/extract-worker-errors.test.ts`：8 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/draft-persistence.test.ts tests/extract-worker-errors.test.ts tests/review-job-resume.test.ts`：25 passed
- `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py tests\test_worker_batching.py tests\test_worker_failure_classify.py tests\test_prd_context_packet.py -q`：32 passed
- `git diff --check`：passed
- `python -m pytest tests\test_review_job_store.py -q`：9 passed
- `python -m pytest tests\test_review_jobs_route.py -q`：4 passed
- `npm test -- --run tests/report-markdown-copy.test.ts tests/revision-downloads.test.ts`：3 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：9 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：10 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/report-markdown-copy.test.ts`：1 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：11 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_shrike_gates.py -q`：20 passed
- Git tracked non-test files secret-pattern scan：0 hits
- `npm test -- --run tests/prd-anchor.test.ts`：6 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：9 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：9 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_missing_feedback.py -q`：1 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：15 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：16 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/review-eta.test.ts`：6 passed
- `npm test -- --run tests/review-eta.test.ts tests/pm-friendly-navigation-copy.test.ts`：23 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：18 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：19 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_worker_batching.py -q`：3 passed
- `python -m pytest tests\test_worker_gateway_recovery.py tests\test_gateway_resilience.py tests\test_langgraph_main_orchestration.py tests\test_worker_batching.py -q`：11 passed
- `git diff --check -- review\orchestration.py tests\test_worker_batching.py`：passed
- `python -m pytest tests\test_admin_usage_summary.py -q`：2 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：19 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/prd-anchor.test.ts tests/pm-friendly-navigation-copy.test.ts`：23 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py -q`：14 passed
- `python -m pytest tests\test_admin_usage_summary.py -q`：2 passed
- `python -m pytest tests\test_admin_usage_summary.py tests\test_review_job_store.py -q`：12 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts`：23 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts`：24 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_review_job_store.py tests\test_admin_usage_summary.py -q`：12 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py -q`：15 passed
- `npm test -- --run tests/review-job-resume.test.ts`：7 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_langgraph_main_orchestration.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py -q`：8 passed
- `python -m pytest tests\test_gateway_resilience.py tests\test_langgraph_spike.py -q`：5 passed
- `npm test -- --run tests/pm-friendly.test.ts tests/report-markdown-copy.test.ts`：6 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/review-job-resume.test.ts`：6 passed
- `npx tsc --noEmit`：passed
- `git diff --check`：passed
- `python -m pytest tests\test_shrike_gates.py -q`：20 passed
- Diff-scoped secret pattern scan：0 hits
- `npm run build`：passed，Next.js 16 production build compiled successfully
- `python -m pytest tests\test_model_router_concurrency_gate.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py tests\test_gateway_resilience.py tests\test_langgraph_main_orchestration.py tests\test_review_history.py tests\test_missing_feedback.py tests\test_admin_feedback_summary.py tests\test_admin_usage_summary.py tests\test_review_jobs_route.py tests\test_review_job_store.py -q`：33 passed
- `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts tests/pm-friendly.test.ts tests/workspace-entry.test.ts tests/prd-anchor.test.ts tests/draft-persistence.test.ts tests/report-markdown-copy.test.ts tests/extract-worker-errors.test.ts`：50 passed
- `npm test -- --run tests/review-job-resume.test.ts`：5 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_review_history.py tests\test_review_job_store.py tests\test_review_jobs_route.py tests\test_admin_usage_summary.py tests\test_api_auth.py -q`：20 passed, 4 warnings
- `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts`：23 passed
- `python -m pytest tests\test_api_auth.py -q`：3 passed
- `python -m pytest tests\test_review_history.py tests\test_review_job_store.py tests\test_review_jobs_route.py tests\test_admin_usage_summary.py tests\test_api_auth.py -q`：20 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `git diff --check -- .env.example api\routes\auth.py tests\test_api_auth.py web\components\TopBanner.tsx web\components\phases\Phase0UploadV8.tsx web\components\phases\Phase4ReportV8.tsx web\components\review\MissingReportButton.tsx web\lib\api.ts web\tests\pm-friendly-navigation-copy.test.ts web\tests\e2e\smoke.spec.ts`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts`：18 passed
- `python -m pytest tests\test_api_auth.py tests\test_missing_feedback.py tests\test_admin_feedback_summary.py -q`：7 passed
- `python -m pytest tests\test_model_router_concurrency_gate.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py -q`：5 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_api_auth.py -q`：3 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/login-timeout.test.ts`：1 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `python -m pytest tests\test_review_history.py -q`：2 passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed
- `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：17 passed
- `npx tsc --noEmit`：passed

## 待继续

- 继续检查 job 模式下的事件完整性和 UI 文案。
- 继续补 PM 试用反馈相关的耗时、超时和报告可读性优化。

## 2026-05-09 05:20 继续开发记录

### PM 超时提示语义收口
- 问题：前端仍有两处提示写着“重试失败方向”，但当前产品能力实际是整单重新评审，容易让 PM 误解为可以只补跑单个方向。
- 改动：`web/lib/v8-run-helpers.ts` 和 `web/lib/useReviewStream.ts` 的超时提示改为“可以先重新评审”，保留“连续出现时联系维护人切换稳定线路”的排障建议。
- 防回归：`web/tests/extract-worker-errors.test.ts`、`web/tests/review-job-resume.test.ts` 增加断言，禁止 PM 主提示继续出现“失败方向”。
- 验证：`npm test -- --run tests/extract-worker-errors.test.ts tests/review-job-resume.test.ts`，15 passed；`rg -n "失败方向|异常方向|重跑异常方向|重试失败方向" web` 仅剩测试断言，无生产代码命中；`git diff --check` 通过。

### 下载报告决策口径统一
- 问题：逐条确认页已经使用“采纳 / 驳回 / 改写”，但下载报告仍写“接受 / 拒绝 / 待决”，同一条评审链路会出现两套 PM 决策语言。
- 改动：`web/lib/generateReport.ts` 的评审概要、单条状态和原因字段统一为“采纳 / 驳回 / 待确认 / 驳回原因”。
- 防回归：`web/tests/report-markdown-copy.test.ts` 增加断言，要求报告包含“采纳 / 驳回”，并禁止“接受 1 / 拒绝 1 / 已接受 / 已拒绝”。
- 验证：`npm test -- --run tests/report-markdown-copy.test.ts`，1 passed；`npm test -- --run tests/report-markdown-copy.test.ts tests/pm-friendly-navigation-copy.test.ts tests/extract-worker-errors.test.ts tests/review-job-resume.test.ts`，35 passed；`git diff --check` 通过。

### 专业术语 PM 化
- 问题：PM 同事反馈部分改动“太专业、不好理解”。现有解释已覆盖部分技术词，但对“接口、并发、回调、缓存”等高频实现词没有自动翻译。
- 改动：`web/lib/pm-friendly.ts` 扩展术语解释表，在逐条确认卡片的 PM 处理提示里，把这些词解释成“谁调用谁、传什么、返回什么”“多人或多个请求同时发生”等可决策语言。
- 防回归：`web/tests/pm-friendly.test.ts` 增加真实技术意见样例，要求解释里出现 PM 化翻译，并禁止出现 `debug` 等排障词。
- 验证：`npm test -- --run tests/pm-friendly.test.ts`，6 passed；`npm test -- --run tests/pm-friendly.test.ts tests/report-markdown-copy.test.ts tests/pm-friendly-navigation-copy.test.ts`，26 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。

### 重新评审按钮语义统一
- 问题：旧版运行页和单个方向卡片仍有“建议重试 / 重跑”字样，但点击动作实际会重新跑整单评审，不是只重跑单个方向。
- 改动：`web/components/phases/Phase2Running.tsx`、`web/components/run/AgentStatusCard.tsx` 统一为“建议重新评审 / 重新评审”。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 禁止 legacy running 页出现“建议重试”，并禁止卡片按钮继续显示“重跑”。
- 验证：`npm test -- --run tests/pm-friendly-navigation-copy.test.ts`，19 passed；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/pm-friendly.test.ts tests/report-markdown-copy.test.ts tests/extract-worker-errors.test.ts tests/review-job-resume.test.ts`，41 passed；`npx tsc --noEmit` 通过；`git diff --check` 通过。

### 后端 SSE 事件标签 PM 化
- 问题：实际 E2E 产物里仍能看到 `worker 1/4 完成`、`wiki 扫描完成` 这类底层 label。前端会二次转译，但 job 复放、排障面板、历史事件仍可能直接使用底层 label。
- 改动：`api/stream.py` 将 `wiki_scanned`、`worker_done`、漏斗阶段、依据校验等 milestone label 改成“资料库读取完成 / 评审方向完成 / 初步意见已汇总 / 依据校验完成”等 PM 友好表达；`emit_worker_done` 动态 label 改为“评审方向 X/4 完成”。
- 防回归：`tests/test_stream_disconnect.py` 增加 `test_stream_labels_are_pm_facing`，禁止 `wiki/worker` 出现在 stream label 中。
- 验证：`python -m pytest tests\test_stream_disconnect.py -q`，7 passed；`python -m pytest tests\test_stream_disconnect.py tests\test_review_jobs_route.py tests\test_review_job_store.py -q`，22 passed；`git diff --check` 通过。
 
### 网关 524 自动降级兜底
- 问题：线上同事反馈的失败里出现过 524/网关超时。此前如果异常文本是 `Cloudflare 524: a timeout occurred` 可以被识别，但如果中转站只抛 `HTTP 524`，主路由会直接失败，不会进入备用路线。
- 改动：`model_router.py` 将 Cloudflare 520-524 统一识别为临时网关故障，允许 `fallback_route` 自动接管；这不会改变正常成功路径，只影响网关波动时的兜底。
- 防回归：`tests/test_model_router.py` 增加 `test_route_call_uses_fallback_route_on_cloudflare_524`，模拟主路由只返回 `HTTP 524`，要求自动切到 `fallback.deepseek_v4_pro`。
- 验证：先运行红灯测试确认失败；修复后 `python -m pytest tests\test_model_router.py -k cloudflare_524 -q`：1 passed；`python -m pytest tests\test_model_router.py tests\test_default_model_routes_gpt_only.py tests\test_model_router_concurrency_gate.py -q`：36 passed；`git diff --check -- model_router.py tests\test_model_router.py` 通过。

### V8 运行页重试话术收口
- 问题：V8 运行页健康检查提示仍写“继续确认还是重跑”，异常兜底仍写“未知错误,请重试”。但当前动作实际是整单重新评审，不是技术意义上的单步重试。
- 改动：`web/components/phases/Phase2RunningV8.tsx` 改成“继续逐条确认或重新评审”，错误兜底改成“评审服务暂时不可用,请返回上一步或重新评审”。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加 V8 running page 断言，禁止重新出现“继续确认还是重跑 / 未知错误,请重试”。
- 验证：先运行红灯测试确认失败；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts`：20 passed；`npx tsc --noEmit` 通过；`git diff --check -- web\components\phases\Phase2RunningV8.tsx web\tests\pm-friendly-navigation-copy.test.ts` 通过。

### 后端降级事件不再承诺单方向重试
- 问题：`review_degraded` 事件仍会返回“必要时只重试失败方向 / 建议重试”，但当前产品入口实际是整单重新评审，后台事件一旦被前端或回放页展示，会再次造成误导。
- 改动：`api/routes/review.py` 将部分失败文案改成“已保留可用意见；可以先继续确认,如需完整结果请重新评审”，无可用意见时改成“请重新评审或联系维护人排查”。
- 防回归：`tests/test_worker_failure_classify.py` 更新断言，要求降级事件包含“重新评审”，并禁止“只重试失败方向 / 建议重试”。
- 验证：先运行红灯测试确认失败；修复后 `python -m pytest tests\test_worker_failure_classify.py -q`：12 passed；`python -m pytest tests\test_worker_failure_classify.py tests\test_stream_disconnect.py tests\test_review_jobs_route.py tests\test_worker_batching.py -q`：26 passed；`npm test -- --run tests/review-job-resume.test.ts tests/extract-worker-errors.test.ts tests/pm-friendly-navigation-copy.test.ts`：35 passed；`git diff --check -- api\routes\review.py tests\test_worker_failure_classify.py` 通过。

### 剩余重试/重跑入口扫尾
- 问题：首页卖点、异常横幅和全员失败事件仍残留“重跑 / 重试 / 稍后重试”，PM 容易理解成局部补跑或普通刷新，而不是当前产品支持的整单重新评审。
- 改动：`web/lib/v8-run-helpers.ts`、`web/app/ForestLanding.tsx`、`api/routes/review.py` 统一改成“重新评审 / 联系维护人补充额度 / 联系维护人排查”。
- 防回归：`web/tests/extract-worker-errors.test.ts` 增加 quota/other banner 断言；`web/tests/pm-friendly-navigation-copy.test.ts` 增加首页文案断言；`tests/test_worker_failure_classify.py` 增加全员失败文案断言。
- 验证：先运行红灯测试确认 3 处失败；修复后 `npm test -- --run tests/extract-worker-errors.test.ts tests/pm-friendly-navigation-copy.test.ts`：29 passed；`python -m pytest tests\test_worker_failure_classify.py -q`：12 passed；`git diff --check -- web\lib\v8-run-helpers.ts web\app\ForestLanding.tsx api\routes\review.py web\tests\extract-worker-errors.test.ts web\tests\pm-friendly-navigation-copy.test.ts tests\test_worker_failure_classify.py` 通过。

### 资料预检失败按钮语义明确
- 问题：Phase1 资料预检失败按钮只写“重试”，PM 不清楚这是重新读资料库，还是重新发起整单评审。
- 改动：`web/components/phases/Phase1Precheck.tsx` 和 `web/components/phases/Phase1PrecheckV8.tsx` 将失败态按钮统一为“重新预检”。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加断言，要求预检页面包含“重新预检”，并禁止按钮文本裸露“重试”。
- 验证：先运行红灯测试确认失败；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "fixed 10-15"` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/extract-worker-errors.test.ts`：29 passed；`npx tsc --noEmit` 通过；`python -m pytest tests\test_worker_failure_classify.py -q`：12 passed。

### 较长 PRD 自动使用结构化摘录
- 问题：四个评审方向重复读取整份 PRD 是评审耗时和中转站 524 的主要放大器之一。此前自动压缩阈值是 3 万字，团队真实 PRD 在 1.2-3 万字区间仍会走全文。
- 改动：`review/prd_context.py` 将默认自动触发阈值降到 12,000 字；`.env.example` 同步 `PECKER_PRD_CONTEXT_AUTO_CHARS=12000`。短 PRD 仍走全文，较长 PRD 走“结构索引 + 维度相关摘录”；需要回滚时可设 `PECKER_PRD_CONTEXT_MODE=full`。
- 防回归：`tests/test_prd_context_packet.py` 增加默认阈值测试，确保 11,999 字不压缩、12,000 字开始压缩，并保留环境变量可调能力。
- 验证：先运行红灯测试确认默认仍是 30,000；修复后 `python -m pytest tests\test_prd_context_packet.py tests\test_worker_timeout_recovery.py tests\test_worker_gateway_recovery.py -q`：9 passed；`git diff --check -- review\prd_context.py tests\test_prd_context_packet.py .env.example` 通过。

### 逐条确认术语翻译继续扩展
- 问题：PM 反馈“部分改动太专业不好理解”。此前已覆盖接口、并发、回调等词，但上线策略类意见常见的状态机、回滚、灰度、埋点、上游下游仍没有解释。
- 改动：`web/lib/pm-friendly.ts` 扩展术语翻译，命中这些词时在逐条确认说明里补一句 PM 可决策解释，避免把研发术语原样推给 PM。
- 防回归：`web/tests/pm-friendly.test.ts` 增加上线策略样例，要求解释包含“状态机可以理解为业务状态怎么流转 / 回滚是出问题后怎么退回 / 灰度是先放给一小部分用户 / 埋点是后续看数据的记录方式 / 上游下游是前后依赖的系统或流程”。
- 验证：先运行红灯测试确认缺失解释；修复后 `npm test -- --run tests/pm-friendly.test.ts -t "release and data"` 通过；`npm test -- --run tests/pm-friendly.test.ts tests/pm-friendly-navigation-copy.test.ts`：28 passed；`npx tsc --noEmit` 通过；`git diff --check -- web\lib\pm-friendly.ts web\tests\pm-friendly.test.ts` 通过。

### 团队版默认不再走 2+2
- 问题：此前为规避中转站 524，`.env.example` 默认 `PECKER_WORKER_BATCH_SIZE=2`，会让深评审变成 2+2 分批。现在已有 524 fallback、PRD context packet 和队列保护，且产品决策已转向不默认尝试 2+2。
- 改动：`.env.example` 默认改为 `PECKER_WORKER_BATCH_SIZE=4`，注释说明 `2` 仅作为临时降级。
- 防回归：新增 `tests/test_team_beta_env_defaults.py`，检查团队版默认 4 worker 并行、PRD context packet 默认打开且阈值为 12,000。
- 验证：先运行红灯测试确认 `.env.example` 仍是 2；修复后 `python -m pytest tests\test_team_beta_env_defaults.py tests\test_worker_batching.py tests\test_langgraph_main_orchestration.py -q`：10 passed；`git diff --check -- .env.example tests\test_team_beta_env_defaults.py` 通过。

### 后台评审完成后自动写 Phase3 草稿
- 问题：PM 在 Phase2 等待期间断网，如果后台 job 已完成但前端没有收到 `result`，前端就无法把 `review_result` 保存到草稿，回到页面时可能仍停在 phase=2。
- 改动：`api/routes/drafts.py` 抽出可复用的原子写草稿函数 `write_draft_file`；`api/routes/review_jobs.py` 在后台 job 成功生成签名评审结果后，服务端直接写入 phase=3 草稿，保留原 PRD、补充材料、用户备注和空决策表。默认复用 SSE 的 stream 分支和 lightweight 分支都覆盖。
- 防回归：`tests/test_review_jobs_route.py` 增加 `test_review_job_completion_persists_phase3_draft` 和 `test_stream_review_job_pipeline_persists_phase3_draft`，模拟浏览器不接收结果也能在 `.pecker_drafts` 里看到 phase=3 草稿。
- 验证：先运行红灯测试确认两个分支草稿文件均不存在；修复后 `python -m pytest tests\test_review_jobs_route.py -k "persists_phase3 or reuse_existing" -q`：3 passed；`python -m pytest tests\test_review_jobs_route.py tests\test_review_job_store.py tests\test_drafts_isolation.py tests\test_admin_usage_summary.py -q`：25 passed；`npm test -- --run tests/draft-persistence.test.ts tests/review-job-resume.test.ts tests/report-contract-store.test.ts`：14 passed；`git diff --check -- api\routes\drafts.py api\routes\review_jobs.py tests\test_review_jobs_route.py` 通过。

### 后台草稿写入竞态保护
- 问题：如果 PM 在等待评审期间断网，然后重新上传了另一份 PRD，旧后台任务晚完成时不应该覆盖新 PRD 的草稿，否则会把用户带回错误的逐条确认材料。
- 改动：`api/routes/drafts.py` 增加内部读取草稿函数 `read_draft_file`；`api/routes/review_jobs.py` 在写入后台完成草稿前先比对 `prd_name`，只有同一份 PRD 才允许把 phase=3 结果写回，避免旧任务晚到污染当前工作台。
- 防回归：`tests/test_review_jobs_route.py` 增加 `test_completed_job_draft_does_not_overwrite_another_prd`，先模拟 PM 已有 `beta.md` 草稿，再让 `alpha.md` 后台任务完成，要求最终草稿仍停留在 `beta.md`。
- 验证：先运行红灯测试确认旧逻辑会覆盖；修复后 `python -m pytest tests\test_review_jobs_route.py -k "draft or persists_phase3 or overwrite_another" -q` 通过，`python -m pytest tests\test_review_jobs_route.py tests\test_review_job_store.py tests\test_drafts_isolation.py tests\test_admin_usage_summary.py -q` 通过（26 passed）。

### 旧上传页草稿恢复文案统一
- 问题：V8 上传页已经用“进度：资料预检/逐条确认”表达草稿位置，但旧上传页仍显示 `Phase 1/2/3`，PM 如果从旧入口进入会再次看到后端分阶段名。
- 改动：`web/components/phases/Phase0Upload.tsx` 增加 `phaseLabel`，恢复 toast 和草稿 badge 改为中文进度标签。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加旧上传页断言，要求包含“进度: ${phaseLabel(draft.phase)} / 进度 {phaseLabel(draft.phase)}”，并禁止 `Phase ${draft.phase}` / `Phase {draft.phase}` 回流。
- 验证：先运行红灯测试确认旧文案存在；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "draft restore"` 通过，`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/draft-persistence.test.ts tests/review-job-resume.test.ts` 通过（33 passed），`npx tsc --noEmit` 通过。

### 后台任务终态后清理本地续接绑定
- 问题：浏览器本地保存了后台 job id 用于断线续接，但如果任务已经成功或失败后仍保留绑定，同一份 PRD 再点重新评审时可能先接回旧结果，而不是发起新任务。
- 改动：`web/lib/useReviewStream.ts` 在收到 result/error/review_failed 等终态事件后清理 `localStorage` 中的 job id，同时把当前 active job 引用置空；取消、无法接回、已有错误快照也同步清理。
- 防回归：`web/tests/review-job-resume.test.ts` 增加终态清理断言，确保终态分支会调用 `clearStoredJobId(resumeKey)` 并清空 active 引用。
- 验证：先运行红灯测试确认终态清理缺失；修复后 `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts tests/extract-worker-errors.test.ts` 通过（37 passed），`npx tsc --noEmit` 通过。

### 后台任务日志密钥脱敏
- 问题：PM 试用真实 PRD 时，后台任务事件和审计日志不会记录 PRD 原文，但如果中转站或 SDK 把 `sk-...`、Bearer token、api_key、password 回显到异常里，错误原文仍可能落到任务快照和 `logs/review_jobs.jsonl`。
- 改动：`api/review_jobs.py` 增加统一脱敏函数，写入 job event、job.error、worker error、审计日志前递归替换敏感片段为 `[REDACTED_SECRET]`；原有 PRD 正文、补充材料、wiki_pages、user_notes 屏蔽策略保持不变。
- 防回归：`tests/test_review_job_store.py` 增加 `test_review_job_store_redacts_secrets_from_errors_and_audit`，模拟 provider 在 worker error 和异常中回显 fake `sk-...`，要求快照和审计日志都不包含原文密钥。
- 验证：先运行红灯测试确认密钥会泄露；修复后 `python -m pytest tests\test_review_job_store.py -q` 通过（12 passed），`python -m pytest tests\test_review_jobs_route.py tests\test_admin_usage_summary.py tests\test_admin_feedback_summary.py -q` 通过（12 passed）。

### 直接流式评审错误脱敏
- 问题：后台 job 已做脱敏，但如果通过 kill switch 临时回退到直接 SSE 流，`api/stream.py` 仍可能把 provider 错误里的密钥直接发给前端或写入日志。
- 改动：新增 `api/sanitize.py` 作为公共脱敏模块；`api/review_jobs.py` 改为复用该模块；`api/stream.py` 在普通事件、worker 错误、`emit_error` 和 pipeline 异常日志中统一脱敏。
- 防回归：`tests/test_stream_disconnect.py` 增加 `test_stream_redacts_secrets_from_public_errors`，覆盖 worker_done error 和 error event 两条直接 SSE 路径。
- 验证：先运行红灯测试确认直接 SSE 会泄露 fake key；修复后 `python -m pytest tests\test_stream_disconnect.py tests\test_review_job_store.py -q` 通过（20 passed），`python -m pytest tests\test_review_jobs_route.py tests\test_admin_usage_summary.py tests\test_admin_feedback_summary.py -q` 通过（12 passed）。

### 稳定性建议去 worker 术语
- 问题：`review/gateway_resilience.py` 的故障摘要建议仍写“降低 worker 并发”“查看失败原文后重试”，如果这段被后台看板或报告引用，会继续显得偏研发排障口径。
- 改动：建议口径改为“降低同时评审方向数”“查看失败原文后重新评审”，保留运行策略含义，但避免 PM 看到 worker/重试这类内部术语。
- 防回归：`tests/test_gateway_resilience.py` 要求建议中包含“降低同时评审方向数”，并禁止出现 `worker`。
- 验证：先运行红灯测试确认旧文案命中；修复后 `python -m pytest tests\test_gateway_resilience.py tests\test_worker_gateway_recovery.py tests\test_langgraph_main_orchestration.py -q` 通过（8 passed），`python -m pytest tests\test_worker_batching.py -q` 通过（3 passed）。

### 网络断开错误文案续接化
- 问题：浏览器网络抖动时常抛 `Failed to fetch`，此前会原样显示给 PM；但后台 job 模式下任务通常仍在服务端继续跑，正确引导应该是刷新后尝试接回，而不是展示英文错误。
- 改动：`web/lib/useReviewStream.ts` 的 `pmFacingReviewMessage` 增加网络断开分类，`Failed to fetch / NetworkError / load failed` 统一转成“网络连接中断，评审任务会继续在后台处理；请刷新页面，系统会尽量继续接回本次评审。”
- 防回归：`web/tests/review-job-resume.test.ts` 增加网络断开用例，要求包含“网络连接中断 / 刷新页面 / 继续接回”，并禁止露出 `Failed to fetch`。
- 验证：先运行红灯测试确认原样暴露；修复后 `npm test -- --run tests/review-job-resume.test.ts tests/extract-worker-errors.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（38 passed），`npx tsc --noEmit` 通过。

### OpenAI 客户端网关瞬时错误补齐
- 问题：主路由已经把 Cloudflare 520-524 识别为可恢复网关故障，但 OpenAI 原生客户端内部重试只覆盖 520/522/524，遇到 521/523 时可能不会换 key 或重试，团队试用时会表现成个别评审方向突然失败。
- 改动：`clients/openai_native.py` 的瞬时错误码补齐 521/523，与 `model_router.py` 的网关兜底策略保持一致；只影响失败恢复路径，不改变正常请求。
- 防回归：`tests/test_openai_native_client.py` 新增 `test_openai_native_client_treats_cloudflare_521_and_523_as_transient`，要求 521/523 都进入瞬时错误判定。
- 验证：先运行红灯测试确认 521 未被识别；修复后 `python -m pytest tests\test_openai_native_client.py -k "521 or 523 or 524" -q` 通过（2 passed），`git diff --check -- clients\openai_native.py tests\test_openai_native_client.py` 通过。

### 登录超时提示去后端化
- 问题：登录接口超时时，前端提示“联系工具负责人检查后端服务”。PM 同事试用时看到“后端服务”会把问题理解成研发排障，而不是当前评审服务暂时不可用。
- 改动：`web/lib/api.ts` 登录超时文案改为“评审服务暂时没有响应，请稍后再试；如果一直卡住，请联系工具负责人检查服务状态。”
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 新增登录超时文案断言，要求包含“评审服务”，禁止出现“后端服务”。
- 验证：先运行红灯测试确认旧文案命中；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "login timeout"` 通过，`git diff --check -- web\lib\api.ts web\tests\pm-friendly-navigation-copy.test.ts` 通过。

### 通用接口错误去 HTTP 状态串
- 问题：接口返回 500 且没有可读 detail 时，前端 `ApiError.message` 会显示 `API 500 Internal Server Error`。登录、资料预检、报告保存等页面如果走 fallback message，会把英文 HTTP 状态直接露给 PM。
- 改动：`web/lib/api.ts` 增加 `formatApiErrorMessage`，5xx 统一提示“服务暂时不可用，请稍后再试”，401/403/404 也转成可理解文案；状态码和 detail 仍保留在 `ApiError.status/detail`，不影响代码分支判断。
- 防回归：`web/tests/login-timeout.test.ts` 新增 500 响应用例，要求不出现 `API 500` 和 `Internal Server Error`。
- 验证：先运行红灯测试确认旧状态串暴露；修复后 `npm test -- --run tests/login-timeout.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（24 passed），`git diff --check -- web\lib\api.ts web\tests\login-timeout.test.ts web\tests\pm-friendly-navigation-copy.test.ts` 通过。

### 逐条确认原文定位支持行范围
- 问题：左侧 PRD 原文高亮此前只支持单行位置，如模型返回“第 3-4 行”，页面只会定位到第 3 行，PM 仍需要自己在原文里继续找问题范围。
- 改动：`web/lib/prd-anchor.ts` 的行号解析支持 `第 3-4 行`、`第 3 至 4 行`、`line 3-4` 等范围表达，并把整段范围作为高亮片段返回。
- 防回归：`web/tests/prd-anchor.test.ts` 新增 `supports line-range references from review output`，要求范围文本包含两行内容，行标签显示“第 3-4 行”。
- 验证：先运行红灯测试确认旧逻辑只返回第一行；修复后 `npm test -- --run tests/prd-anchor.test.ts` 通过（7 passed），`git diff --check -- web\lib\prd-anchor.ts web\tests\prd-anchor.test.ts` 通过。

### 团队版网关请求超时上调
- 问题：`.env.example` 写着 `OPENAI_REQUEST_TIMEOUT=240`，会让团队部署按 4 分钟左右切断单个模型请求；这和 PM 同事截图里 4m13s 左右的 worker 超时高度吻合，也和代码默认的 360 秒以上不一致。
- 改动：团队版示例配置改为 `OPENAI_REQUEST_TIMEOUT=420`，给 GPT 深评 worker 留出 7 分钟请求窗口；并保留 worker 级重试/路由 fallback 作为兜底。
- 防回归：`tests/test_team_beta_env_defaults.py` 新增 `test_team_beta_openai_timeout_covers_deep_review_workers`，要求团队版示例请求超时不少于 360 秒。
- 验证：先运行红灯测试确认旧配置只有 240 秒；修复后 `python -m pytest tests\test_team_beta_env_defaults.py tests\test_openai_native_client.py -k "team_beta or timeout or 521 or 523 or 524" -q` 通过（7 passed），`git diff --check -- .env.example tests\test_team_beta_env_defaults.py clients\openai_native.py tests\test_openai_native_client.py` 通过。

### 多人排队等待窗口与请求窗口对齐
- 问题：团队版允许 5 个模型调用并发、3 个活跃评审排队，但 `PECKER_MODEL_CALL_QUEUE_TIMEOUT=240` 小于新的请求窗口 420 秒。多人同时深评时，排队中的方向可能还没拿到调用槽就被队列超时切掉。
- 改动：`.env.example` 将 `PECKER_MODEL_CALL_QUEUE_TIMEOUT` 调整为 480 秒，确保排队等待至少覆盖一个深评请求周期。
- 防回归：`tests/test_team_beta_env_defaults.py` 新增 `test_team_beta_model_call_queue_timeout_covers_request_timeout`，要求队列等待窗口不小于请求超时窗口。
- 验证：先运行红灯测试确认 240 < 420；修复后 `python -m pytest tests\test_team_beta_env_defaults.py tests\test_model_router_concurrency_gate.py -q` 通过（6 passed），`git diff --check -- .env.example tests\test_team_beta_env_defaults.py` 通过。

### 耗时提示加入多人排队预期
- 问题：上传页只提示“材料较长时会更久”，但团队内网试用的真实慢点还包括多位 PM 同时发起深评后排队等待，容易被误解为页面卡死或评审跑崩。
- 改动：`web/lib/review-eta.ts` 的等待提示加入“多人同时使用时可能排队”，同时保留“刷新或断网后可继续等待”的续接说明。
- 防回归：`web/tests/review-eta.test.ts` 新增排队提示断言；既要求长材料提示可续接，也要求短 PRD 场景提示多人排队。
- 验证：先运行红灯测试确认旧文案缺少排队提示；修复后 `npm test -- --run tests/review-eta.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（29 passed），`git diff --check -- web\lib\review-eta.ts web\tests\review-eta.test.ts web\tests\pm-friendly-navigation-copy.test.ts` 通过。

### 表单校验错误不再展示 JSON
- 问题：FastAPI 422 校验失败时，`detail` 常是数组/对象；前端此前会 `JSON.stringify` 后作为错误 detail 展示，PM 可能看到 `loc/body/msg` 这类技术字段。
- 改动：`web/lib/api.ts` 只把字符串型 detail 作为可展示说明；结构化 detail 不再直出，422 统一提示“请求内容不完整，请检查后再提交”。
- 防回归：`web/tests/login-timeout.test.ts` 新增结构化 422 响应用例，要求 `detail` 为 `undefined`，且 message 不包含 `loc` / `Field required`。
- 验证：先运行红灯测试确认旧逻辑会暴露 JSON；修复后 `npm test -- --run tests/login-timeout.test.ts tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts` 通过（34 passed），`git diff --check -- web\lib\api.ts web\tests\login-timeout.test.ts web\tests\pm-friendly-navigation-copy.test.ts web\tests\review-job-resume.test.ts` 通过。

### 后台评审任务防重复提交
- 问题：PM 双击开始、刷新后短时间重复点击，或前端网络抖动时重复提交同一份 PRD，后端可能创建两个后台评审任务，造成重复扣预算、重复占用模型并发和结果混淆。
- 改动：`api/review_jobs.py` 在创建任务前检查同一评审人、同一资料库、同一 PRD、同一模式是否已有 queued/running 任务；如有则直接复用现有 job。
- 防回归：`tests/test_review_job_store.py` 新增 `test_review_job_store_reuses_running_job_for_same_reviewer_and_prd`，模拟同一请求连续创建两次，要求只启动一次 runner。
- 验证：先运行红灯测试确认会创建两个任务；修复后 `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py -q` 通过（20 passed），`git diff --check -- api\review_jobs.py tests\test_review_job_store.py` 通过。

### 防重复提交增加请求指纹边界
- 问题：仅按 PRD 文件名去重会有误伤：PM 可能上传同名但内容已修改的新 PRD，如果旧任务还在跑，不应该接回旧任务。
- 改动：`api/routes/review_jobs.py` 为评审请求计算不含明文的 SHA-256 短指纹，`api/review_jobs.py` 只在同一评审人、资料库、PRD 名、模式和请求指纹都一致时复用进行中任务；不存储 PRD 原文。
- 防回归：`tests/test_review_job_store.py` 新增 `test_review_job_store_does_not_reuse_same_prd_name_with_different_fingerprint`，要求同名但不同指纹创建两个独立任务。
- 验证：先运行红灯测试确认旧接口不支持指纹边界；修复后 `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py -q` 通过（21 passed），`git diff --check -- api\review_jobs.py api\routes\review_jobs.py tests\test_review_job_store.py` 通过。

### 请求指纹不暴露到前端快照
- 问题：请求指纹虽然不是 PRD 明文，但属于服务端去重实现细节，没有必要通过 job snapshot 返回前端或后台看板。
- 改动：`api/review_jobs.py` 保留内部 `request_fingerprint` 字段用于去重，但从 `snapshot()` 返回值中移除。
- 防回归：`tests/test_review_job_store.py` 在基础快照测试中断言不包含 `request_fingerprint`。
- 验证：先运行红灯测试确认快照会暴露该字段；修复后 `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py tests\test_admin_usage_summary.py -q` 通过（23 passed），`git diff --check -- api\review_jobs.py api\routes\review_jobs.py tests\test_review_job_store.py` 通过。
### 运行明细错误文案复用 PM 友好转换
- 问题：V8 运行页虽然主错误提示已做 PM 友好化，但底部运行明细仍可能直接拼接 `e.message`，当浏览器或网关返回英文错误时，PM 仍会看到 `Request timed out` / `Failed to fetch` 等技术表达。
- 改动：`web/components/phases/Phase2RunningV8.tsx` 的 error console line 改为复用 `pmFacingReviewMessage`，与主流程错误提示保持同一套表达。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加 V8 running 断言，要求运行页源码调用 `pmFacingReviewMessage(e.message)`。
- 验证：先运行红灯测试确认旧实现失败；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "V8 running"` 通过，`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts tests/login-timeout.test.ts tests/review-eta.test.ts` 通过（41 passed），`npx tsc --noEmit` 通过，`git diff --check -- web\components\phases\Phase2RunningV8.tsx web\tests\pm-friendly-navigation-copy.test.ts` 通过。
### 逐条确认原文定位支持跨行引用
- 问题：PM 在逐条确认时需要左侧直接看到“错在哪”。此前定位支持单行、行号和行号范围，但如果模型依据句子在 PRD 原文里被 Markdown 换行拆开，页面会提示“未精确定位”，仍要 PM 手工找。
- 改动：`web/lib/prd-anchor.ts` 的候选匹配增加忽略空白/换行的引用匹配；证据句子即使跨行，也能返回覆盖多行的高亮范围和行号标签。
- 防回归：`web/tests/prd-anchor.test.ts` 新增跨行引用用例，要求 `支持支付前锁定本次使用的积分` 能匹配到第 2-3 行。
- 验证：先运行红灯测试确认旧实现失败；修复后 `npm test -- --run tests/prd-anchor.test.ts -t "wraps"` 通过，`npm test -- --run tests/prd-anchor.test.ts tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts` 通过（39 passed），`npx tsc --noEmit` 通过，`git diff --check -- web\lib\prd-anchor.ts web\tests\prd-anchor.test.ts` 通过。
### 重复提交明确接回进行中任务
- 问题：PM 双击开始、刷新后重复提交，或网络抖动导致前端重发同一份 PRD 时，后端已经能复用进行中的评审任务，但接口响应没有告诉前端“这是接回旧任务”，PM 看不到系统是在续接而不是重新跑。
- 改动：`api/review_jobs.py` 增加 `create_job_with_reuse_info`，`api/routes/review_jobs.py` 的 start 响应新增 `reused`；`web/lib/useReviewStream.ts` 在 `started.reused` 时插入“已接回进行中的评审，本次不会重复生成”的 PM 友好进度事件，V8 运行明细同步展示。
- 防回归：`tests/test_review_job_store.py` 覆盖复用标记；`tests/test_review_jobs_route.py` 覆盖 start 接口第二次提交返回同一 job 且 `reused=true`；`web/tests/review-job-resume.test.ts` 覆盖前端复用提示。
- 验证：先运行红灯测试确认缺少复用标记；修复后 `python -m pytest tests\test_review_job_store.py tests\test_review_jobs_route.py tests\test_admin_usage_summary.py -q` 通过（25 passed），`npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts tests/prd-anchor.test.ts` 通过（40 passed），`npx tsc --noEmit` 通过，`git diff --check` 通过。
### 长 PRD 上下文包保留原文行号
- 问题：为缩短深评耗时，长 PRD 会走本地结构化上下文包；但旧上下文包只保留章节名和摘录，不标注原文行号。这样 worker 如果基于压缩摘录提出意见，后续逐条确认时 PM 仍可能难以定位到原文。
- 改动：`review/prd_context.py` 的章节切分保留 `start_line/end_line`，结构索引和每段摘录标题都增加“原文第 X-Y 行”。
- 防回归：`tests/test_prd_context_packet.py` 新增行号保留用例，要求字段口径和目标章节在上下文包里带原文行号范围。
- 验证：先运行红灯测试确认旧上下文包没有行号；修复后 `python -m pytest tests\test_prd_context_packet.py -k line_ranges -q` 通过，`python -m pytest tests\test_prd_context_packet.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py -q` 通过（11 passed），`python -m pytest tests\test_langgraph_main_orchestration.py tests\test_gateway_resilience.py -q` 通过（7 passed），`git diff --check -- review\prd_context.py tests\test_prd_context_packet.py` 通过。
### 压缩视图提示评审员输出原文行号
- 问题：上下文包带了原文行号后，如果 prompt 没提醒评审员优先使用这些行号，模型仍可能只写章节名，导致确认页锚点命中率没有充分提升。
- 改动：`review/prompting.py` 在压缩视图说明里增加输出约束：如果摘录标题带原文行号，`location / 位置` 优先写成“原文第 X-Y 行 + 章节名”。
- 防回归：`tests/test_prd_context_packet.py` 新增 prompt 断言，确认压缩视图会要求原文行号写法。
- 验证：先运行红灯测试确认旧 prompt 没有约束；修复后 `python -m pytest tests\test_prd_context_packet.py -k "line_ranges or original_line_ranges" -q` 通过，`python -m pytest tests\test_prd_context_packet.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py tests\test_langgraph_main_orchestration.py -q` 通过（17 passed），`python -m pytest tests\test_default_model_routes_gpt_only.py tests\test_model_router.py -q` 通过（34 passed），`git diff --check -- review\prd_context.py review\prompting.py tests\test_prd_context_packet.py` 通过。
### 普通 PRD 输出也要求可搜索位置
- 问题：即使不走压缩视图，评审员仍可能把 `location` 写成“全文/整体/上述”，逐条确认页难以自动高亮原文，PM 需要自己找问题位置。
- 改动：`review/prompting.py` 的最终提交要求增加通用约束：`location / 位置` 请写成可在 PRD 中搜索到的短句、章节名或原文行号，避免只写“全文/整体/上述”。
- 防回归：`tests/test_prd_context_packet.py` 新增普通 PRD prompt 用例，确认所有 worker 消息都包含可搜索位置要求。
- 验证：先运行红灯测试确认旧 prompt 缺少该约束；修复后 `python -m pytest tests\test_prd_context_packet.py -k "searchable_locations or original_line_ranges" -q` 通过，`python -m pytest tests\test_prd_context_packet.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py tests\test_langgraph_main_orchestration.py tests\test_model_router.py -q` 通过（46 passed），`git diff --check -- review\prompting.py tests\test_prd_context_packet.py` 通过。
### 敏感信息落库/落文件巡检
- 检查：对仓库执行高置信密钥扫描，重点覆盖 `sk-` 长 token、已知密码片段、`OPENAI_API_KEY=[REDACTED]`、常见 password 写法。
- 结果：`rg -l "sk-[A-Za-z0-9]{20,}" .` 仅命中测试里的假 key；`rg -n "sk-[A-Za-z0-9]{20,}" tests\...` 确认均为 `fake_key` / secret gate 测试样例。未发现真实 API key、团队密码或 GitLab 密码写入项目文件。
- 结论：当前新增的 job 日志脱敏、stream 脱敏和部署 env 示例没有引入新的明文 secret 风险。
### PM 下载报告默认不夹排障 JSON
- 问题：`generateReportMarkdown` 末尾默认附带“维护人排障信息”折叠块和 JSON，虽然便于后续 eval，但 PM 下载报告会显得像内部调试产物，也可能让同事误解字段含义。
- 改动：`web/lib/generateReport.ts` 增加 `includeMaintenanceDetails` 显式选项，默认不输出维护人 JSON；需要内部排障时仍可主动打开。
- 防回归：`web/tests/report-markdown-copy.test.ts` 要求默认报告不包含“维护人排障信息”和 ```json，同时新增显式打开选项的覆盖。
- 验证：先运行红灯测试确认旧报告默认包含排障 JSON；修复后 `npm test -- --run tests/report-markdown-copy.test.ts` 通过，`npm test -- --run tests/report-markdown-copy.test.ts tests/revision-downloads.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（26 passed），`npx tsc --noEmit` 通过，`git diff --check -- web\lib\generateReport.ts web\tests\report-markdown-copy.test.ts` 通过。
### 管理看板直达 URL 加管理员护栏
- 问题：顶部导航已对非管理员隐藏“团队使用情况”，但 `/system/usage` 页面自身只依赖后端 403 兜底，普通 PM 直达 URL 时仍会先执行后台查询逻辑，体验和边界都不够清楚。
- 改动：`web/app/system/usage/page.tsx` 与 health/prompts 一样包进 `AdminOnlyPage`，普通 PM 直接看到管理员限制说明，不进入后台数据页面。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加 usage 页必须包含 `AdminOnlyPage` 的断言。
- 验证：先运行红灯测试确认 usage 页缺少管理员护栏；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "run and system"` 通过，`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts tests/report-markdown-copy.test.ts` 通过（27 passed），`npx tsc --noEmit` 通过，`git diff --check -- web\app\system\usage\page.tsx web\tests\pm-friendly-navigation-copy.test.ts` 通过。
### 过程回放直达 URL 加管理员护栏
- 问题：`/runs/[id]/replay` 是维护人用来看评审过程和原始排障记录的页面，顶部导航不暴露给 PM 之后，直达 URL 仍可能绕过入口控制，看到偏后台的过程数据。
- 改动：`web/app/runs/[id]/replay/page.tsx` 和系统看板保持一致，外层包裹 `AdminOnlyPage`，普通评审人直达时先看到管理员限制说明，不进入过程回放内容。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加断言，要求 replay 页面源码包含 `AdminOnlyPage`。
- 验证：`npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "run and system"` 通过（1 passed）；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts tests/report-markdown-copy.test.ts` 通过（27 passed）；`npx tsc --noEmit` 通过；`git diff --check -- web/app/runs/[id]/replay/page.tsx web/tests/pm-friendly-navigation-copy.test.ts` 通过。
### E2E 覆盖同步到团队默认视角
- 问题：部分 Playwright 脚本还在验证旧的维护人页面假设，例如组件预览默认开放、`/runs/diff` 展示 Harness Run 对比、系统页展示 Harness 文案。这会让研发/运维复测时拿旧标准判断新团队版 UI，造成“改动丢了”的错觉。
- 改动：`web/tests/e2e/v8-routes.spec.ts` 改为验证团队默认视角：组件预览默认关闭、评审记录页默认展示个人历史、过程回放和系统页默认进入管理员护栏；`bird-portrait-check` 和响应式截图从 `/v8-preview` 改到 `/review?demo=1`，避免把维护人组件预览暴露给 PM 视觉验收。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加 e2e 源码漂移检查，禁止重新出现旧 Harness 正向文案、`event timeline` 和默认 `/v8-preview` 截图入口。
- 验证：先运行新增漂移测试确认旧 e2e 命中 `Harness ·`；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "e2e smoke"` 通过；`npx playwright test tests/e2e/v8-routes.spec.ts --project=chromium-desktop` 通过（5 passed）；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts tests/report-markdown-copy.test.ts tests/review-job-resume.test.ts tests/prd-anchor.test.ts` 通过（46 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 报告出口提示去掉后端和飞书配置噪声
- 问题：报告出口的旧版卡片仍显示“浏览器本地保存,不走后端”，飞书未配置时会把 `FEISHU_APP_ID/APP_SECRET/CHAT_ID` 这类环境变量名直接给 PM 看；V8 推送成功提示还带“消息号”。这些信息对 PM 决策无帮助，反而像工程排障页面。
- 改动：`Phase4Report` 的下载说明改为“下载到本机,便于转发和归档”；飞书未配置统一提示“请联系工具负责人”；`Phase4ReportV8` 推送成功只提示“已推送到飞书”，消息 ID 仍保留在审计日志里，不出现在 PM toast。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 的报告页检查增加断言，禁止“ 不走后端 ”、飞书环境变量、`msg_id=` 和“消息号”重新进入报告页源码。
- 验证：先运行红灯测试确认旧表达存在；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "report-preview"` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/report-markdown-copy.test.ts tests/revision-downloads.test.ts` 通过（27 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 运行页处理明细提示从排障改为复盘
- 问题：Phase2 V8 底部“处理明细”虽然默认收起，但折叠态说明仍写“排障时可展开”，PM 会感觉这是维护后台日志，而不是可以理解评审过程的辅助信息。
- 改动：`web/components/phases/Phase2RunningV8.tsx` 把提示改为“需要复盘时可查看每个阶段的处理记录”，保留展开能力，但语义从工程排障转为业务复盘。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 要求出现新文案，并禁止“排障时可展开”回流。
- 验证：先运行红灯测试确认缺少新文案；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "run detail"` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts tests/extract-worker-errors.test.ts` 通过（41 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 登录态检查增加短超时
- 问题：登录提交已有 10 秒超时，但 `/api/me` 登录态检查没有超时；登录页、顶部导航和管理员护栏都会用它。如果服务端或反代卡住，页面可能长时间停在“正在确认权限”或类似等待态。
- 改动：`web/lib/api.ts` 给 `authApi.me()` 增加 5 秒超时，失败文案为“暂时无法确认登录状态，请刷新后再试”，让 React Query 能结束 pending 状态，页面进入明确的未登录/无权限兜底。
- 防回归：`web/tests/login-timeout.test.ts` 增加登录态查询超时用例，模拟 fetch 永不返回，要求 5 秒后抛出 PM 可理解的 `ApiError`。
- 验证：先运行红灯测试确认 `/api/me` 不带 `AbortSignal`；修复后 `npm test -- --run tests/login-timeout.test.ts -t "login-state"` 通过；`npm test -- --run tests/login-timeout.test.ts tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts` 通过（37 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 管理员护栏区分权限不足与登录态异常
- 问题：管理员页面依赖 `/api/me`；一旦登录态查询超时或网络错误，旧逻辑会把 `me` 为空直接当作“不是管理员”，管理员本人看到的也是“仅管理员可见”，排障方向不清楚。
- 改动：`web/components/auth/AdminOnlyPage.tsx` 读取 `isError`，登录态查询失败时展示“暂时无法确认权限 / 请刷新页面后再试”，与普通非管理员访问分开。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加管理员护栏源码断言；`web/tests/e2e/v8-routes.spec.ts` 的管理员页 smoke 同步允许该错误态标题。
- 验证：先运行红灯测试确认缺少 `isError`；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "admin guard auth"` 通过；`npm test -- --run tests/login-timeout.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（28 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 后端登录错误不再暴露环境变量名
- 问题：如果内网部署漏配登录密码或 JWT secret，后端 `auth.py` 会直接把 `PECKER_WEB_PASSWORD` / `PECKER_JWT_SECRET` 写进 HTTP detail。前端大多会转译，但直接接口错误、代理日志或浏览器网络面板仍可能暴露内部配置名。
- 改动：`api/routes/auth.py` 的 503/500 detail 改为“请联系工具负责人处理”的 PM/运维友好表达，不再回显环境变量名；顺手把 JWT 时间戳改为 timezone-aware，消除 `datetime.utcnow()` 弃用告警。
- 防回归：`tests/test_api_auth.py` 增加缺密码和 JWT secret 过短两个用例，要求状态码保持 503/500，但 detail 不包含环境变量名。
- 验证：先运行红灯测试确认两个环境变量名会暴露；修复后 `python -m pytest tests\test_api_auth.py -k "env_var or admin_flag" -q` 通过（3 passed）；`python -m pytest tests\test_api_auth.py tests\test_drafts_isolation.py tests\test_review_jobs_route.py -q` 通过（19 passed）；`npm test -- --run tests/login-timeout.test.ts` 通过（4 passed）；`git diff --check` 通过。
### 团队版模型配置说明去旧口径
- 问题：热路径已切到 GPT/OpenAI 路由，但 `.env.example`、`model_routes.yaml` 和部分后端注释还在推荐 `opus/sonnet/haiku`、`Claude 调用前检查`、`--model opus` 等旧口径，容易让运维和后续维护者误以为团队版仍依赖个人 Claude/OAT。
- 改动：`.env.example` 的 `PECKER_MODEL_OVERRIDE` 只推荐 `auto/gpt55/gpt54/gpt54mini`，预算说明改为“每次模型调用前检查”；`model_routes.yaml` 改成“默认由 GPT 路由表控制”；`api/routes/review.py` 和 `api/deps.py` 注释同步改为 LLM/model_router/legacy client 语义。
- 防回归：`tests/test_team_beta_env_defaults.py` 增加漂移测试，禁止团队部署说明重新出现旧 Claude 档位和旧预算口径。
- 验证：先运行红灯测试确认旧说明会失败；修复后 `python -m pytest tests\test_team_beta_env_defaults.py -q` 通过（7 passed）；`python -m pytest tests\test_default_model_routes_gpt_only.py tests\test_gpt_route_hot_path.py -q` 通过（8 passed）；`git diff --check` 通过。
### 运行页失败态不再暴露原始错误串
- 问题：普通运行页和 V8 运行页在 worker 失败时都有“给维护人看的错误原文”折叠块，PM 会看到 `Request timed out`、网关错误或模型调用原文，既不利于理解，也容易把内部排障信息带到试用反馈里。
- 改动：普通运行页改为“查看未完成方向”，每个方向只展示 PM 可理解的失败说明；V8 顶部红条改为“查看处理建议”，不再直接渲染 `banner.errorPreview`。原始错误仍留在后台事件、job snapshot 和日志里，维护人可以从后台排查。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 禁止运行页源码重新出现“给维护人看的错误原文”、`we.error.slice` 和直接渲染 `banner.errorPreview`。
- 验证：先运行红灯测试确认旧 UI 会失败；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "running pages"` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/review-job-resume.test.ts tests/extract-worker-errors.test.ts` 通过（42 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 下载报告和修订建议包进一步 PM 化
- 问题：报告和修订建议包仍把内部条目 ID 写在标题里，并显示“评审编号”“可信度 91%”“原始评审问题”等系统化标签。PM 转发给需求 owner 时，会像机器日志而不是评审结论。
- 改动：主报告、修订建议包、修订稿草案统一把“评审编号”改为“追踪编号”；条目标题移除 `R-001` 这类内部 ID；“可信度”改为“参考程度: 依据充分 / 可参考 / 需再核对”；改写场景的“原始”改为“原意见”。
- 防回归：`web/tests/report-markdown-copy.test.ts` 和 `web/tests/revision-downloads.test.ts` 增加断言，禁止 `### 1. R-001`、`可信度`、`原始评审问题` 等表达回流。
- 验证：先运行红灯测试确认旧报告输出会失败；修复后 `npm test -- --run tests/report-markdown-copy.test.ts tests/revision-downloads.test.ts tests/pm-friendly-navigation-copy.test.ts` 通过（29 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### DeepSeek 备用线路改为 worker 兼容模型
- 问题：默认 worker 的 `fallback_route` 指向 `fallback.deepseek_v4_pro`，但同一个配置文件又标注 pro 不支持 worker 需要的结构化 tool 调用。这会导致 GPT 主线路超时后，备用线路也可能因为 tool_choice 不兼容继续失败。
- 改动：默认 worker 和苍鹰 fallback 改为 `fallback.deepseek_v4_flash`，使用支持 function calling 的 flash 档；pro tier 保留在 vendor 定义里，作为后续手动实验，不再作为团队版自动兜底。
- 防回归：`tests/test_default_model_routes_gpt_only.py` 增加断言，要求默认 worker fallback 必须是 `deepseek-v4-flash`。
- 验证：先运行红灯测试确认默认 fallback 仍是 pro；修复后 `python -m pytest tests\test_default_model_routes_gpt_only.py -q` 通过（7 passed）；`python -m pytest tests\test_default_model_routes_gpt_only.py tests\test_model_router.py tests\test_deepseek_native_client.py -q` 通过（37 passed）；`git diff --check` 通过。
### 模型路由注释同步 GPT-only 团队口径
- 问题：`model_router.py` 的用法示例和 override 注释仍写 `model_override="opus"`、`PECKER_MODEL_OVERRIDE=opus|sonnet|haiku|auto`，容易误导后续研发以为团队版还要按旧 Claude 档位调参。
- 改动：示例改成 `model_override="gpt55"`，env 注释改成 `auto|gpt55|gpt54|gpt54mini`，并把跨 vendor 示例改成 OpenAI/DeepSeek 口径。
- 防回归：`tests/test_team_beta_env_defaults.py` 增加源码注释漂移断言。
- 验证：先运行红灯测试确认旧注释存在；修复后 `python -m pytest tests\test_team_beta_env_defaults.py tests\test_model_router.py -q` 通过（36 passed）；`git diff --check` 通过。
### 报告页复核说明去内部术语
- 问题：V8 报告页的复核说明区仍叫“评审治理摘要”，并显示“保留少数派”，容易让 PM 感觉是内部算法机制而不是结果可信度说明。
- 改动：区块标题改成“结果复核说明”，少数意见保留文案改成“保留少数意见”，保留多轮复核信息但去掉治理/少数派术语。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加断言，要求报告页出现新文案并禁止旧术语回流。
- 验证：先运行红灯测试确认旧文案存在；修复后 `npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "report confidence"` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/report-markdown-copy.test.ts tests/revision-downloads.test.ts` 通过（30 passed）；`npx tsc --noEmit` 通过；`git diff --check` 通过。
### 管理看板增加逐条确认筛选
- 问题：逐条确认反馈已经落到 `eval/ground_truth` 和草稿汇总里，但管理员页面只能看最近列表。第一波 PM 反馈里最有价值的是“驳回”和“改写”，没有筛选会增加人工翻找成本。
- 改动：`/system/usage` 的“逐条确认反馈”增加“全部反馈 / 只看驳回 / 只看改写 / 只看认可”筛选；前端 `adminUsageApi.feedback` 支持 action、reviewer、workspace、limit 参数；页面新增“按同事看 / 按资料库看”反馈分布，方便第一波试用后定位谁反馈多、哪个资料库问题集中。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 增加源码断言，确保后台反馈区保留可筛选入口，且 API 层不会把 `all` 当作实际筛选条件传给后端。
- 验证：`npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "decision feedback"` 通过；`python -m pytest tests\test_admin_feedback_summary.py tests\test_admin_usage_summary.py -q` 通过（5 passed）；补类型导入后 `npx tsc --noEmit` 通过；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts tests/pm-friendly.test.ts tests/report-markdown-copy.test.ts` 通过（37 passed）。
### 报告和交接输出统一 PM 方向名
- 问题：界面已经把四个评审方向改成“业务完整性 / 字段口径 / 使用体验 / 实现风险”，但 PM 友好投影和下载报告里仍会出现“结构 / 质量 / 数据质量”等内部分类，第一波试用反馈会觉得术语不稳定。
- 改动：`web/lib/pm-friendly.ts` 的方向标签统一到界面同款表达；`generateReportMarkdown` 每条意见增加“PM 需要判断”和“建议动作”，让下载报告不只给原始问题，还告诉 PM 下一步该怎么决策。
- 防回归：`web/tests/pm-friendly.test.ts` 增加方向名一致性断言；`web/tests/report-markdown-copy.test.ts` 增加报告中必须出现“PM 需要判断 / 建议动作”和 PM 方向名的断言。
- 验证：先运行红灯测试确认旧方向名失败；修复后 `npm test -- --run tests/pm-friendly.test.ts tests/report-markdown-copy.test.ts` 通过（11 passed）；`git diff --check -- web\lib\pm-friendly.ts web\lib\generateReport.ts web\tests\pm-friendly.test.ts web\tests\report-markdown-copy.test.ts` 通过。
### 稳定性摘要补充压缩视图和恢复证据
- 问题：线上超时反馈里最难判断的是“是否仍然四个方向重复喂完整 PRD、是否已经触发恢复策略”。旧的 resilience summary 只统计失败类型和建议降并发，证据不够。
- 改动：`review/gateway_resilience.py` 在 summary 中增加 `context_packet_workers`、`max_context_packet_chars` 和 `recovered_workers`，同时把超时建议补成“启用超时恢复或压缩知识库上下文 / 失败方向改走备用线路或恢复重试”。这样 LangGraph 返回的 `resilience` 可以直接说明本轮是否用过压缩 PRD 视图、是否有方向恢复成功。
- 防回归：`tests/test_gateway_resilience.py` 增加断言，覆盖 524 场景下压缩视图统计、恢复方向统计和运维建议。
- 验证：`python -m pytest tests\test_gateway_resilience.py tests\test_langgraph_main_orchestration.py -q` 通过（7 passed）；`git diff --check -- review\gateway_resilience.py tests\test_gateway_resilience.py` 通过。
### 后台草稿写回增加资料库边界
- 问题：后台任务完成后会帮 PM 写回 Phase3 草稿，解决断网后可续接的问题；但旧保护只比对 `prd_name`。如果 PM 切到另一个资料库，文件名刚好相同，旧任务晚到时仍可能覆盖新草稿。
- 改动：`api/routes/review_jobs.py` 的草稿写回条件升级为同一个 `prd_name` 且同一个 `workspace` 才允许覆盖；不同资料库的同名 PRD 直接跳过写回，避免跨资料库污染。
- 防回归：`tests/test_review_jobs_route.py` 增加同名不同资料库用例，确认旧任务不会覆盖当前工作台。
- 验证：`python -m pytest tests\test_review_jobs_route.py -k "draft or persists_phase3 or overwrite" -q` 通过，4 passed；`python -m pytest tests\test_review_jobs_route.py -q` 通过，9 passed。

### 长 PRD 压缩视图复用章节切分
- 问题：长 PRD 已经会自动走“结构索引 + 维度相关摘录”，但每个评审方向都会重新切分同一份 PRD 章节。它不等于重复调模型，但会增加本地预处理、恢复重试和并发排队时的额外消耗。
- 改动：`review/prd_context.py` 增加进程内 LRU 缓存，只缓存 PRD 章节切分结果；不同方向仍然按各自关键词重新打分和选择摘录，避免牺牲业务/字段/体验/实现风险的方向差异。
- 防回归：`tests/test_prd_context_packet.py` 增加缓存命中测试，确保同一份长 PRD 被不同 worker 方向处理时只产生一次章节切分 miss，后续方向复用缓存。
- 验证：`python -m pytest tests\test_prd_context_packet.py -k "cached_across_worker_dimensions" -q` 通过；`python -m pytest tests\test_prd_context_packet.py -q` 通过，10 passed。

### 旧版报告页运行细节去技术化
- 问题：旧版报告页的折叠块仍叫“维护人排障信息”，并展示 token 输入/输出和成本归因。即使默认折叠，它仍然是 PM 可见报告页的一部分，容易把报告体验拉回工程排障界面。
- 改动：`web/components/phases/Phase4Report.tsx` 将折叠块改为“运行记录”，只保留总耗时和各方向耗时；成本和 token 不再出现在 PM 报告页，相关成本仍由后台预算和管理员看板承接。
- 防回归：`web/tests/pm-friendly-navigation-copy.test.ts` 验证旧版报告页包含“运行记录/处理耗时”，并禁止 `tokens_in`、`tokens_out`、`成本归因`、`维护人排障信息` 回流。
- 验证：`npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "legacy report run details"` 通过；`npx tsc --noEmit` 通过。

### 管理看板活跃草稿补充安全诊断摘要
- 问题：后台任务结果已经能保留 telemetry，但 `/admin/usage` 的活跃草稿摘要仍只显示阶段、条数和处理进度。PM 断网后停在逐条确认时，管理员无法从看板判断本轮耗时、是否触发恢复、是否已使用 PRD 压缩视图。
- 改动：`api/routes/admin_usage.py` 从草稿里的 `review_result.telemetry` 只提取白名单统计字段：总耗时、编排方式、失败/恢复方向数、压缩视图使用数和最大压缩长度；不返回 worker 原始错误、PRD 正文或条目正文。`web/app/system/usage/page.tsx` 的活跃草稿行展示一行安全摘要，`web/lib/api.ts` 同步类型。
- 防回归：`tests/test_admin_usage_summary.py` 验证活跃草稿返回安全统计且不泄露 `internal detail`；`web/tests/pm-friendly-navigation-copy.test.ts` 验证管理看板保留安全诊断入口。
- 验证：`python -m pytest tests\test_admin_usage_summary.py -q` 通过，2 passed；`npm test -- --run tests/pm-friendly-navigation-copy.test.ts -t "safe run diagnostics"` 通过；`npx tsc --noEmit` 通过。

### 后台任务结果保留运行诊断
- 问题：`/api/review/run` 已经在结果里组装了总耗时和 worker telemetry，但 `ReviewResult.create` 没有 telemetry 字段，后台任务的 lightweight 路径也没有把 LangGraph/resilience 摘要带回前端。结果是 PM 看到超时后，管理员看板和任务恢复页缺少“用了哪条编排、哪些 worker 恢复成功、每个 worker 耗时多少”的关键证据。
- 改动：`api/models.py` 的 `ReviewResult` 增加 `telemetry`，`api/routes/review.py` 传入已有 telemetry；`api/routes/review_jobs.py` 在后台任务完成时汇总 `total_duration_ms`、worker telemetry、`orchestrator` 和 `resilience`，随签名结果一起返回并写入 Phase3 草稿。
- 防回归：`tests/test_hmac_scope.py` 验证 telemetry 会被保留，且不削弱 items/workspace/reviewer 的 HMAC 校验；`tests/test_review_jobs_route.py` 验证后台任务结果包含 worker 耗时、恢复状态、LangGraph 标识和 resilience 摘要。
- 验证：`python -m pytest tests\test_hmac_scope.py -q` 通过，10 passed；`python -m pytest tests\test_review_jobs_route.py -q` 通过，8 passed；`npx tsc --noEmit` 通过。
## 2026-05-09 10:55 收口中检查点
- 最新已完成补丁
  - 复盘页和报告可选维护段继续去“排障”化，统一为“处理原始记录 / 维护人处理记录”。
  - 管理看板最近处理轨迹移除 token 计数字段，只保留耗时、方向、条数、状态和压缩视图大小。
  - 后台任务复用指纹纳入资料库页面内容，避免同名 PRD 在资料库刚更新后误接旧任务；指纹只做哈希，不存正文。
  - 网关稳定性建议从“失败方向”改成“未完整返回的方向”，避免暗示 UI 已支持单方向重跑。
  - PM 术语翻译继续扩展到 P99/QPS/限流/熔断、队列积压、补偿任务、脱敏审计和黑白名单。
- 最新验证
  - `python -m pytest tests\test_model_router_concurrency_gate.py tests\test_worker_batching.py tests\test_worker_gateway_recovery.py tests\test_gateway_resilience.py tests\test_langgraph_main_orchestration.py tests\test_review_jobs_route.py tests\test_review_job_store.py tests\test_prd_context_packet.py tests\test_admin_usage_summary.py -q`：50 passed。
  - `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts tests/pm-friendly.test.ts tests/extract-worker-errors.test.ts tests/draft-persistence.test.ts tests/report-markdown-copy.test.ts tests/review-eta.test.ts tests/prd-anchor.test.ts`：8 files / 78 tests passed。
  - `npx tsc --noEmit`：passed。
  - `git diff --check`：passed。
  - 非测试文件密钥形态扫描：`non_test_secret_path_hits=0`；测试目录保留 fake key 用于 secret gate 回归。
  - 全量后端：`python -m pytest -q`，1436 passed，4 warnings。
  - 全量前端：`npm test`，20 files / 162 tests passed。
  - 前端 lint：`npm run lint`，0 errors，6 个既有 `<img>` warning。
  - 前端生产构建：`npm run build`，Next.js production build passed，12 个静态页面生成通过。
  - E2E smoke：`npm run test:e2e -- --project=chromium-desktop tests/e2e/smoke.spec.ts`，6 passed；同步修正旧英文/Agent 断言到当前 PM 友好文案。
- 当前残余风险
  - 未重新跑真实中转站端到端，代码层保护已增强，但线上稳定性仍受中转站 524/超时/并发排队影响。
  - 大量改动仍在本地未提交状态，最终推内网前需要做一次完整 diff review、secret scan 和至少一轮后端/前端广回归。
  - 管理后台现在能看到安全摘要和任务轨迹，但如果服务重启，内存 job 仍会丢失；草稿和审计日志能辅助恢复，但不是完整持久化队列。
- 回滚方式
  - 前端后台任务模式可通过 `NEXT_PUBLIC_REVIEW_JOB_MODE=0` 回到旧 SSE 直连路径。
  - 编排可通过 `PECKER_REVIEW_ORCHESTRATOR=legacy` 回到 legacy 编排。
  - 长 PRD 压缩视图可通过调高 `PECKER_PRD_CONTEXT_PACKET_THRESHOLD` 或关闭相关策略回到更接近完整 PRD 输入的方式。

## 2026-05-09 11:20 收口补丁
- 最新已完成补丁
  - 运行页错误提示继续去后端化：`后台日志 / 模型线路 / 系统会尽量` 改为 `工具负责人查看 / 评审线路 / 页面会尝试接回`。
  - 超时错误 banner 仍保留可操作建议，但不再把英文超时原文、debug/log 或模型供应商术语暴露给 PM。
  - `reviewJobResumeKey` 已保持把资料库页面内容纳入哈希，避免同名 PRD 在资料库更新后误接旧后台任务。
  - 多人同时使用时新增 `review_queued` 阶段：PM 会看到“已进入评审队列，等待空闲评审位”，真正拿到全局并发位后才显示“四个方向开始并行检查”。
- 最新验证
  - `npm test -- --run tests/review-job-resume.test.ts`：11 passed。
  - `npm test -- --run tests/extract-worker-errors.test.ts tests/review-job-resume.test.ts`：2 files / 19 tests passed。
  - `python -m pytest tests\test_review_jobs_route.py tests\test_stream_disconnect.py -q`：18 passed。
  - `npm test -- --run tests/review-job-resume.test.ts tests/pm-friendly-navigation-copy.test.ts`：2 files / 39 tests passed。
  - `python -m pytest tests\test_review_jobs_route.py tests\test_api_auth.py -q`：15 passed。
  - `python -m py_compile api\routes\review.py api\routes\review_jobs.py api\stream.py`：passed。
  - `npx tsc --noEmit`：passed。
  - `git diff --check`：passed。
  - PM 可见敏感词回扫：`后台日志 / 模型线路 / 系统会尽量 / 排查模型线路 / 排查服务状态` 在 `web/app`、`web/components`、`web/lib` 中已无可见文案残留；仅测试断言和代码注释保留历史约束词。
