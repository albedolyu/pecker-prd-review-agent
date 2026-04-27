# Baseline Matrix

- 生成时间: 2026-04-27 17:31:33
- 路由数: 2

## 5 维度全表

| route_id | vendor | model | task | 主指标 | n | Overlap | p95 ms | $/run | quota% |
|---|---|---|---|---|---|---|---|---|---|
| verify.nli | anthropic | haiku | binary | acc=0.500 TPR=0.000 FPR=0.000 | 60 | 1.000 | 853 | 0.000000 | 0.000 |
| router.intent | anthropic | haiku | multiclass | acc=0.250 (opus:0.00/sonnet:1.00/haiku:0.00/reject:0.00) | 60 | 1.000 | 775462 | 0.006300 | 0.000 |

## 说明

- 此表作为后续准入对比的参照基线 (scripts/eval_admission.py --compare)
- task=issues 主指标 P/R/F1 (cuckoo); task=binary 主指标 accuracy/TPR/FPR;
  task=multiclass 主指标 accuracy + per-class accuracy
- 准入阈值: F1>=base-0.05, Recall>=base-0.05, Overlap>=base-0.05,
  p95<=base*1.5, $/run<=base*2.0; halluc TPR>=0.85, FPR<=0.10 (绝对)
