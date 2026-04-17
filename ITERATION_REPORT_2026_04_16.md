# 啄木鸟 Harness 自主迭代报告 — 2026-04-16

> 由 Claude 在用户授权下自主迭代 13 轮生成,期间无人值守。
> 本文件为一次性手写快照,日常项目状态以自动生成的 `STATUS.md` 为准。

## 一、量化总账

| 指标 | 对话起点 | 现在 | Δ |
|------|----------|------|---|
| pytest 用例数 | 143 | **416** | +273 (+191%) |
| 通过率 | 100% | 100% | 持平 |
| 核心模块数 | 1 (run_session 891 行单体) | 8 (含 5 个抽出 + 3 个 ops 脚本) | — |
| `run_session.py` 行数 | 891 | 565 | -37% |
| 已删手写自评文档 | 0 | 2 (HARNESS_MATURITY + PRODUCTION_READINESS) | + CI gate 防复活 |
| STATUS 指标类别 | 1 个混淆 consistency | 10+ 分层 (outcomes / flow / goshawk verdict / empty_retry / error fingerprint) | — |
| 跨 env 常量崩溃 bug | 1 (session 2 repro) | 0 + AST 扫描防御测 | — |
| 已修 runtime bug | 0 | 3 (GOSHAWK_TIMEOUT / empty submission / eval_history 非原子写) | — |

## 二、按轮次展开

### 第 1 轮 — STATUS 增扩:flow dropout + error fingerprint
- 添加 `flow_milestones` / `completion_rate` / `checkpoint_rate` / `final_reviewer_failure_rate`
- 添加 `_error_fingerprint(err)` 归一化聚合,路径和时间戳打码
- **发现**: 真实 session 苍鹰终审失败率 **100%** (GOSHAWK bug repro 证据)
- 新增测试 7 条

### 第 2 轮 — 消费 empty_retry_used telemetry
- `api/routes/review.py` 持久化 `empty_retry_used` / `turns_used` 到 jsonl
- `generate_status.py` 聚合 retry 触发率/救回率
- 报告里加"[pending] 尚无埋点"状态提示(新代码还没产生数据)
- 新增测试 3 条

### 第 3 轮 — `goshawk_advisor.py` 审计 + 真 bug 修复
- **真 bug**: 苍鹰调了 `submit_advisor_review` 但三个数组全空时被静默接受
- 新增 `_is_empty_advisor_submission()` + empty-retry 分支
- 精细化 verdict: **REVIEWED / EMPTY_APPROVAL / SILENT / TIMEOUT** (原来一律 REVIEWED)
- 新增测试 12 条

### 第 4 轮 — `cuckoo_eval.py` 加固
- **真 bug**: `append_eval_history` 对缺失 score key 硬崩 + 非原子写易污染
- 新增 `_safe_get()` 降级读取,`_atomic_write_json()` 原子写
- `print_eval_trend` 对损坏 JSON 静默返回
- 新增测试 16 条

### 第 5 轮 — 跨 env `from agent_config import` 扫雷
- 用 AST 扫全仓实际被 import 的 15 个符号
- 验证 `dev` / `prod` / `test` 三环境下都能成功 import
- 加参数化回归测试(subprocess 隔离,防 config 缓存污染)
- 新增测试 3 条

### 第 6 轮 — `shrike_review.py` Gate 覆盖
- SECURITY_PATTERNS 覆盖: sk- API key / ghp_ GitHub token / 明文密码 / 内网 IP (10/172.16-31/192.168) / 带凭据连接串
- `check_report_completeness` / `check_id_consistency` 边界场景
- 新增测试 20 条

### 第 7 轮 — `cuckoo_parser.py` 覆盖
- `compute_confidence` 全映射 + 补充衰减
- `parse_review_report` 三策略分支 (YAML / Markdown / loose 兜底)
- `_extract_fields_from_block` 多格式字段 + evidence_type 推断
- 新增测试 21 条

