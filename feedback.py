"""
啄木鸟 PRD 评审反馈闭环模块

独立脚本，在 AI Coding 完成后手动运行。
从代码目录中采集下游信号，反哺评审规则改进。

用法:
    python feedback.py --code-dir /path/to/code --report output/PRD_改动报告_20260411.md
    python feedback.py --code-dir /path/to/code  # 只采集信号
"""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

# ── 常量 ──

# 代码注释中的 PRD 相关吐槽关键词
ASSUMPTION_KEYWORDS = [
    "假设", "TODO", "FIXME", "PRD未说明", "待确认",
    "不确定", "需求不清", "暂定",
]

# UI 状态关键词
UI_STATE_KEYWORDS = [
    "loading", "error", "empty", "no-result", "no_result", "noResult",
    "加载中", "加载失败", "暂无数据", "无结果", "空状态",
    "skeleton", "spinner", "fallback", "placeholder",
]

# 代码文件后缀
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java", ".go",
    ".html", ".css", ".scss", ".less",
}


# ── 工具函数 ──

def _is_code_file(path):
    """判断是否为代码文件"""
    return Path(path).suffix.lower() in CODE_EXTENSIONS


def _relative_path(file_path, base_dir):
    """计算相对路径"""
    try:
        return str(Path(file_path).relative_to(base_dir))
    except ValueError:
        return str(file_path)


def _read_file_safe(path, encoding="utf-8"):
    """安全读取文件，失败返回 None"""
    try:
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            return f.read()
    except (OSError, IOError):
        return None


def _grep_lines(file_path, keywords):
    """在文件中搜索关键词，返回 [(行号, 行内容)] 列表"""
    content = _read_file_safe(file_path)
    if not content:
        return []
    hits = []
    for i, line in enumerate(content.splitlines(), 1):
        for kw in keywords:
            if kw.lower() in line.lower():
                hits.append((i, line.strip(), kw))
                break  # 同一行只匹配一次
    return hits


def _walk_code_files(code_dir, scope_keywords=None):
    """遍历代码目录中的所有代码文件，可选按 scope 关键词过滤"""
    skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    for root, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            full_path = os.path.join(root, f)
            if _is_code_file(full_path):
                # 如果指定了 scope，只扫描路径中包含关键词的文件
                if scope_keywords:
                    rel = _relative_path(full_path, code_dir).lower()
                    if not any(kw in rel for kw in scope_keywords):
                        continue
                yield full_path


# ── 1. 下游信号采集 ──

def _collect_assumption_signals(code_dir, scope_keywords=None):
    """a) 代码注释中的 PRD 相关吐槽"""
    signals = []
    for fp in _walk_code_files(code_dir, scope_keywords):
        hits = _grep_lines(fp, ASSUMPTION_KEYWORDS)
        for line_no, content, keyword in hits:
            signals.append({
                "type": "assumption",
                "file": _relative_path(fp, code_dir),
                "line": line_no,
                "content": content,
                "keyword": keyword,
            })
    return signals


