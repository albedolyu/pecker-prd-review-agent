# 啄木鸟稳定性诊断报告

> 诊断日期: 2026-04-16
> 诊断范围: `eval/results/` 下 8 次劳动仲裁 consistency 评测（共 22 个 run）+ `workspace-对外投资/output/sessions/` 5 个 event_store session（20 个 worker_done events）
> 工具: `eval/consistency_analyzer.py` + 自定义 JSON 解析
> **核心结论**: CLI 配额耗尽被 `_empty_tool_fallback` 静默吞掉,当成"评审完成无问题"报给用户。这是 P0 紧急 bug,修复后 consistency 问题大部分会自然解决。

---

## 一、核心发现

**同一 PRD 的 22 次评测呈现严重漂移：**

| 指标 | 数值 | 判断 |
|---|---|---|
| 整体一致性分 | **17%** | 评级 D（不一致） |
| 稳定规则（≥75% 命中） | **0 条** | 没有任何规则被稳定检出 |
| 中间态规则（50-75%） | 2 条（RC-010=64%, RC-009=50%） | 只有数据质量维度有稍稳定信号 |
| 不稳定规则（<50%） | 10 条 | 大部分发现是"碰运气"级别 |
| 每次 run items 数：min/max/avg | 0 / 8 / 3.8 | **变异系数 2.12** |
| **零 items run 占比** | **4/22 = 18%** | 18% 的评审完全空手而归 |

## 二、维度返回模式（关键症状）

逐个 run 拆开看 items 的维度归属,发现**每次 run 常常只有 1 个维度返回非零**,其他 3 个 worker 完全静默:

| session | items_per_run | 返回非零维度 |
|---|---|---|
| 1359 | [4, 6, 8] | 数据质量×2、数据质量+质量层 |
| 1412 | [2, 4, 4] | 数据质量、结构层+数据质量×2 |
| 1419 | [4, 2, 0] | 结构层+数据质量、数据质量、**全空** |
| 1433 | [4, 4, 2] | 结构层+数据质量×2、数据质量 |
| 1451 | [0, 0, 8] | **全空×2**、数据质量 |
| 1501 | [4, 0, 3] | 数据质量、**全空**、数据质量 |
| 1527 | [4, 8, 6] | 数据质量、AI Coding、数据质量 |
| 1549 | [6] | 数据质量 |

**观察**:
- **数据质量（鸬鹚）出现最频繁**,且总是被当作唯一出声的维度
- **结构层（织布鸟）** 在 8 次 session 中只出现 3 次
- **质量层（猫头鹰）** 在 8 次 session 中只出现 1 次
- **AI Coding（渡鸦）** 在 8 次 session 中只出现 1 次
- **苍鹰补充项** 无独立维度标记,无法从 raw 判断是否有出声

**结论**: 不是"系统太严",是 **3/4 的 worker 经常直接返回空**,且是哪个 worker 静默完全随机。

## ⚡ 2.6 Round 2 精确化：漏洞在汇总层不在 per-worker 层

继续挖后发现问题比想象的更细致，**per-worker 错误上报链路其实是对的**:

- `api_adapter.py:558-560`: CLI 配额耗尽 → `returncode != 0` → raise `APIError`
- `parallel_review._run_worker_async:1153`: catch 后回调 `{"error": str(e)[:200]}`
- `api/stream.py:95`: `success = "error" not in result`，错误时设 False
- `api/stream.py:100`: error 字段透传到 SSE payload
- `Phase2Running.tsx:144-145`: `if (!ev.success) → state = "error"`，UI 正确显示红卡

**真正的漏洞在这 3 个位置**:

### 漏洞 A — 缺"全员失败则 abort"规则（最严重）

`api/routes/review.py` Phase 2 完成后:
- 即使 `result.workers` 里 4 个全 error,`merged_items=[]` 时仍发 `review_completed`
- `Phase2Running.tsx:111-114` 收到 `done` → toast "评审完成" + 自动跳 Phase 3
- 用户流程: 4 张红卡闪过 → 自动跳转 → Phase 3 显示 "0 条待确认" → 容易被当作"评审干净没问题"

