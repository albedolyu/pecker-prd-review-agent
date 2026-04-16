# rule_performance_history 污染清洗方案

> 背景: `STABILITY_DIAGNOSIS.md` 发现 CLI 配额耗尽 bug 导致 0-items 伪评审。这些 session 里用户只能 reject 空 items 或放弃,会污染 rule_performance_history 的 rejection_rate 和 is_noisy 标签,反哺 Worker prompt 时给 Worker 错误信号。
> 数据: 2026-04-16 分析 `workspace-对外投资/output/rule_performance_history.json` 15 条规则

---

## 一、污染识别逻辑

用以下启发式分类每条规则的 history:

| 判断 | 条件 | 含义 |
|---|---|---|
| `CONTAMINATED(0C all-R)` | confirmed=0 且 rejected>0 且 total<10 | 所有样本都是 reject,无任何 accept。**很可能是 0-items 伪评审时代的 rejection 堆积**，真实效果未知 |
| `LIKELY CONTAMINATED` | confirmed=0 且 rejected ≥ 4 | 同上但 reject 更多,更可疑 |
| `TRUE NOISE` | is_noisy=True 且 confirmed>0 | 有真实 accept 历史仍被标 noisy,是真噪声规则 |
| `EFFECTIVE` | confirmed>rejected 或 is_noisy=False 且有 confirmed | 明确有效 |
| `? miss-heavy` | missed>confirmed 且 missed>3 | 漏报主导,可能规则定义问题 |
| `?` | total=0 | 从未被触发,存在性存疑 |

## 二、workspace-对外投资 具体诊断

| rule_id | total | conf | rej | miss | rate | noisy | 分类 | 建议 |
|---|---|---|---|---|---|---|---|---|
| RC-004 | 2 | 0 | 2 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |
| RC-008 | 2 | 1 | 1 | 0 | 0.50 | True | TRUE NOISE | 保留 |
| RC-009 | 4 | 0 | 4 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |
| RC-010 | 4 | 4 | 0 | 0 | 0.00 | False | EFFECTIVE | 保留（唯一全 accept 规则） |
| RC-013 | 6 | 0 | 6 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |
| RC-014 | 15 | 5 | 0 | 10 | 0.00 | False | miss-heavy | 人工 review 漏报模式 |
| RC-015 | 4 | 2 | 0 | 2 | 0.00 | False | EFFECTIVE | 保留 |
| V-03 | 1 | 0 | 1 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |
| V-04 | 1 | 0 | 1 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |
| V-05 | 6 | 2 | 4 | 0 | 0.67 | True | TRUE NOISE | 保留（可调整权重） |
| V-06 | 0 | 0 | 0 | 0 | 0.00 | False | ? | **核对规则是否已实装** |
| V-07 | 10 | 0 | 6 | 4 | 0.60 | True | LIKELY CONTAMINATED | **reset stats** |
| V-08 | 4 | 1 | 3 | 0 | 0.75 | True | TRUE NOISE | 保留 |
| V-09 | 6 | 2 | 3 | 1 | 0.50 | True | TRUE NOISE | 保留 |
| V-10 | 2 | 0 | 2 | 0 | 1.00 | True | CONTAMINATED | **reset stats** |

### 统计摘要

- 7/15 (47%) 规则疑似污染 → 建议 reset
- 6/15 (40%) 规则保留
- 1/15 RC-014 漏报密集需要人工审
- 1/15 V-06 未触发,核对实装状态

## 三、清洗脚本规格（未实施）

建议写一个 `scripts/cleanup_rule_perf.py`,具备以下能力:

```
功能:
- 输入: workspace 路径 + 可选 dry-run 标志
- 扫描 output/rule_performance_history.json
- 按本文档的"污染识别逻辑"分类每条规则
- 对 CONTAMINATED / LIKELY CONTAMINATED 的规则:
  - 保留 name 字段
  - 把 stats 清零
  - history 字段保留但加标记 contaminated=true, reason="quota bug era"
  - impact_score 重置为 0.5（中性）
  - is_noisy 重置为 False
- 备份原文件到 rule_performance_history.json.bak_{timestamp}
- 输出清洗报告到 stdout

用法:
  python -m scripts.cleanup_rule_perf --workspace workspace-对外投资 --dry-run
  python -m scripts.cleanup_rule_perf --workspace workspace-对外投资 --confirm
```

## 四、为何不能自动清洗（必须人工确认）

- 启发式可能误杀: 某些规则确实很差,也会出现"0 confirmed all rejected"
- 建议清洗 + 人工抽检: dry-run 输出后,PM 看一眼分类结果,确认污染范围再 --confirm
- 同时, 配额 bug 修复前清洗无意义,会再被污染。**必须按顺序做**:
  1. 先修 3 个 P0 漏洞 (STABILITY_DIAGNOSIS 补丁 1-3)
  2. 再接通 audit log (漏洞 C)
  3. 最后清洗 rule_perf_history

## 五、长期机制（防止再污染）

修复配额 bug 后建议加 3 层防污染机制:

1. **快照 + rollback**: 每次 Web 决策写入 history 前,备份当前 history 到 `.bak`,允许管理员 rollback
2. **明显异常的决策不回流**: 如果一次 confirm 里 `reject_count / total > 0.9`,怀疑用户是在伪绿色报告上 reject all,**延迟写入**,需要下次同 workspace 评审时再验证
3. **衰减窗口**: EMA 只考虑近 90 天的决策,避免一次糟糕数据永久影响规则

## 六、清洗后预期

- 7 条规则的 is_noisy 从 True 变回 False,Worker prompt 不再收到"这些规则被频繁驳回"的错误信号
- impact_score 恢复中性 0.5,下一轮评审时这些规则能正常被 Worker 使用
- 经过 10-20 次有效评审后,EMA 会收敛到真实的 impact_score
- Worker 的 prompt 注入会变得更准确,进一步提升 consistency