def _extract_prd_fields(prd_text):
    """从 PRD 文本中提取字段名（best-effort）

    搜索"字段"、"映射"、"DDL"附近的表格，提取类似 snake_case 的标识符
    """
    fields = set()
    # 匹配 markdown 表格行中的 snake_case / camelCase 标识符
    # 先找包含关键词的区域
    lines = prd_text.splitlines()
    in_relevant_section = False
    relevant_keywords = ["字段", "映射", "DDL", "数据表", "表结构", "字段名", "column"]

    for line in lines:
        lower = line.lower()
        # 进入相关区域
        if any(kw in lower for kw in relevant_keywords):
            in_relevant_section = True
        # 离开相关区域（遇到新的一级/二级标题）
        elif re.match(r"^#{1,2}\s", line) and in_relevant_section:
            in_relevant_section = False

        if in_relevant_section:
            # 提取 snake_case 标识符（至少含一个下划线）
            identifiers = re.findall(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b', lower)
            fields.update(identifiers)
            # 提取 camelCase 标识符
            camel = re.findall(r'\b([a-z]+[A-Z][a-zA-Z0-9]*)\b', line)
            fields.update(camel)

    return fields


def _to_snake(name):
    """camelCase → snake_case"""
    s1 = re.sub(r'([A-Z])', r'_\1', name)
    return s1.lower().lstrip('_')


def _collect_field_inconsistency_signals(code_dir, prd_file, scope_keywords=None):
    """b) 字段不一致检测"""
    if not prd_file or not os.path.isfile(prd_file):
        return []

    prd_text = _read_file_safe(prd_file)
    if not prd_text:
        return []

    prd_fields = _extract_prd_fields(prd_text)
    if not prd_fields:
        return []  # 提取不到就跳过

    # 构建 snake_case ↔ camelCase 对照表
    field_variants = {}  # { normalized_snake: original_prd_field }
    for f in prd_fields:
        snake = _to_snake(f) if f != _to_snake(f) else f
        field_variants[snake] = f

    signals = []
    for fp in _walk_code_files(code_dir, scope_keywords):
        content = _read_file_safe(fp)
        if not content:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for snake_form, prd_field in field_variants.items():
                # 在代码中搜索 camelCase 变体
                camel = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), snake_form)
                # 只在 PRD 用 snake_case 但代码用 camelCase（或反过来）时报告
                if prd_field == snake_form and camel in line and snake_form not in line:
                    signals.append({
                        "type": "field_inconsistency",
                        "file": _relative_path(fp, code_dir),
                        "line": i,
                        "content": f"PRD 用 '{prd_field}' 但代码用 '{camel}'",
                    })
                elif prd_field == camel and snake_form in line and camel not in line:
                    signals.append({
                        "type": "field_inconsistency",
                        "file": _relative_path(fp, code_dir),
                        "line": i,
                        "content": f"PRD 用 '{prd_field}' 但代码用 '{snake_form}'",
                    })
    return signals


