"""
百灵测试 Agent - W2.4 评测打分 + 基线记录

评测维度(对齐快手智能单测 3.x 指标体系):
  1. 生成成功率(job_ok / total_jobs)   — V1.0 基线对齐: 3%
  2. parse 通过率(javalang 代编译)       — V2.0 对齐: 编译通过率 > 95%
  3. 平均每方法测试数                     — 对齐: 每 CUT 方法 2-3 个 case
  4. 场景覆盖率                           — normal/boundary/exception 三类均覆盖
  5. import 卫生度                        — 0 冲突、0 非法 static import
  6. 行覆盖率(占位)                      — 没 javac 暂无法测

基线记录到 workspace-风鸟-backend-test/output/baseline.json
可以多次运行覆盖,用于比较不同版本 agent 的表现

用法:
    python riskbird_test_eval.py --target-class AiRobotChatServiceImpl
    python riskbird_test_eval.py --eval-only  # 只评测已有产物,不重跑 agent
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import javalang

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("eval")


BASELINE_PATH = "workspace-风鸟-backend-test/output/baseline.json"


# ============================================================
# 静态评分
# ============================================================

def evaluate_test_file(file_path):
    """对单个生成的测试文件做静态评分

    Returns dict:
        parse_ok, test_method_count, method_names[], scenario_coverage{},
        import_count, import_conflicts, illegal_static_imports, loc
    """
    if not os.path.isfile(file_path):
        return {"error": f"file not found: {file_path}"}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    loc = len(content.split("\n"))

    # 1. javalang parse
    parse_ok = True
    parse_err = None
    try:
        tree = javalang.parse.parse(content)
    except javalang.parser.JavaSyntaxError as e:
        parse_ok = False
        parse_err = f"{e.description} @ {e.at}"
        tree = None
    except Exception as e:
        parse_ok = False
        parse_err = f"{type(e).__name__}: {e}"
        tree = None

    # 2. 抽取 @Test 方法名
    method_names = []
    if tree:
        try:
            for _, klass in tree.filter(javalang.tree.ClassDeclaration):
                for m in klass.methods:
                    ann_names = [a.name for a in (m.annotations or [])]
                    if "Test" in ann_names:
                        method_names.append(m.name)
        except Exception:
            pass
    else:
        # 降级: 正则抓
        method_names = re.findall(
            r"@Test\s*(?:\([^)]*\))?\s*public\s+void\s+(\w+)\s*\(",
            content,
        )

    # 3. 场景覆盖率 — 命名约定匹配
    scenario_coverage = {"normal": 0, "boundary": 0, "exception": 0, "unknown": 0}
    for name in method_names:
        low = name.lower()
        if "throw" in low or "fail" in low or "exception" in low or "error" in low:
            scenario_coverage["exception"] += 1
        elif "empty" in low or "null" in low or "boundary" in low or "zero" in low or "max" in low:
            scenario_coverage["boundary"] += 1
        elif "return" in low or "success" in low or "valid" in low or "correct" in low or "should" in low:
            scenario_coverage["normal"] += 1
        else:
            scenario_coverage["unknown"] += 1

    # 4. import 卫生度
    import_lines = [l.strip() for l in content.split("\n") if l.strip().startswith("import ")]
    import_count = len(import_lines)
    simple_names_non_static = []
    illegal_static = 0
    for line in import_lines:
        m = re.match(r"import\s+(static\s+)?([\w.]+?)(\.\*)?;", line)
        if not m:
            continue
        is_static = bool(m.group(1))
        fqn = m.group(2)
        is_wildcard = m.group(3) == ".*"
        last_seg = fqn.split(".")[-1]
        if is_static and not is_wildcard and last_seg and last_seg[0].isupper():
            # static import 只指向类名(无 member,无 .*) — 非法
            illegal_static += 1
        if not is_static and not is_wildcard:
            simple_names_non_static.append(last_seg)
    # 冲突: 同 simple name 出现多次
    from collections import Counter
    counter = Counter(simple_names_non_static)
    import_conflicts = sum(c - 1 for c in counter.values() if c > 1)

    return {
        "file": file_path.replace("\\", "/"),
        "parse_ok": parse_ok,
        "parse_error": parse_err,
        "test_method_count": len(method_names),
        "method_names_sample": method_names[:10],
        "scenario_coverage": scenario_coverage,
        "import_count": import_count,
        "import_conflicts": import_conflicts,
        "illegal_static_imports": illegal_static,
        "loc": loc,
    }


# ============================================================
# 综合评分
# ============================================================

def compute_overall_score(metrics):
    """综合评分 0-100,对齐单测进化指标

    权重:
      - parse_ok:          30
      - 方法数 >= 5:        15 (有实质内容)
      - 场景覆盖 3/3:        20 (normal/boundary/exception 都有)
      - 0 import 冲突:       15
      - 0 非法 static:       10
      - 平均每方法 2+ test:  10
    """
    if metrics.get("error"):
        return {"overall": 0, "verdict": "FAIL", "reason": metrics["error"]}

    score = 0
    breakdown = {}

    if metrics["parse_ok"]:
        score += 30
        breakdown["parse_ok"] = 30
    else:
        breakdown["parse_ok"] = 0

    if metrics["test_method_count"] >= 5:
        score += 15
        breakdown["has_methods"] = 15
    else:
        breakdown["has_methods"] = int(metrics["test_method_count"] / 5 * 15)
        score += breakdown["has_methods"]

    cov = metrics["scenario_coverage"]
    covered_scenarios = sum(1 for k in ("normal", "boundary", "exception") if cov[k] > 0)
    scen_score = int(covered_scenarios / 3 * 20)
    score += scen_score
    breakdown["scenario_coverage"] = scen_score

    if metrics["import_conflicts"] == 0:
        score += 15
        breakdown["import_hygiene"] = 15
    else:
        breakdown["import_hygiene"] = max(0, 15 - metrics["import_conflicts"] * 3)
        score += breakdown["import_hygiene"]

    if metrics["illegal_static_imports"] == 0:
        score += 10
        breakdown["no_illegal_static"] = 10
    else:
        breakdown["no_illegal_static"] = 0

    # 假定每类至少 4 个业务方法,目标 ≥ 8 个 test
    if metrics["test_method_count"] >= 8:
        score += 10
        breakdown["density"] = 10
    else:
        breakdown["density"] = int(metrics["test_method_count"] / 8 * 10)
        score += breakdown["density"]

    verdict = "PASS" if score >= 80 else ("PARTIAL" if score >= 50 else "FAIL")
    return {
        "overall": score,
        "verdict": verdict,
        "breakdown": breakdown,
    }


# ============================================================
# 基线记录
# ============================================================

def load_baseline():
    if os.path.isfile(BASELINE_PATH):
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": []}


def save_baseline(baseline):
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)


def record_run(target_class, metrics, score, agent_result=None):
    """记录一次评测到 baseline.json"""
    baseline = load_baseline()
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_class": target_class,
        "metrics": metrics,
        "score": score,
    }
    if agent_result:
        entry["agent_run"] = agent_result
    baseline["runs"].append(entry)
    baseline["last_run"] = entry
    save_baseline(baseline)
    return entry


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="百灵测试 Agent 评测器")
    parser.add_argument("--target-class", required=True)
    parser.add_argument("--eval-only", action="store_true",
                        help="只评测已有产物,不重跑 agent")
    parser.add_argument("--output-dir", default="workspace-风鸟-backend-test/output/generated_tests")
    args = parser.parse_args()

    agent_result = None
    if not args.eval_only:
        from riskbird_test_agent import run_test_agent
        agent_result = run_test_agent(
            target_class=args.target_class,
            knowledge_path="workspace-风鸟-backend-test/knowledge/backend_call_graph.json",
            templates_dir="workspace-风鸟-backend-test/knowledge/mock_templates",
            output_dir=args.output_dir,
        )
        if isinstance(agent_result, int):
            return agent_result

    # 评测
    file_path = os.path.join(args.output_dir, f"{args.target_class}Test.java")
    log.info(f"评测文件: {file_path}")

    metrics = evaluate_test_file(file_path)
    score = compute_overall_score(metrics)

    print("\n" + "=" * 60)
    print(f"评测报告: {args.target_class}")
    print("=" * 60)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print()
    print(f"综合得分: {score['overall']}/100  -> {score['verdict']}")
    print(f"细分: {json.dumps(score['breakdown'], ensure_ascii=False)}")

    # 记录基线
    entry = record_run(args.target_class, metrics, score, agent_result)
    print(f"\n已记录到: {BASELINE_PATH}")
    return 0 if score["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