### 漏洞 B — JSON 解析失败静默返回空壳（api_adapter.py:594）

```python
if parsed is None:
    log.warning(f"[cc_client] tool={...} JSON 解析失败，返回空壳")
    # 返回空 tool_use 块，上游当成功处理
```

这是真正的"静默吞"路径,和配额错误是两回事:
- 配额错误走 APIError,UI 能看到
- JSON 解析失败走空壳,UI 看不到错误

### 漏洞 C — user_actions.jsonl 基本废掉

只有 4 条测试事件 (`test_event`, `smoke_test` 等),**无真实用户行为数据**。审计日志接通状态存疑,后续反馈分析完全没数据源。

**Round 4 根因（2026-04-16）**: 完整链路核对结果:
- 后端 `api/routes/audit.py:28 POST /api/audit` 路由正常 ✅
- 前端 `web/lib/api.ts:363 auditApi.log()` API 方法定义正常 ✅
- **但前端 `web/` 里任何组件都没调用 `auditApi.log`！** `grep -r 'auditApi\.log' web/` 返回 0 结果
- TopBanner 调了 `auditApi.todayCount`（读），但写侧从未触发

**修复方案（漏洞 C 的具体 patch 点）**:
1. `web/components/phases/Phase0Upload.tsx` 上传 PRD 后 → `auditApi.log({event: "review_started", workspace, prd_name})`
2. `web/components/phases/Phase3Confirm.tsx` confirm 后 → `auditApi.log({event: "review_confirmed", workspace, prd_name, extra: {accepted, rejected, edited}})`
3. `web/components/phases/Phase4Report.tsx` 三出口分别调：`saved_to_wiki` / `pushed_feishu` / `downloaded_report`
4. 可选：登录成功在 `web/app/login/page.tsx` 调 `logged_in` 事件
5. Phase 3 每条 accept/reject/edit 不建议上报（单条噪声太多），在 confirm 时批量上报

## ⚡ 2.5 从 event_store 找到 smoking gun（2026-04-16 update）

继续挖 `workspace-对外投资/output/sessions/` 的 5 个 session JSONL(20 个 worker_done events):

| 维度 | 样本数 | min | max | avg | zeros 率 |
|---|---|---|---|---|---|
| ai_coding | 5 | 0 | 6 | 2.4 | 3/5 (60%) |
| data_quality | 5 | 0 | 1 | 0.2 | 4/5 (80%) |
| quality | 5 | 0 | 2 | 0.4 | 4/5 (80%) |
| structure | 5 | 0 | 9 | 3.2 | 3/5 (60%) |
| **总计** | **20** | | | | **14/20 (70%)** |

**70% 的 worker_done 是 0 items!** 20 个 events 中 12 个带 `error` 字段,内容全部是:

```
claude -p 退出码 1: You've hit your limit — resets 8am (America/Los_Angeles)
```

**结论(根因候选 1 已验证)**: `_empty_tool_fallback` 把 CLI 配额耗尽错误当成"正常完成 0 items"返回给用户。

**证据**:
- event_store 确实忠实记录了 `error` 字段(不是这里 bug)
- 但上游 `on_worker_done` 回调 + `merged_items` 合并时,error 情况仍被当作成功路径
- 用户看到的最终报告没有"4 个 worker 全因配额失败"的警告,只是"本次评审 0 items"

**影响**:
- 在 04-16 早晨这波请求中,**100% 的用户评审请求实际是失败的**,但用户看到的是"无问题"的绿色报告
- 下游 AI Coding 基于"无问题" PRD 开工,**所有后续返工都是这个 bug 的下游成本**

**这也反向解释了劳动仲裁 04-13 的 17% 一致性问题**:
- 当时应该也有部分 worker 因为网络/CLI 临时失败返回空
- 静默吞掉后,有些 run 全 4 worker 失败 → 0 items (18% 的占比吻合)
- 漂移的随机性就是"哪些 worker 刚好在那一刻失败"的随机性