### 第 8 轮 — STATUS 消费 goshawk verdict
- `api/routes/review.py` 持久化 verdict / confidence / empty_retry_used
- `generate_status.py` 新增"苍鹰 verdict 分布"章节
- 新增测试 5 条

### 第 9 轮 — `majority_vote` + `merge_and_deduplicate` 覆盖
- merge_and_deduplicate: 空/单条/相似去重/严重度优先/must 排序/重编号
- majority_vote: min_votes 门槛/rule_id 精确匹配/issue 相似度兜底/最长 item 保留
- 新增测试 16 条

### 第 10 轮 — `review_fixer.infer_evidence_type` 覆盖
- 全依据类型映射 (A / B / C / 空)
- 优先级正确性 (A > B > C)
- `fix_review_items` stats 形状稳定性 + verify 异常时全 unchecked 降级
- 新增测试 18 条

### 第 11 轮 — `feedback._normalize_status` + `_match_signal_to_item` 覆盖
- 状态归一化 (confirmed / rejected / pending / unknown)
- 信号匹配评分逻辑 (路径 +2 / 关键词 / 类型亲和)
- confidence 上限 / stop word 过滤
- 新增测试 13 条

### 第 12 轮 — `security.sanitize_unicode` 覆盖
- 零宽空格 / ZWNJ / LRM / BOM 等 Cf 字符移除
- NFKC 全角转半角
- 非 str 透传 / emoji 保留
- 新增测试 12 条

### 第 13 轮 — `context_manager` autocompact 熔断器 + token 估算
- `estimate_tokens_rough` / `estimate_messages_tokens` 及其 4/3 安全系数
- `AutocompactManager.should_compact` 阈值 + 熔断器
- compact 成功重置失败计数 / 失败递增 / 空摘要等价失败
- 序列化 tool_use/tool_result/text block + 长消息截断
- 新增测试 22 条

## 三、真实发现的 3 个 runtime bug

### Bug 1: `GOSHAWK_TIMEOUT` 只在 `config/dev.py` 定义
**症状**: Session 2 jsonl 里 `final_reviewer_done: cannot import name 'GOSHAWK_TIMEOUT'` — 苍鹰跨校验整块崩溃,13 条 items 没终审直接流入下游
**根因**: `config/prod.py` 和 `config/test.py` 只 `from config.base import *`,base.py 里没定义
**修复**: 搬 `GOSHAWK_TIMEOUT=300` 到 `config/base.py` + `agent_config.py` re-export 列表加上
**防御**: 新增 AST 扫描型跨 env 回归测,未来类似遗漏会立即 CI 红

### Bug 2: Worker / 苍鹰空提交静默接受
**症状**: data_quality/quality worker 50% 静默率 (真实数据),其实是 model 调了 tool 但 items=[]
**根因**: 原代码只在 `not _has_tool_use(response)` 时 retry,空提交走不到 retry 分支
**修复**: 新增 `_is_empty_tool_submission` / `_is_empty_advisor_submission` + empty-retry 分支
**配套**: retry prompt 要求 model 要么补齐遗漏,要么显式提交 "已检查无问题" 说明,避免幻觉
**观测**: telemetry 加 `empty_retry_used`,STATUS 里新增 "空提交重试分支" 章节等数据

### Bug 3: `eval_history.json` 非原子写 + scores key 硬依赖
**症状**: scores 形状降级时 `append_eval_history` KeyError,或写 I/O 中断导致 history 文件损坏
**根因**: 直接 `open(...)` + `json.dump`,且代码假设 scores 必带 detail.total_bugs 等字段
**修复**: `_safe_get(scores, key)` 容忍缺失 / 非数值,`_atomic_write_json` 走 .tmp + rename
**效果**: 即使 cuckoo_scorer 未来返回降级 shape,eval_history 不会崩也不会被污染

## 四、STATUS.md 进化

### 前 (1 个混淆指标)
```
一致性基线: 40.0%
```
把 quota 耗尽和真 bug 混在一起算,误导整个团队的优化方向。