def _collect_rework_signals(code_dir, scope_keywords=None):
    """c) 返工指标 — 分析 git commit 历史"""
    signals = []
    git_dir = os.path.join(code_dir, ".git")
    if not os.path.isdir(git_dir):
        return signals

    try:
        # 统计每个文件被修改的 commit 次数
        result = subprocess.run(
            ["git", "log", "--pretty=format:", "--name-only"],
            cwd=code_dir, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return signals

        file_counts = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                file_counts[line] = file_counts.get(line, 0) + 1

        # 如果指定了 scope，只保留路径中包含关键词的文件
        if scope_keywords:
            file_counts = {
                fp: cnt for fp, cnt in file_counts.items()
                if any(kw in fp.lower() for kw in scope_keywords)
            }

        # 修改超过 3 次的文件
        for file_path, count in file_counts.items():
            if count > 3:
                signals.append({
                    "type": "rework",
                    "file": file_path,
                    "content": f"被修改 {count} 次（超过 3 次阈值），可能因 PRD 不清导致返工",
                })
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # 按修改次数降序排列
    signals.sort(key=lambda s: int(m.group(1)) if (m := re.search(r'(\d+) 次', s.get("content", ""))) else 0, reverse=True)
    return signals


def _collect_ui_state_signals(code_dir, prd_file, scope_keywords=None):
    """d) UI 状态补全检测 — 代码有但 PRD 没提及的 UI 状态"""
    # 先收集代码中出现的 UI 状态关键词
    code_hits = {}  # { keyword: [(file, line_no, content)] }
    for fp in _walk_code_files(code_dir, scope_keywords):
        hits = _grep_lines(fp, UI_STATE_KEYWORDS)
        for line_no, content, keyword in hits:
            code_hits.setdefault(keyword, []).append(
                (_relative_path(fp, code_dir), line_no, content)
            )

    # 如果有 PRD，检查哪些 UI 状态 PRD 没提及
    prd_text = ""
    if prd_file and os.path.isfile(prd_file):
        prd_text = (_read_file_safe(prd_file) or "").lower()

    signals = []
    for keyword, occurrences in code_hits.items():
        # 如果 PRD 中没提及该关键词，说明是开发自行补充的
        if prd_text and keyword.lower() in prd_text:
            continue  # PRD 中有，不算 gap
        for file_path, line_no, content in occurrences:
            signals.append({
                "type": "ui_state_gap",
                "file": file_path,
                "line": line_no,
                "content": f"UI 状态 '{keyword}' 在代码中出现但 PRD 未提及: {content}",
            })

    return signals


def collect_signals(code_dir, prd_file=None, scope_keywords=None):
    """主入口：从代码目录采集所有下游信号"""
    code_dir = os.path.abspath(code_dir)
    if not os.path.isdir(code_dir):
        print(f"[错误] 代码目录不存在: {code_dir}")
        return []

    signals = []
    signals.extend(_collect_assumption_signals(code_dir, scope_keywords))
    signals.extend(_collect_field_inconsistency_signals(code_dir, prd_file, scope_keywords))
    signals.extend(_collect_rework_signals(code_dir, scope_keywords))
    signals.extend(_collect_ui_state_signals(code_dir, prd_file, scope_keywords))
    return signals


# ── 2. 评审项结局追踪 ──

def _parse_review_items(report_text):
    """从改动报告中提取改进项

    匹配格式如:
        - id: R-001
          位置: "xxx"
          ...
          确认状态: 已确认 / 已驳回 / 待确定
    或 markdown 表格/列表中的 R-xxx 编号
    """
    items = []

    # 策略1: 匹配 YAML 风格的改进项块
    yaml_pattern = re.compile(
        r'-\s*id:\s*(R-\d+)\s*\n'
        r'(?:\s+位置:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+问题:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+建议:\s*["\']?(.+?)["\']?\s*\n)?'
        r'(?:\s+严重度:\s*(\w+)\s*\n)?'
        r'(?:.*?\n)*?'
        r'(?:\s+确认状态:\s*(.+?)\s*\n)?',
        re.MULTILINE
    )
    for m in yaml_pattern.finditer(report_text):
        status_raw = (m.group(6) or "").strip()
        status = _normalize_status(status_raw)
        items.append({
            "id": m.group(1),
            "location": (m.group(2) or "").strip(),
            "problem": (m.group(3) or "").strip(),
            "severity": (m.group(5) or "should").strip(),
            "status": status,
        })

    if items:
        return items

    # 策略2: 按段落匹配 R-xxx 编号（适配实际报告中的各种格式）
    # 按 ## 分段，在每段中找 R-xxx
    sections = re.split(r'\n(?=##\s)', report_text)
    current_section = ""
    for section in sections:
        header_match = re.match(r'##\s*(.+)', section)
        if header_match:
            current_section = header_match.group(1).strip()

        # 在段落中找 R-xxx 模式
        for line in section.splitlines():
            id_match = re.search(r'(R-\d+)', line)
            if id_match:
                rid = id_match.group(1)
                # 避免重复
                if any(it["id"] == rid for it in items):
                    continue
                status = "confirmed"
                if "驳回" in current_section or "驳回" in line:
                    status = "rejected"
                elif "待确定" in current_section or "待确定" in line:
                    status = "pending"
                items.append({
                    "id": rid,
                    "location": line.strip()[:80],
                    "severity": "unknown",
                    "status": status,
                })

    return items


def _normalize_status(raw):
    """统一确认状态"""
    if not raw:
        return "unknown"
    if "确认" in raw or "接受" in raw or "✅" in raw:
        return "confirmed"
    if "驳回" in raw or "❌" in raw:
        return "rejected"
    if "待确定" in raw or "⚠" in raw:
        return "pending"
    return "unknown"


def _match_signal_to_item(signal, item):
    """判断一条信号是否与某个改进项相关

    多维度评分匹配，总分 ≥ 2 视为命中：
    1. 文件路径匹配：信号 file 字段含 location/problem 中的模块名 → +2
    2. 关键词匹配：location+problem 关键词出现在信号 content+file 中，每词 +1
    3. 信号类型亲和：signal_type 与 location/problem 语义对应 → +1
    """
    location = item.get("location", "").lower()
    problem = item.get("problem", "").lower()
    if not location and not problem:
        return False

    signal_content = signal.get("content", "").lower()
    signal_file = signal.get("file", "").lower()
    signal_text = signal_content + " " + signal_file
    item_text = location + " " + problem

    score = 0

    # --- 1. 文件路径匹配 ---
    # 取 signal file 的路径各段（目录名、文件名去扩展），看是否出现在 item 文本中
    if signal_file:
        import os as _os
        file_parts = re.split(r'[/\\.\-_]', signal_file)
        for part in file_parts:
            if len(part) >= 2 and part in item_text:
                score += 2
                break  # 只加一次

    # --- 2. 关键词匹配（双语，精炼停用词） ---
    stop_words = {
        "prd", "the", "and", "or", "of", "in", "is", "to", "a", "an",
        "第", "节", "章", "的", "中", "和", "与", "或", "及", "等", "该",
        "为", "在", "对", "有", "是",
    }
    loc_words = re.findall(r'[\w\u4e00-\u9fff]{2,}', item_text)
    loc_words = [w for w in loc_words if w not in stop_words]
    for word in loc_words:
        if word in signal_text:
            score += 1

    # --- 3. 信号类型亲和 ---
    signal_type = signal.get("signal_type", "").lower()
    type_affinity = {
        "assumption":        ["未说明", "待确认", "缺失", "assumption", "unclear"],
        "field_inconsistency": ["字段", "映射", "field", "ddl", "一致"],
        "rework":            ["频繁", "返工", "rework", "重复修改"],
        "ui_state_gap":      ["状态", "ui", "加载", "空", "loading", "error", "empty"],
    }
    keywords_for_type = type_affinity.get(signal_type, [])
    for kw in keywords_for_type:
        if kw in item_text:
            score += 1
            break  # 类型亲和每个 type 只加一次

    return score >= 2


def evaluate_outcomes(review_report_path, signals):
    """评审项结局追踪"""
    report_text = _read_file_safe(review_report_path)
    if not report_text:
        print(f"[错误] 无法读取评审报告: {review_report_path}")
        return []

    items = _parse_review_items(report_text)
    if not items:
        print("[警告] 未从报告中解析出改进项")
        return []

    # 为每个改进项匹配下游信号
    outcomes = []
    matched_signal_indices = set()

    for item in items:
        related_signals = []
        for idx, sig in enumerate(signals):
            if _match_signal_to_item(sig, item):
                related_signals.append(sig)
                matched_signal_indices.add(idx)

        has_downstream_issue = len(related_signals) > 0

        # 判定结局
        if item["status"] == "confirmed" and not has_downstream_issue:
            outcome = "effective_catch"
        elif item["status"] == "confirmed" and has_downstream_issue:
            outcome = "insufficient_fix"
        elif item["status"] == "rejected" and has_downstream_issue:
            outcome = "wrong_rejection"
        else:
            outcome = "no_signal"

        outcomes.append({
            "item_id": item["id"],
            "location": item["location"],
            "severity": item["severity"],
            "status": item["status"],
            "outcome": outcome,
            "related_signals": related_signals,
        })

    # 找出未被任何改进项覆盖的下游信号 → missed
    for idx, sig in enumerate(signals):
        if idx not in matched_signal_indices:
            outcomes.append({
                "item_id": "MISSED",
                "location": sig.get("file", ""),
                "severity": "unknown",
                "status": "none",
                "outcome": "missed",
                "related_signals": [sig],
            })

    return outcomes


# ── 3. 规则权重更新 ──

def update_rule_scores(outcomes, rules_file, workspace=None, prd_name=None):
    """用 EMA 算法更新规则的 impact_score，并追加规则历史记录"""
    # 先追加历史记录（无论规则文件是否存在都做）
    if workspace:
        _append_rule_history(outcomes, workspace, prd_name)

    if not rules_file or not os.path.isfile(rules_file):
        print("\n[跳过] 规则文件不存在，打印权重更新建议：")
        _print_score_suggestions(outcomes)
        return

    try:
        import yaml
    except ImportError:
        print("[跳过] 未安装 PyYAML，无法更新规则文件。打印建议：")
        _print_score_suggestions(outcomes)
        return

    with open(rules_file, "r", encoding="utf-8") as f:
        rules_data = yaml.safe_load(f)

    if not rules_data or not isinstance(rules_data, (list, dict)):
        print("[警告] 规则文件格式无法解析")
        _print_score_suggestions(outcomes)
        return

    # 规则列表可能在 rules_data 本身（list）或 rules_data["rules"]（dict）
    rules_list = rules_data if isinstance(rules_data, list) else rules_data.get("rules", [])

    alpha = 0.15  # EMA 系数

    # 计算每个结局类型对 impact_score 的增量
    outcome_deltas = {
        "effective_catch": 1.0,      # 有效捕获，加分
        "insufficient_fix": 0.3,     # 修了但不够，小加
        "wrong_rejection": -0.5,     # 错误驳回，扣分
        "missed": 0.0,              # 漏报不影响已有规则
        "no_signal": 0.0,
    }

    updated_count = 0
    for outcome in outcomes:
        if outcome["outcome"] in ("missed", "no_signal"):
            continue
        # 尝试匹配规则（通过 item_id 或 location 中的规则编号）
        rule_id = _extract_rule_id(outcome)
        if not rule_id:
            continue
        for rule in rules_list:
            rid = rule.get("id", rule.get("rule_id", ""))
            if rid and rid == rule_id:
                old_score = rule.get("impact_score", 0.5)
                delta = outcome_deltas.get(outcome["outcome"], 0.0)
                # EMA 更新
                new_score = alpha * delta + (1 - alpha) * old_score
                new_score = max(0.0, min(1.0, new_score))
                rule["impact_score"] = round(new_score, 3)
                updated_count += 1

    if updated_count > 0:
        with open(rules_file, "w", encoding="utf-8") as f:
            yaml.dump(rules_data, f, allow_unicode=True, default_flow_style=False)
        print(f"\n[完成] 已更新 {updated_count} 条规则的 impact_score")
    else:
        print("\n[提示] 未找到可匹配的规则，打印建议：")
        _print_score_suggestions(outcomes)


def _append_rule_history(outcomes, workspace, prd_name=None):
    """追加规则执行历史到 rule_performance_history.json

    每次评估后，把每条有规则 ID 的结局写入历史文件，
    并更新累计统计和噪声标记。
    """
    history_path = os.path.join(workspace, "output", "rule_performance_history.json")
    today = datetime.now().strftime("%Y-%m-%d")
    prd_label = prd_name or "unknown"

    # 读取已有历史
    history_data = {}
    if os.path.isfile(history_path):
        raw = _read_file_safe(history_path)
        if raw:
            try:
                history_data = json.loads(raw)
            except json.JSONDecodeError:
                history_data = {}

    updated_rules = set()
    for o in outcomes:
        rule_id = _extract_rule_id(o)
        if not rule_id:
            continue

        # 初始化规则条目
        if rule_id not in history_data:
            history_data[rule_id] = {
                "history": [],
                "stats": {"confirmed": 0, "rejected": 0, "missed": 0, "total": 0},
                "rejection_rate": 0.0,
                "is_noisy": False,
            }

        entry = history_data[rule_id]

        # 追加本次记录
        entry["history"].append({
            "date": today,
            "outcome": o["outcome"],
            "prd": prd_label,
        })

        # 更新累计统计
        oc = o["outcome"]
        if oc in ("effective_catch", "insufficient_fix"):
            entry["stats"]["confirmed"] += 1
        elif oc == "wrong_rejection":
            entry["stats"]["rejected"] += 1
        elif oc == "missed":
            entry["stats"]["missed"] += 1
        entry["stats"]["total"] += 1

        # 计算驳回率和噪声标记
        total = entry["stats"]["total"]
        rejected = entry["stats"]["rejected"]
        entry["rejection_rate"] = round(rejected / total, 3) if total > 0 else 0.0
        entry["is_noisy"] = entry["rejection_rate"] > 0.4

        updated_rules.add(rule_id)

    if not updated_rules:
        return

    # 确保输出目录存在
    os.makedirs(os.path.dirname(history_path), exist_ok=True)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

    # 打印高噪声规则警告
    noisy_rules = [rid for rid in updated_rules if history_data[rid]["is_noisy"]]
    print(f"\n[历史] 已追加 {len(updated_rules)} 条规则的历史记录 → {history_path}")
    if noisy_rules:
        for rid in sorted(noisy_rules):
            rate = history_data[rid]["rejection_rate"]
            print(f"  ⚠️ {rid} 驳回率 {rate:.0%}（高噪规则，建议审查）")


def _extract_rule_id(outcome):
    """从结局中提取规则编号（RC-xxx、V-xx 或 BMAD V-xx）"""
    text = outcome.get("location", "") + " " + str(outcome.get("related_signals", ""))
    # 先尝试匹配 BMAD V-xx 格式
    match = re.search(r'(BMAD\s+V-\d+)', text)
    if match:
        return match.group(1)
    # 再匹配 RC-xxx 或 V-xx
    match = re.search(r'(RC-\d+|V-\d+)', text)
    return match.group(1) if match else None


def _print_score_suggestions(outcomes):
    """打印权重更新建议（无规则文件时）"""
    stats = {}
    for o in outcomes:
        oc = o["outcome"]
        stats[oc] = stats.get(oc, 0) + 1
    for outcome_type, count in sorted(stats.items()):
        label = {
            "effective_catch": "有效捕获（规则有用，建议保持/提权）",
            "insufficient_fix": "修复不足（规则方向对但力度不够，建议细化）",
            "wrong_rejection": "错误驳回（被拒绝的改进项确实有问题，需复审规则）",
            "missed": "漏报（需新增规则覆盖）",
            "no_signal": "无下游信号（暂无法评估）",
        }.get(outcome_type, outcome_type)
        print(f"  {label}: {count} 条")


# ── 4. 漏报 → 新规则提案 ──

def propose_new_rules(missed_signals, wiki_dir):
    """对 missed 信号按 type 聚类，每组 >= 3 条时生成规则提案"""
    if not missed_signals:
        return []

    # 按 signal type 分组
    groups = {}
    for sig in missed_signals:
        sig_type = sig.get("type", "unknown")
        groups.setdefault(sig_type, []).append(sig)

    proposals = []
    today = datetime.now().strftime("%Y%m%d")

    for sig_type, sigs in groups.items():
        if len(sigs) < 3:
            continue

        seq = len(proposals) + 1
        proposal_id = f"PROP-{today}-{seq:02d}"

        # 生成规则名
        rule_name_map = {
            "assumption": "PRD 应明确标注假设与待确认项",
            "field_inconsistency": "PRD 字段命名应与代码规范一致",
            "rework": "PRD 应对高频修改模块提供更详细的规格说明",
            "ui_state_gap": "PRD 应覆盖所有 UI 异常状态的处理方案",
        }
        rule_name = rule_name_map.get(sig_type, f"补充 {sig_type} 类检查项")

        # 支撑证据
        evidence_lines = []
        for s in sigs[:5]:  # 最多列 5 条
            evidence_lines.append(f"- [{s.get('file', '?')}:{s.get('line', '?')}] {s.get('content', '')[:100]}")
        evidence = "\n".join(evidence_lines)

        proposal_content = f"""# 规则提案 {proposal_id}

## 建议规则名
{rule_name}

## 严重度
should

## 信号类型
{sig_type}

## 信号数量
{len(sigs)} 条

## 支撑证据
{evidence}

## 建议描述
在 PRD 评审时增加对 "{sig_type}" 类问题的检查，减少 AI Coding 阶段的返工和自行补充。

---
生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}
"""
        proposals.append({
            "id": proposal_id,
            "rule_name": rule_name,
            "sig_type": sig_type,
            "count": len(sigs),
            "content": proposal_content,
        })

        # 写入 wiki 目录
        if wiki_dir:
            os.makedirs(wiki_dir, exist_ok=True)
            filename = f"规则提案-{today}-{seq:02d}.md"
            filepath = os.path.join(wiki_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(proposal_content)
            print(f"  [写入] {filepath}")

    return proposals


# ── 5. CLI 入口 ──

def _print_signal_summary(signals):
    """打印信号摘要"""
    print("\n" + "=" * 60)
    print("信号采集摘要")
    print("=" * 60)

    if not signals:
        print("  未采集到任何信号。")
        return

    # 按类型统计
    type_counts = {}
    for s in signals:
        t = s["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    type_labels = {
        "assumption": "PRD 相关吐槽/假设",
        "field_inconsistency": "字段不一致",
        "rework": "疑似返工文件",
        "ui_state_gap": "UI 状态缺失",
    }

    total = 0
    for t, count in sorted(type_counts.items()):
        label = type_labels.get(t, t)
        print(f"  {label}: {count} 条")
        total += count
    print(f"  {'─' * 30}")
    print(f"  总计: {total} 条")

    # 打印前 10 条信号详情
    print(f"\n前 {min(10, len(signals))} 条信号详情：")
    for i, s in enumerate(signals[:10], 1):
        loc = s.get("file", "?")
        line = s.get("line")
        loc_str = f"{loc}:{line}" if line else loc
        print(f"  [{i}] [{s['type']}] {loc_str}")
        print(f"      {s['content'][:100]}")


def _classify_rule_type(rule_id):
    """根据规则 ID 判断类型：BMAD（文档规范）或 RC（实现约束）"""
    if not rule_id:
        return None
    # V-XX 或 BMAD V-XX → BMAD（文档规范）
    if re.match(r'^(BMAD\s+)?V-\d+', rule_id):
        return "BMAD（文档规范）"
    # RC-XXX → RC（实现约束）
    if re.match(r'^RC-\d+', rule_id):
        return "RC（实现约束）"
    return None


def _print_rule_type_stats(outcomes):
    """按规则类型（BMAD / RC）分组统计结局"""
    # 按规则类型聚合结局
    type_outcomes = {}  # { rule_type: { outcome: count } }
    for o in outcomes:
        rule_id = _extract_rule_id(o)
        rule_type = _classify_rule_type(rule_id)
        if not rule_type:
            # missed 类型没有规则 ID，跳过分类统计
            if o["outcome"] == "missed":
                rule_type = "未分类"
            else:
                continue
        type_outcomes.setdefault(rule_type, {})
        oc = o["outcome"]
        type_outcomes[rule_type][oc] = type_outcomes[rule_type].get(oc, 0) + 1

    if not type_outcomes:
        return

    print(f"\n按规则类型统计：")
    # 表头
    print(f"  {'类型':<20} {'有效捕获':<10} {'修复不足':<10} {'错误驳回':<10} {'漏报':<10}")
    print(f"  {'─' * 60}")

    for rule_type in sorted(type_outcomes.keys()):
        stats = type_outcomes[rule_type]
        effective = stats.get("effective_catch", 0)
        insufficient = stats.get("insufficient_fix", 0)
        wrong = stats.get("wrong_rejection", 0)
        missed = stats.get("missed", 0)
        print(f"  {rule_type:<20} {effective:<10} {insufficient:<10} {wrong:<10} {missed:<10}")


def _print_outcome_table(outcomes):
    """打印结局表格"""
    print("\n" + "=" * 60)
    print("改进项结局追踪")
    print("=" * 60)

    if not outcomes:
        print("  无结局数据。")
        return

    outcome_labels = {
        "effective_catch": "有效捕获",
        "insufficient_fix": "修复不足",
        "wrong_rejection": "错误驳回",
        "missed": "漏报",
        "no_signal": "无信号",
    }

    # 表头
    print(f"  {'ID':<10} {'状态':<10} {'结局':<12} {'相关信号数':<10}")
    print(f"  {'─' * 42}")

    for o in outcomes:
        oc_label = outcome_labels.get(o["outcome"], o["outcome"])
        sig_count = len(o.get("related_signals", []))
        print(f"  {o['item_id']:<10} {o['status']:<10} {oc_label:<12} {sig_count:<10}")

    # 统计
    print(f"\n结局统计：")
    oc_stats = {}
    for o in outcomes:
        oc = o["outcome"]
        oc_stats[oc] = oc_stats.get(oc, 0) + 1
    for oc, count in sorted(oc_stats.items()):
        print(f"  {outcome_labels.get(oc, oc)}: {count}")

    # 按规则类型（BMAD / RC）分组统计
    _print_rule_type_stats(outcomes)


def _print_proposals(proposals):
    """打印规则提案"""
    if not proposals:
        return

    print("\n" + "=" * 60)
    print("新规则提案")
    print("=" * 60)

    for p in proposals:
        print(f"\n  [{p['id']}] {p['rule_name']}")
        print(f"  信号类型: {p['sig_type']} | 支撑信号数: {p['count']}")


def main():
    parser = argparse.ArgumentParser(
        description="啄木鸟 PRD 评审反馈闭环 — 从 AI Coding 结果采集反馈信号"
    )
    parser.add_argument(
        "--code-dir", required=True,
        help="AI Coding 产出的代码目录",
    )
    parser.add_argument(
        "--report",
        help="啄木鸟评审报告路径（如 output/PRD_改动报告_20260411.md）",
    )
    parser.add_argument(
        "--prd",
        help="原始 PRD 文件路径（用于字段一致性检测和 UI 状态对比）",
    )
    parser.add_argument(
        "--rules-file",
        default=None,
        help="评审规则文件路径（默认 review-rules/review-checklist.yaml）",
    )
    parser.add_argument(
        "--wiki-dir",
        default=None,
        help="规则提案输出目录（默认 wiki/）",
    )
    parser.add_argument(
        "--scope",
        default=None,
        help="扫描范围关键词（逗号分隔），只扫描路径中包含这些关键词的文件。如 'arbitration,labour,仲裁'",
    )
    parser.add_argument(
        "--prd-name",
        default=None,
        help="PRD 名称标识（用于规则历史记录中标注来源，如 '劳动仲裁'）",
    )

    args = parser.parse_args()

    # 确定基础目录（脚本所在目录）
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rules_file = args.rules_file or os.path.join(base_dir, "review-rules", "review-checklist.yaml")
    wiki_dir = args.wiki_dir or os.path.join(base_dir, "wiki")

    # 1. 采集信号
    print("[1/4] 采集下游信号...")
    scope_keywords = None
    if args.scope:
        scope_keywords = [kw.strip().lower() for kw in args.scope.split(",") if kw.strip()]
        print(f"  扫描范围: {', '.join(scope_keywords)}")

    signals = collect_signals(args.code_dir, prd_file=args.prd, scope_keywords=scope_keywords)
    _print_signal_summary(signals)

    # 2. 结局追踪（需要 report）
    outcomes = []
    if args.report:
        print("\n[2/4] 评审项结局追踪...")
        report_path = args.report
        if not os.path.isabs(report_path):
            report_path = os.path.join(base_dir, report_path)
        outcomes = evaluate_outcomes(report_path, signals)
        _print_outcome_table(outcomes)
    else:
        print("\n[2/4] 未指定 --report，跳过结局追踪。")

    # 3. 规则权重更新
    if outcomes:
        print("\n[3/4] 规则权重更新...")
        update_rule_scores(outcomes, rules_file, workspace=base_dir, prd_name=args.prd_name)
    else:
        print("\n[3/4] 无结局数据，跳过规则权重更新。")

    # 4. 漏报 → 新规则提案
    missed_signals = []
    for o in outcomes:
        if o["outcome"] == "missed":
            missed_signals.extend(o.get("related_signals", []))

    if missed_signals:
        print("\n[4/4] 生成新规则提案...")
        proposals = propose_new_rules(missed_signals, wiki_dir)
        _print_proposals(proposals)
    else:
        print("\n[4/4] 无漏报信号，跳过规则提案。")

    print("\n" + "=" * 60)
    print("反馈闭环分析完成。")
    print("=" * 60)


if __name__ == "__main__":
    main()