---

## 三、可能根因（按可能性排序）

### 根因候选 1 — Worker 隐性失败被空壳兜底吞掉（可能性: 高）

**证据链**:
- `parallel_review.py:_empty_tool_fallback` 在解析失败时返回空 items 列表
- Worker 的完整链路是: 构造 prompt → Claude API → 尝试 tool_use → 失败转 maxTurns 重试 → 耗尽转文本兜底解析 → 兜底失败返回空
- 整条链路静默吃异常,log 层面看不出差异

**排查方向**:
- 在 `_worker_core` 最后一次兜底前 log.warning 记录链路走到了第几层
- `event_store.py` 应该能看到每个 worker 的 event,统计 `empty_tool_fallback` 命中次数
- 对照 8 次 consistency 的时间戳,拉对应的 `logs/劳动仲裁.log` 看是否有"解析失败"

### 根因候选 2 — Stagger 0.3s 引入瞬时 API 限流（可能性: 中）

**证据链**:
- commit `be5fead` 加了 stagger 0.3s 错峰,但 4 worker 在 1.2 秒内全部发起
- CLI 模式下 Claude Code 本身串行队列,4 个并发请求可能在 CLI 层排队
- 排队超时的 worker 转 maxTurns → 空壳

**排查方向**:
- 增大 stagger 到 1-2 秒重测 consistency,看 max 是否上升
- 如果根因是此,修复方向是 semaphore=1 串行执行（牺牲速度换稳定）

### 根因候选 3 — Tool schema 约束过紧 + CLI 后端 prompt 注入（可能性: 中）

**证据链**:
- CLI 后端没有原生 tool use,schema 是 prompt-based 注入
- `SUBMIT_REVIEW_ITEMS_TOOL` schema 较复杂（const 约束 + maxItems + evidence_type 枚举）
- 模型偶尔无法一次性构造合规 tool call

**排查方向**:
- 简化 schema 看 consistency 是否上升
- 或对 CLI 后端直接用 JSON mode 代替 tool 模式

### 根因候选 4 — Worker null_finding_reason 机制被滥用（可能性: 低）

**证据链**:
- `parallel_review.py` 允许 Worker 返回空 items + null_finding_reason
- 如果 Worker 在 prompt 理解上判断"本维度无问题",会主动交白卷
- 但劳动仲裁 PRD 已知至少有 5-6 个 bug,全 worker 都判"无问题"不合理

**排查方向**:
- 在 raw JSON 中搜索 `null_finding_reason` 字段看出现频率

### 根因候选 5 — Haiku sanity check 过度剪枝（可能性: 低）

**证据链**:
- Haiku sanity check 会删除被判误报的 items
- 但 22 个 run 中 18% 0 items,Haiku 再狠也不至于全剪光

## 四、修复顺序（Round 2 精确化后）

### P0 紧急 — 3 个漏洞对应的三条补丁（合计 0.8 天）

#### 补丁 1 — 在 orchestrator 加"全员失败 abort"规则（对应漏洞 A）

文件: `api/routes/review.py` Phase 2 完成后、返回 SSE `review_completed` 前

```python
# Phase 2 完成后
workers = result.get("workers", [])
failed_count = sum(1 for w in workers if w.get("error"))
total_count = len(workers)

if failed_count == total_count and total_count > 0:
    # 全员失败,发失败事件不发完成事件
    emitter.emit("review_failed", {
        "reason": "all_workers_failed",
        "message": f"全部 {total_count} 个 worker 失败,请重试",
        "worker_errors": [w.get("error", "") for w in workers],
    })
    return  # 不进入下面的 review_completed 路径

if failed_count > 0 and len(merged_items) == 0:
    # 部分失败且没拿到任何 items,提示用户
    emitter.emit("review_degraded", {
        "failed_workers": failed_count,
        "total_workers": total_count,
        "message": "部分 worker 失败,未获得评审项,建议重试",
    })
```

