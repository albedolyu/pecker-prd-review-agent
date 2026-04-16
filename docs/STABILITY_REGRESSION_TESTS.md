# 稳定性回归测试方案

> 目的：确保 `docs/STABILITY_DIAGNOSIS.md` 里的 3 个 P0 漏洞（A/B/C）不再复发
> 依赖：已有 `tests/test_eval_gate.py` 的 pytest 框架

---

## 一、测试矩阵

每个漏洞对应 1-2 个针对性 test，放在 `tests/test_worker_failure_handling.py`（新文件）。

### Test 1 — 全员失败应该发 `review_failed`（漏洞 A）

```python
@pytest.mark.asyncio
async def test_all_workers_failed_emits_review_failed():
    """4 个 worker 全 error 时,SSE 发 review_failed 而不是 review_completed"""
    from api.routes.review import _run_review_core  # 或其他注入点
    # Mock parallel_review 让 4 个 worker 全报错
    mock_result = {
        "workers": [
            {"dim_key": "structure", "error": "claude -p 退出码 1: hit your limit"},
            {"dim_key": "quality", "error": "claude -p 退出码 1: hit your limit"},
            {"dim_key": "ai_coding", "error": "claude -p 退出码 1: hit your limit"},
            {"dim_key": "data_quality", "error": "claude -p 退出码 1: hit your limit"},
        ],
        "merged_items": [],
    }
    events_received = []

    # 跑一次 review,收集 SSE 事件
    # ... (具体 mock 手法按现有 test_api_auth 类似套路)

    # 断言
    event_types = [e["event"] for e in events_received]
    assert "review_failed" in event_types, "全员失败应发 review_failed"
    assert "review_completed" not in event_types, "全员失败不应发 review_completed"
```

### Test 2 — 部分 worker 失败 + items 空应该发 `review_degraded`（漏洞 A）

```python
@pytest.mark.asyncio
async def test_partial_failure_empty_items_emits_degraded():
    """部分 worker 失败且 merged_items 为空时,SSE 发 review_degraded"""
    mock_result = {
        "workers": [
            {"dim_key": "structure", "items": []},  # 无错无 items
            {"dim_key": "quality", "error": "..."},
            {"dim_key": "ai_coding", "items": []},
            {"dim_key": "data_quality", "items": []},
        ],
        "merged_items": [],
    }
    # 预期 review_degraded 而不是 review_completed
```

### Test 3 — CLI JSON 解析失败应抛错（漏洞 B）

```python
def test_cli_json_parse_failure_raises():
    """api_adapter 的 JSON 解析失败路径不应静默返回空壳,应抛 APIError"""
    from api_adapter import CCClient
    from exceptions import APIError
    client = CCClient()

    # Monkey-patch subprocess 返回 non-JSON 文本
    # 或直接 mock _parse_json_from_text 返回 None
    with pytest.raises(APIError, match="JSON parse failed"):
        client.call(..., structured_tool={"name": "submit_review_items", ...})
```

### Test 4 — 配额错误应抛 QuotaExhaustedError（漏洞 A 用户体验）

```python
def test_quota_exhausted_error_distinguished():
    """CLI 返回 'hit your limit' 错误时,抛 QuotaExhaustedError 而不是 generic APIError"""
    from api_adapter import CCClient
    from exceptions import QuotaExhaustedError  # 新类型

    # Mock subprocess 返回 returncode=1 + stderr="hit your limit"
    with pytest.raises(QuotaExhaustedError):
        client.call(...)
```

### Test 5 — user_actions.jsonl 字段规范（漏洞 C）

```python
def test_audit_log_schema():
    """真实用户 action 事件应有固定字段 schema,不能是 action='?'"""
    import json
    from pathlib import Path
    p = Path("logs/user_actions.jsonl")
    if not p.exists():
        pytest.skip("No audit log yet")
    lines = p.read_text(encoding="utf-8").splitlines()
    real_events = [json.loads(l) for l in lines if l.strip()
                    if json.loads(l).get("event") not in ("test_event", "smoke_test", "test")]
    if not real_events:
        pytest.skip("Only test events present")
    for e in real_events:
        # 新 schema 约束
        assert "action" in e, f"缺 action 字段: {e}"
        assert e["action"] in ("accept", "reject", "edit", "save_to_wiki", "push_feishu", "download"), \
            f"非法 action: {e['action']}"
```

---

## 二、集成测试:一致性回归

### Test 6 — 修复后劳动仲裁一致性分应 ≥ 50%

```python
@pytest.mark.eval
@pytest.mark.slow  # 真跑 LLM,标记 slow
def test_consistency_improvement_after_fix():
    """配额重置后,跑 3 次同一 PRD,一致性分应 >= 50%(原 17%)"""
    from cuckoo_eval import run_consistency
    results = run_consistency(
        prd_path="workspace-劳动仲裁/prd/劳动仲裁需求文档-v4.11.md",
        rounds=3,
    )
    assert results["consistency_score"] >= 0.50, \
        f"一致性 {results['consistency_score']*100:.0f}% 低于 50% 阈值"
    # 同时断言 zero-items runs 应该 < 10%
    zero_runs = sum(1 for r in results["items_per_run"] if r == 0)
    assert zero_runs <= 1, f"3 次 run 中有 {zero_runs} 次返回 0 items"
```

---

## 三、CI 集成

在 `.github/workflows/eval.yml` 追加一个 job:

```yaml
  stability_gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: pip install -r requirements.txt && pip install ".[dev]"
      - name: Run stability gate
        run: python -m pytest tests/test_worker_failure_handling.py -v
```

一致性回归 test 因为需要真实 LLM 调用,不进 CI,用 `pytest -m "eval and slow"` 手动跑。

---

## 四、验收 checklist

修复合并前用下列 checklist 验证:

- [ ] Test 1-4 全部 pass（`pytest tests/test_worker_failure_handling.py`）
- [ ] Test 5 至少不 fail（audit log 修复后转为 pass）
- [ ] 手动配额耗尽场景：4 个 worker 全 error 时,UI 显示"评审失败"面板而非自动跳 Phase 3
- [ ] 手动 quota 重置后：跑 3 次劳动仲裁 consistency,整体一致性分 ≥ 50%,0-items run 占比 ≤ 10%
- [ ] workspace-对外投资 的 `rule_performance_history.json` 清洗后,被误标 noisy 的规则（V-07/RC-013/RC-009）impact_score 有正常值

---

## 五、监控（修复后的长期观测）

加一段监控脚本 `scripts/stability_daily.py`（可接入 cron）:

```python
# 每天统计:
# 1. 过去 24h 的 worker_done 事件 zero-items 占比
# 2. quota_exhausted error 次数
# 3. review_failed / review_completed 比例
# 超过阈值时写入 logs/stability_alert.log,可接飞书推送

THRESHOLDS = {
    "zero_rate": 0.1,        # zero-items 占比 > 10% 告警
    "quota_daily": 5,        # 单日配额错误 > 5 次告警
    "failed_ratio": 0.15,    # review_failed / total > 15% 告警
}
```
