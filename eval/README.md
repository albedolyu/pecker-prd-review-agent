# eval/ -- 啄木鸟评审质量评测套件

## 目录结构

```
eval/
  test_cases/           # 预埋 bug 测试用例 (JSON)
    劳动仲裁_planted.json
    产品召回_planted.json
    侵权软件_planted.json
    对外投资_planted.json
    纳税人资质_planted.json
  results/              # 评测结果输出目录 (git-ignored)
  consistency_eval.py   # 一致性评测: 同一 PRD 跑 N 次,计算 overlap rate
  consistency_analyzer.py # 一致性分析: 读 results/ 的多次结果,统计规则检出频率
```

## 快速开始

### 1. CI Eval Gate (纯计算,不跑 LLM)

```bash
pytest tests/test_eval_gate.py -m eval -v
```

用固定 fixture 验证 scorer 逻辑的稳定性 (recall/precision/overall_score 满足阈值)。

### 1.1 右下角小助手 Golden Eval (纯计算,不跑 LLM)

```bash
npm.cmd --prefix web test -- tests/review-assistant-golden-eval.test.ts
python -m pytest tests/test_review_assistant_golden_eval.py -q
```

用 `eval/golden/review_assistant_customer_needs.json` 验证小助手是否满足 PM 试用需求:
上传材料说明、采纳/驳回/改写、报告导出、524 超时恢复、风鸟知识库查询、原始事实层查询,以及普通 PRD 问题不误触发查库。

### 1.2 小助手完整评测体系 (参考 Claw-Eval-Live)

```bash
python -m eval.assistant_eval_system --project-root . --days 30
python -m pytest tests/test_assistant_eval_system.py -q
```

体系分四层:

- 信号层: 读取 `logs/user_actions_*.jsonl`、`logs/missing_feedback.jsonl`、`eval/results/*` 和 golden cases,统计真实使用/反馈信号。
- 任务族: `workflow_help`、`failure_recovery`、`evidence_lookup`、`fact_layer_lookup`、`negative_boundary`。
- 评分层: `route_correctness` 25%、`answer_utility` 35%、`evidence_grounding` 25%、`safety_boundary` 15%。
- 稳定性层: 预留 `Pass^k` 评测,同一问题多次运行时要求路由稳定且每轮达标。

输出写入 `eval/results/assistant_eval_*.json` 和 `.md`。这些是本地运行产物,默认不入库。

### 1.3 事实层黄金样本生成

```bash
python -m eval.fact_layer_golden --output eval/golden/fact_layer_ground_truth_samples.json
python -m pytest tests/test_fact_layer_golden.py -q
```

`eval/golden/fact_layer_ground_truth_samples.json` 从现有人工标注/PM 确认材料和当前事实层资料生成:

- `active`: 可进入事实层准确率统计。来源包括 PM 已标注的 planted bugs,`eval/ground_truth/*.json` 中 `action=accept/edit`、`is_true_positive=true` 且带 `note` 的 PM 决策,以及风鸟 Wiki/后端源码/前端源码中可定位到路径、行号和关键词的 `source_verified` 样本。
- `candidate`: 只进入补标队列。来源是 `business_prd_gt` 里 manifest 明确写着待 PM 后续标注的 `inline_minimal` 样本。
- 不纳入: 只有真假但没有 `issue/note` 的 PM 决策、`advisor_conflicts` 中 `is_placeholder=true` 的冲突调解样本。

默认事实来源是本机风鸟 Wiki、RiskBirdApi 后端源码、riskbird-mobile-vue3 前端源码。也可以用 `PECKER_FACT_SOURCE_ROOTS="wiki=C:\path\wiki;backend=C:\path\api"` 指定替代来源。事实层样本统一要求 `include_fact_layer=true`,并保留 `expected_sources`、`standard_answer`、`must_include` 字段,用于后续计算 Recall@5、Precision@5、证据引用准确率和层级混淆率。

### 2. 端到端评测 (需要 Claude API)

```bash
# 单次评测
python cuckoo_eval.py workspace/prd/劳动仲裁需求文档-v4.11.md \
  --test-case eval/test_cases/劳动仲裁_planted.json

# 一致性评测 (同一 PRD 跑 3 次)
python eval/consistency_eval.py workspace/prd/劳动仲裁需求文档-v4.11.md --runs 3
```

### 3. 一致性分析 (离线,读已有结果)

```bash
python -m eval.consistency_analyzer --results-dir eval/results/ --test-case 劳动仲裁
```

## 生成新测试用例

测试用例是 JSON 文件,包含 `planted_bugs` 和 `non_issues` 两个数组。

### 步骤

1. 准备一份真实 PRD (.md)
2. 人工审阅 PRD,识别 6-10 个真实问题作为 `planted_bugs`
3. 识别 2-3 个容易被误报的正常内容作为 `non_issues`
4. 按以下 schema 编写 JSON:

```json
{
  "name": "PRD名称 预埋 bug 端到端测试",
  "prd_file": "workspace-xxx/prd/xxx.md",
  "generated_at": "2026-01-01 10:00",
  "description": "描述测试用例覆盖范围",
  "planted_bugs": [
    {
      "id": "BUG-001",
      "location": "章节号,如 3.7",
      "type": "笔误|不一致|歧义|缺失|字段类型",
      "severity": "must|should",
      "description": "问题描述,包含足够细节让 matcher 能匹配",
      "keywords": ["关键词1", "关键词2", "用于模糊匹配"]
    }
  ],
  "non_issues": [
    {
      "location": "章节号",
      "reason": "为什么这不是问题 (误报陷阱)"
    }
  ]
}
```

### 关键原则

- `planted_bugs` 数量建议 6-10 个,覆盖 must 和 should 两种严重度
- `non_issues` 数量建议 2-3 个,用于检测精确率 (误报率)
- `keywords` 用于 matcher 的模糊匹配,每个 bug 至少 3 个关键词
- `location` 与 PRD 章节号对应,matcher 会用 location 做位置相似度匹配

## 评测指标

| 指标 | 含义 | CI 阈值 |
|------|------|---------|
| recall | 预埋 bug 被检出的比例 | >= 0.3 |
| precision | 检出项中真正命中预埋 bug 的比例 | >= 0.2 |
| overall_score | recall * 0.5 + precision * 0.3 + evidence_reliability * 0.2 | >= 0.25 |

阈值可在 `config.py` 中通过 `EVAL_MIN_*` 变量调整。