Web UI 侧 (`Phase2Running.tsx`): 监听 `review_failed` 事件 → 不自动跳 Phase 3,显示"评审失败"面板 + 重试按钮。

#### 补丁 2 — `api_adapter.py:594` JSON 解析失败改为抛错（对应漏洞 B）

当前 silent 返回空壳的行为替换为:

```python
if parsed is None:
    from exceptions import APIError
    log.error(f"[cc_client] tool={structured_tool['name']} JSON 解析失败, text_result 前 200 字: {text_result[:200]}")
    raise APIError(f"CLI JSON parse failed for tool {structured_tool['name']}")
```

这样上游能 catch 到失败,和配额错误走同一路径。

#### 补丁 3 — 识别 quota_exhausted 专用状态（对应漏洞 A 的用户体验）

`api_adapter.py:558-560` 的 APIError 分类:

```python
if proc.returncode != 0:
    err_text = (proc.stderr or proc.stdout)[:300]
    if "hit your limit" in err_text or "quota" in err_text.lower():
        raise QuotaExhaustedError(err_text)  # 新异常类型
    raise APIError(f"claude -p 退出码 {proc.returncode}: {err_text}")
```

UI 收到 `QuotaExhaustedError` 可以展示"配额已用完,明天 8am 重置"的友好提示,而不是 generic "评审失败"。

### P1 后续（合计 1.3 天）

| 优先级 | 动作 | 成本 |
|---|---|---|
| P1 | 修 `user_actions.jsonl` 审计链路 (漏洞 C) — 查 audit 路由为何只有 test 事件 | 0.3 天 |
| P1 | 记 `worker_failures_history.json` 累计各维度失败率 | 0.5 天 |
| P1 | 配额重置后重跑劳动仲裁 3 次 consistency,验证一致性分上升 | 0.3 天 |
| P1 | 清洗 `workspace-对外投资/output/rule_performance_history.json` 中 6 条 is_noisy=True 的规则(可能由 0-items 伪评审污染) | 0.2 天 |

### P2 精益求精（合计 1.2 天）

- B 类依据 embedding 缓存,减少 verify_evidence API 抖动 (1 天)
- consistency mode 下 temperature=0 + seed 固定 (0.2 天)

## 五、对 HARNESS_MATURITY 的影响

- "Eval 量化" 维度从乐观打的 7 分回调到 6 分
- 稳定性修复后有望直接上 7-8 分（不需要扩充测试用例就能先解决这个硬骨头）
- 修复顺序上，**稳定性优先于扩充测试用例**: 样本不稳定的前提下扩充用例只会放大噪声

## 六、对用户体验的影响（被埋没的风险）

18% 的 run 返回 0 items 意味着：
- 每 5 次评审有 1 次用户会看到"无问题"报告
- 用户可能据此认为 PRD 没问题直接进入 AI Coding 阶段
- 下游返工的隐性成本 = 这 18% × 平均返工成本

这个风险在**用户没有二次评审对照**时完全不可见。建议 Web UI 在结果为空时强制显示"warning: 本次评审 0 items,可能是系统偶发失败,建议重跑一次"。

---

## 附录：复现步骤

```bash
# 跑离线一致性分析（不需要 Claude API）
python -m eval.consistency_analyzer --results-dir eval/results/ --test-case 劳动仲裁

# 跑 raw JSON 的每-run 维度拆解
python << 'EOF'
import json, glob, os
for f in sorted(glob.glob('eval/results/*劳动仲裁*_raw.json')):
    with open(f, encoding='utf-8') as fh:
        data = json.load(fh)
    for i, run in enumerate(data.get('all_items', [])):
        dims = {}
        for it in run:
            d = it.get('dimension', '?')
            dims[d] = dims.get(d, 0) + 1
        print(f"{os.path.basename(f)[:30]}  run {i}: {len(run)} items, {dims}")
EOF
```
