"""route_eval -- 多模型路由准入门槛 + 回归评测框架.

5 维度评测 (capability/stability/cross_vendor/cost_latency/failure_modes)
+ 阈值判定 (admission) + md/json 报告生成 (report).

调用约定:
    from eval.route_eval import runner, metrics, admission, cross_vendor, report

    res = runner.run_route_eval(
        route_id="advisor.goshawk",
        vendor="anthropic", model="sonnet",
        runs=3, dataset_name="advisor_conflicts",
        dry_run=True,
    )
    cap = metrics.compute_capability(res["responses"], res["ground_truth"])
    decision = admission.admit(cap, baseline_cap, route_id="advisor.goshawk")

详细 plan 见 ``C:\\Users\\20834\\.claude\\plans\\tranquil-snacking-harbor.md``
的"评测体系（多模型准入门槛）"章节。
"""

from . import admission, cross_vendor, datasets, metrics, report, runner

__all__ = ["admission", "cross_vendor", "datasets", "metrics", "report", "runner"]
