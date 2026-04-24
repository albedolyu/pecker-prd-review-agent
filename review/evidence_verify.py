"""依据可回溯性验证 (Side Query).

从 parallel_review.py 拆出 (2026-04-16):
- A 类依据: wiki 页面是否存在
- B 类依据: review-rules 里规则号是否真实 + 语义 overlap 检查
- C 类依据: 必须标注"待确定⚠️"(自动补标)

对外 API:
- verify_evidence(items, workspace) - 主入口,标注 verified / verified_with_caveat / retracted
- summarize_verification(items) - 给门禁用的概要统计

parallel_review.py re-export 这些符号,现有调用方无需改动 import 路径。
"""

import glob as glob_module
import os
import re
from collections import Counter

from logger import get_logger

log = get_logger("parallel")


# ============================================================
# wiki / rule 文件查找
# ============================================================


# 元文件(不算"业务 wiki 内容"),用于 _is_wiki_sparse 判定
_META_WIKI_FILENAMES = frozenset({"log.md", "index.md", "README.md", "TOC.md"})


_VALID_AUTHORITY = frozenset({"canonical", "trusted", "contextual", "generated"})


def _parse_wiki_frontmatter(wiki_file_path):
    """读取 wiki 文件 YAML frontmatter 并解析成 dict。

    容错策略:
    - 文件读失败 (OSError, 编码异常) → 返回 {}
    - 没有 frontmatter 包围块 (---) → 返回 {}
    - 逐行 key: value 解析 (不用 YAML 库以保持轻量 + 不引入依赖)

    只处理 frontmatter 里的 scalar 字段 (string / number),list/dict 字段当 string 截取,
    这对 authority/owner/sources/last_verified/verified_by 这种 scalar 足够。
    """
    try:
        with open(wiki_file_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(1500)  # frontmatter 一般在 1k 内, 1500 足够兜底
    except OSError:
        return {}
    m = re.match(r'^\s*---\s*\n(.*?)\n---', head, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).split("\n"):
        kv = line.split(":", 1)
        if len(kv) == 2:
            fm[kv[0].strip()] = kv[1].strip()
    return fm


def _wiki_authority_tier(wiki_file_path):
    """返回 wiki 文件的 authority tier: 'canonical' | 'trusted' | 'contextual' | 'generated'。

    优先级:
    1. IOError / 无 frontmatter → 'contextual' (保留老 _is_pecker_generated 返回 False 语义,
       让文件仍进 wiki_index,只是不作强依据; 不用 'generated' 避免把读错的合理文件挡掉)
    2. sources == 0 → 'generated' (硬性约束,不信任矛盾声明如"sources:0 但 authority:canonical")
    3. 显式 authority 字段合法 → 原样返回
    4. 冷启动映射: 有 verified_by → 'trusted', 否则 'contextual'

    spec: docs/wiki-frontmatter-v2.md

    2026-04-24 发现的自回归偏见(autoregressive bias):
    pecker 的 "C 类回写 wiki" 步骤(post_review.py)会把"待确定⚠️"的 C 类
    evidence 自动提炼成 wiki 页, frontmatter 里 sources: 0。把这些自生成 wiki 作为
    下次评审 A 类依据的权威源, 形成 "pecker 用自己的输出验证自己的输出" 的循环。
    本函数通过 tier 分级替代原 binary 判断, 让 generated 层自动过滤,
    同时给 PM 手工 promote 到 trusted/canonical 留口子。
    """
    fm = _parse_wiki_frontmatter(wiki_file_path)

    # IOError / 无 frontmatter 兜底 — 保留老接口语义 (文件仍进 wiki_index)
    if not fm:
        return "contextual"

    # 硬性约束: **显式** sources: 0 强制 generated (即使写了 authority: canonical)
    # 注意只有 sources 字段 explicitly present 且解析成 0 才触发 —
    # 缺失 sources 字段 / 非整数 (如 list 格式) 走默认映射, 与老 `_is_pecker_generated`
    # 的 `^sources:\s*0\s*$` 正则行为等价 (只认明确的 "sources: 0")
    sources_raw = fm.get("sources")
    if sources_raw is not None:
        try:
            if int(sources_raw) == 0:
                return "generated"
        except (ValueError, TypeError):
            pass  # 非整数 → 视为 non-zero, 走下面默认映射

    # 显式 authority 合法 → 信任
    explicit = fm.get("authority", "").strip()
    if explicit in _VALID_AUTHORITY:
        return explicit

    # 冷启动默认映射
    verified_by = fm.get("verified_by", "").strip()
    if verified_by:
        return "trusted"
    return "contextual"


def _is_pecker_generated(wiki_file_path):
    """向后兼容的 binary 接口 — 内部走 `_wiki_authority_tier`。

    3 个调用点保持不变 (evidence_verify.py:_is_wiki_sparse / _build_wiki_index /
    tests/test_evidence_verify_wiki_sparse.py), 避免一次改太多。
    """
    return _wiki_authority_tier(wiki_file_path) == "generated"


def _is_wiki_sparse(wiki_dir, min_business_files=3):
    """判断 workspace 的 wiki 目录是否缺少业务上下文。

    模板型 / 新业务 / 跨部门引用 PRD 的 workspace 通常没填充 wiki 内容,
    A 类依据(强制 wiki 页面引用)在这种 workspace 上 100% 被 retract,
    导致 evidence_verify 过度剔除合理 items(2026-04-24 侵权软件模板 PRD
    实测 5/7 条 A 类被撤)。

    判定规则:**真实业务 md** 文件数量 < min_business_files(默认 3)视为 sparse。
    真实业务 md = 不是元文件(log/index/README/TOC) + 不是 pecker 自生成(sources: 0)。

    2026-04-24 新增 pecker 自生成过滤: 避免"pecker 自己写了 11 个 wiki 然后判 rich"
    的循环误判(autoregressive bias)。

    Args:
        wiki_dir: wiki 目录绝对路径
        min_business_files: 认定 "有业务上下文" 的最小业务 md 数量

    Returns:
        True 表示 sparse(走宽松模式), False 表示 rich(维持严格校验)
    """
    if not os.path.isdir(wiki_dir):
        return True
    md_files = glob_module.glob(os.path.join(wiki_dir, "*.md"))
    business_files = [
        f for f in md_files
        if os.path.basename(f) not in _META_WIKI_FILENAMES
        and not _is_pecker_generated(f)  # 剔除 pecker 自回归生成的
    ]
    return len(business_files) < min_business_files


def _build_wiki_index(wiki_dir):
    """构建 wiki 文件索引（一次 glob，多次复用）。

    2026-04-24 新增 pecker 自生成过滤:pecker 上次评审的 C 类回写文件
    (`sources: 0`)不应作为本次 A 类依据的验证权威(自回归偏见)。
    """
    if not os.path.isdir(wiki_dir):
        return {}
    index = {}
    for wiki_file in glob_module.glob(os.path.join(wiki_dir, "*.md")):
        # 剔除 pecker 自动生成的 wiki,防自回归
        if _is_pecker_generated(wiki_file):
            continue
        basename = os.path.basename(wiki_file)
        index[basename] = wiki_file
    return index


def _find_wiki_page(evidence_content, wiki_dir, wiki_index=None):
    """在 wiki 目录中搜索依据提到的页面"""
    if not os.path.isdir(wiki_dir):
        return False

    # 从依据内容中提取 [[页面名]] 格式的引用
    page_refs = re.findall(r"\[\[(.+?)\]\]", evidence_content)

    if page_refs:
        # 有明确的页面引用，检查文件是否存在
        for ref in page_refs:
            for basename in (wiki_index or {}):
                if ref in basename:
                    return True
            if not wiki_index:
                pattern = os.path.join(wiki_dir, f"*{ref}*")
                if glob_module.glob(pattern):
                    return True
        return False

    # 模糊搜索用索引代替 glob
    all_basenames = list(wiki_index.keys()) if wiki_index else [
        os.path.basename(f) for f in glob_module.glob(os.path.join(wiki_dir, "*.md"))
    ]
    cn_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', evidence_content)
    en_keywords = [w for w in re.findall(r'[a-zA-Z_-]+', evidence_content) if len(w) > 2]
    keywords = cn_keywords + en_keywords
    for basename in all_basenames:
        for kw in keywords[:5]:
            if kw in basename:
                return True
    return False


def _find_rule_reference(evidence_content, rules_dir):
    """检查规则编号是否在 review-rules 目录中存在"""
    if not os.path.isdir(rules_dir):
        return False

    # 提取规则编号（如 RC-005, V-07, BMAD V-02 等）
    rule_ids = re.findall(r"(?:RC-\d+|BMAD\s+V-\d+|V-\d+)", evidence_content)
    if not rule_ids:
        # 没有明确规则编号，视为验证失败
        return False

    # 在 review-rules 目录下递归搜索
    all_rules_files = glob_module.glob(os.path.join(rules_dir, "**", "*"), recursive=True)
    for rules_file in all_rules_files:
        if not os.path.isfile(rules_file):
            continue
        try:
            with open(rules_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for rid in rule_ids:
                # 去掉 "BMAD " 前缀做匹配
                clean_rid = rid.replace("BMAD ", "")
                if clean_rid in content:
                    return True
        except OSError:
            continue

    return False


# ============================================================
# B 类语义 overlap 验证 (不调 LLM,关键词比对)
# ============================================================


def _verify_b_class_semantic(item, rules_dir):
    """B 类依据语义验证(轻量版,不调 LLM)

    1. 从 review-rules/ 读 rule 原文
    2. 提取 item.issue + item.suggestion 的关键词
    3. 检查关键词和 rule 原文的 overlap ratio
    4. overlap < 0.1 -> 标记 "B 类依据语义薄弱"

    Returns:
        (passed: bool, note: str)
    """
    ev_content = item.get("evidence_content", "")
    rule_ids = re.findall(r"(?:RC-\d+|V-\d+)", ev_content)
    if not rule_ids or not os.path.isdir(rules_dir):
        return True, ""

    # 读 rule 原文: 在 review-rules/ 下找到包含该 rule_id 的文件,提取上下文
    rule_text = ""
    target_rid = rule_ids[0]  # 取第一个 rule_id
    for root, _, files in os.walk(rules_dir):
        for fn in files:
            if not fn.endswith((".md", ".yaml", ".yml", ".txt")):
                continue
            try:
                fp = os.path.join(root, fn)
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if target_rid in content:
                    rule_text = content
                    break
            except OSError:
                continue
        if rule_text:
            break

    if not rule_text:
        return True, ""  # 规则文件找不到,跳过语义验证(存在性已被 _find_rule_reference 检查)

    # 提取 item 的关键词(中文 2-4 字词 + 英文 3+ 字母词)
    item_text = f"{item.get('issue', '')} {item.get('suggestion', '')}"
    cn_kw = set(re.findall(r'[\u4e00-\u9fff]{2,4}', item_text))
    en_kw = set(w.lower() for w in re.findall(r'[a-zA-Z_-]{3,}', item_text))
    item_keywords = cn_kw | en_kw

    # 停用词过滤
    stop_words = {"文档", "说明", "需求", "内容", "系统", "功能", "应该", "建议",
                  "问题", "修改", "添加", "缺少", "the", "and", "for", "that", "this",
                  "should", "must", "not", "with", "from", "have", "are", "PRD", "prd"}
    item_keywords -= stop_words

    if not item_keywords:
        return True, ""

    # 提取 rule 原文的关键词
    rule_cn_kw = set(re.findall(r'[\u4e00-\u9fff]{2,4}', rule_text))
    rule_en_kw = set(w.lower() for w in re.findall(r'[a-zA-Z_-]{3,}', rule_text))
    rule_keywords = (rule_cn_kw | rule_en_kw) - stop_words

    if not rule_keywords:
        return True, ""

    # 计算 overlap ratio
    overlap = item_keywords & rule_keywords
    ratio = len(overlap) / len(item_keywords) if item_keywords else 0

    if ratio < 0.1:
        note = (
            f"B 类依据语义薄弱: {target_rid} 原文与 item 关键词 overlap={ratio:.2f} "
            f"(阈值 0.1), item 可能引用了不相关规则"
        )
        return False, note

    return True, ""


# ============================================================
# 主入口:verify_evidence + summarize_verification
# ============================================================


def verify_evidence(items, workspace):
    """
    验证每条改进项的依据是否可回溯

    v1.2(B1): 细化返回字段
    - item["status"]: "VERIFIED" / "RETRACTED"  (向后兼容,run_session.py:336 的过滤仍有效)
    - item["verification_status"]: "verified" / "verified_with_caveat" / "retracted"  (细粒度)
    - item["verification_reason"]: 详细原因(成功/失败都有)
    - item["verification_details"]: {evidence_type, target, found}
    - item["retract_reason"]: 向后兼容(同 verification_reason)

    Args:
        items: 改进项列表
        workspace: 工作目录路径

    Returns:
        验证后的 items 列表(失败的标记 RETRACTED)
    """
    wiki_dir = os.path.join(workspace, "wiki")
    rules_dir = os.path.join(workspace, "review-rules")
    wiki_index = _build_wiki_index(wiki_dir)

    # 2026-04-24 P0 修复: 模板型 / 新业务 workspace 的 wiki 稀疏时走宽松模式,
    # 不对 A 类依据做硬 retract, 改 verified_with_caveat + 保留 item 继续下游.
    # 之前逻辑在 workspace-侵权软件 这种无 wiki 上下文场景下 100% retract A 类,
    # 导致 evidence_verify 裁剪过度 (实测 5/7 条 A 类被撤, pipeline 80% 吞没率).
    wiki_sparse = _is_wiki_sparse(wiki_dir)
    if wiki_sparse:
        log.info(
            f"[verify] workspace 无 wiki 上下文 ({wiki_dir} 业务 md 文件 < 3), "
            f"A 类依据走宽松模式: 不 retract, 标 verified_with_caveat"
        )

    verified = []
    for item in items:
        ev_type = item.get("evidence_type", "")
        ev_content = item.get("evidence_content", "")
        retract_reason = None
        v_status = "verified"
        v_reason = f"{ev_type} 类依据通过校验" if ev_type else "无依据类型标注,跳过校验"
        v_details = {
            "evidence_type": ev_type or "unknown",
            "target": (ev_content or "")[:100],
        }

        if ev_type == "A":
            if wiki_sparse:
                # 宽松模式: 无 wiki 上下文 workspace 不对 A 类硬撤回
                v_status = "verified_with_caveat"
                v_reason = (
                    "A 类依据: workspace 无 wiki 上下文(业务 md 文件 < 3), "
                    "跳过 wiki 页面强查 — 走 evidence_weak 降级, 不 retract"
                )
                v_details["found"] = None
                v_details["reason_code"] = "A_wiki_sparse_relaxed"
            elif not _find_wiki_page(ev_content, wiki_dir, wiki_index):
                # 2026-04-24 P0 放宽: wiki 未命中不再 retract, 改降权保留.
                # 原逻辑粗暴 retract,等于把"证据链弱"等同"item 错",
                # 会把合理 item 一并抹杀(侵权软件模板 PRD 实测 4 条 A 类被撤).
                # 新逻辑: confidence × 0.7 降权保留,让 PM 自己判断.
                v_status = "verified_with_caveat"
                v_reason = (
                    "A 类依据: wiki 未找到匹配页面, 降权保留 "
                    "(证据链弱但 item 可能仍有效, 由 PM 复核)"
                )
                v_details["found"] = False
                v_details["reason_code"] = "A_wiki_page_not_found_weak"
                old_conf = item.get("confidence_score", 0.8)
                item["confidence_score"] = round(old_conf * 0.7, 2)
            else:
                v_details["found"] = True

        elif ev_type == "B":
            # B 类:检查规则编号是否在 review-rules/ 中存在
            if not _find_rule_reference(ev_content, rules_dir):
                retract_reason = f"B 类依据验证失败:review-rules 中未找到规则「{ev_content}」"
                v_status = "retracted"
                v_reason = retract_reason
                v_details["found"] = False
                v_details["reason_code"] = "B_missing_rule"
            else:
                v_details["found"] = True
                # B 类语义验证: 规则存在但 item 内容可能与规则不相关
                sem_passed, sem_note = _verify_b_class_semantic(item, rules_dir)
                if not sem_passed:
                    v_status = "verified_with_caveat"
                    v_reason = sem_note
                    v_details["reason_code"] = "B_semantic_weak"
                    # 降低 confidence 而非 retract(规则存在,只是语义薄弱)
                    old_conf = item.get("confidence_score", 0.8)
                    item["confidence_score"] = round(old_conf * 0.7, 2)
                    log.info(f"[verify] {item.get('id', '?')}: {sem_note}")

        elif ev_type == "C":
            # C 类:必须标记"待确定⚠️"
            if "待确定" not in ev_content and "⚠️" not in ev_content:
                # 自动补标,不 retract;但状态标为 verified_with_caveat(需人工确认)
                item["evidence_content"] = ev_content + "(待确定⚠️)"
                v_status = "verified_with_caveat"
                v_reason = "C 类依据自动补标'待确定⚠️',需人工确认"
                v_details["reason_code"] = "C_auto_annotated"
            else:
                v_status = "verified_with_caveat"
                v_reason = "C 类依据已标注待确定,需人工确认"
                v_details["reason_code"] = "C_pending_confirm"

        # 写入 item(保留旧字段 + 新字段)
        if retract_reason:
            item["status"] = "RETRACTED"
            item["retract_reason"] = retract_reason
        else:
            item["status"] = "VERIFIED"

        item["verification_status"] = v_status
        item["verification_reason"] = v_reason
        item["verification_details"] = v_details

        verified.append(item)

    return verified


def summarize_verification(items):
    """从验证后的 items 统计概要(供 shrike 门禁使用)

    v1.2(B1): 把 verification_status 汇总,给伯劳做决策

    Returns:
        {
            "total": N,
            "verified": N,              # verified + verified_with_caveat
            "retracted": N,
            "caveat": N,                # verified_with_caveat (C 类待确认)
            "retracted_by_reason_code": {"A_missing_wiki_page": N, ...},
            "reliability": 0.0-1.0,     # verified / total
        }
    """
    total = len(items)
    if total == 0:
        return {"total": 0, "verified": 0, "retracted": 0, "caveat": 0,
                "retracted_by_reason_code": {}, "reliability": 1.0}

    verified_count = 0
    retracted_count = 0
    caveat_count = 0
    by_code = Counter()
    for item in items:
        vs = item.get("verification_status", "")
        if vs == "verified":
            verified_count += 1
        elif vs == "verified_with_caveat":
            verified_count += 1
            caveat_count += 1
        elif vs == "retracted":
            retracted_count += 1
            code = item.get("verification_details", {}).get("reason_code", "unknown")
            by_code[code] += 1

    reliability = verified_count / total if total > 0 else 1.0
    return {
        "total": total,
        "verified": verified_count,
        "retracted": retracted_count,
        "caveat": caveat_count,
        "retracted_by_reason_code": dict(by_code),
        "reliability": round(reliability, 3),
    }