### 后 (10+ 分层指标)
```
Session 分类:
  productive=1, partial_silent=1, empty_bug=0, quota_exhausted=3

有效一致性 (productive / 非 quota): 50.0%
配额耗尽占比: 60.0% (ops 问题,非 bug)

Flow 完整性:
  完成率 40%, checkpoint 率 40%, 苍鹰失败率 100%

Worker 静默率:
  data_quality 50%, quality 50%, structure 0%, ai_coding 0%

错误指纹 (归一化聚合):
  count=2: cannot import name 'GOSHAWK_TIMEOUT' from ...

苍鹰 verdict 分布 [待新 session 产生数据]
空提交重试分支 [pending] [待新 session 产生数据]
```

## 五、新增模块清单

| 模块 | 职责 | 行数 | 备注 |
|------|------|------|------|
| `interactive_io.py` | 非交互 I/O helper | 33 | 第 0 波抽出 |
| `content_loader.py` | PRD/Wiki 加载 + sanitize_branch_name + wiki_pull | 73 | 第 0 波 |
| `router.py` | 意图路由 + system blocks | 73 | 第 0 波 |
| `tool_runtime.py` | tool_loop 核心循环 + 并发分发 | 195 | 第 1 波 |
| `session_setup.py` | CLI parser / merge 模式 / resume 策略 | 159 | 第 1 波 |
| `scripts/generate_status.py` | 自动 STATUS 生成(13 轮持续演化) | ~400 | 第 0 波 → Round 8 |
| `scripts/shadow_run.py` | 批量跑 50 次 run_session 采集一致性 | 239 | 第 0 波 |

## 六、没解决的事(非代码问题)

1. **shadow run 50 次实数据**
   - `scripts/shadow_run.py --workspace workspace-对外投资 --runs 50 --fail-under 0.6`
   - 需要真机 Claude CLI + 配额,CI 做不了
   - 跑完后 STATUS 会自动填入 empty_retry 和 goshawk verdict 真实统计

2. **quota 60% 耗尽** 是 ops 时段问题
   - 目前 STATUS 里已经分离它不计入 bug 指标
   - 解决方案属于运维:调整运行时段 / 多账号轮询,和代码无关

3. **若干 low-ROI 模块尚无单测覆盖**
   - `wiki_consolidation.py` / `kakapo_dream.py` / `cache_monitor.py` / `event_store.py`
   - ROI 偏低,本轮未动;下次如出现 bug 可按"看 jsonl → grep 异常 → 加测"套路定向补

## 七、工程方法论沉淀

本次迭代产出的可复用模式,已写入 memory:

1. **看真实数据 > 猜**: STATUS.md 和 session jsonl 才是真相源
2. **分层聚合 > 单一指标**: 把 ops 噪声 (quota) 和代码 bug 分开算,才能看到真问题
3. **fingerprint 聚合 > 前 N 条错误列表**: 归一化后 count=2 的错误直接暴露,比 raw list 更易发现
4. **空提交 = 半沉默**: LLM tool_choice=any 强制调 tool 但 items=[] 是常见 failure mode,需要专门检测 + retry
5. **跨 env 常量漂移**: `from base import *` 让"某 env 缺符号"类 bug 到 runtime 才暴露,需 AST 扫描防御
6. **原子写 + 容错读**: 所有"历史/状态"类 JSON 都该 .tmp + rename,所有字段读取都该 `.get(k, default)`
7. **telemetry 先加,数据后有**: 即使还没真实数据,先把 field 和聚合代码准备好,新 session 产生即可用

## 八、本轮所有 memory 条目

- `pecker_p0_p1_first_wave_2026_04_16.md` — 3 波重构 (interactive_io / content_loader / router / tool_runtime / session_setup)
- `pecker_session_classification_and_goshawk_bug.md` — 分类框架 + GOSHAWK bug
- `pecker_empty_submission_retry_landed.md` — worker 空提交重试
- (未来若有 shadow run 数据,追加一条真实一致性基线)

---

**pytest 143 → 416 (全绿),13 轮迭代,3 个 runtime bug 修复,0 回归,0 用户干预。**
