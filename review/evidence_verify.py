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
from typing import Any, Dict, List

from logger import get_logger

log = get_logger("parallel")

# Metrics 埋点 — 失败 silent skip, 不阻 evidence verify 主流程
try:
    from review.metrics_store import record_event as _record_event
except Exception:
    def _record_event(*args, **kwargs):  # noqa: ARG001
        return False


# 中文分词: 用 jieba 替代滑动窗口 (2026-04-28). 老滑窗 r'[\u4e00-\u9fff]{2,4}'
# 把"位置标识符"切成 ["位置标识","置标识符"] 噪声子串, 导致 issue 即便逐字
# 引用 evidence 也常 overlap=0. jieba 出真实词后 overlap 信号才有意义.
try:
    import jieba
    jieba.setLogLevel(40)  # 屏蔽 jieba INFO 日志
    _JIEBA_AVAILABLE = True
except ImportError:
    log.warning("jieba 未安装, B 类语义 overlap 回退到滑动窗口算法")
    _JIEBA_AVAILABLE = False


def _extract_cn_keywords(text: str) -> set:
    """中文 keyword 提取: jieba 切真实词, 长度 ≥ 2 且全中文."""
    if not text:
        return set()
    if _JIEBA_AVAILABLE:
        return {w for w in jieba.lcut(text)
                if len(w) >= 2 and re.fullmatch(r'[\u4e00-\u9fff]+', w)}
    # 回退: 老滑窗算法
    return set(re.findall(r'[\u4e00-\u9fff]{2,4}', text))


# ============================================================
# rule_id 抽取: 走 SchemaRegistry 单点 SoT (step 3.4)
# ============================================================

# 把 registry.rule_id_pattern() 的 ^...$ 锚点剥掉, 用于在 evidence 文本里 findall 抽 rule_id.
# 为什么不直接 re.findall(pattern) — registry pattern 是 ^(V|RC|EV|FN)-\d+$ anchored,
# findall 在长文本里会一条都抽不到. 这里剥锚点保留 prefix 枚举.
_ANCHOR_STRIP = re.compile(r"^\^(.*)\$$")


def _registry_rule_id_extractor(workspace=None, allow_bmad_prefix=False):
    r"""从 SchemaRegistry 拿 rule_id 抽取正则 (单点 SoT, step 3.4).

    替代原硬编码 ``r"(?:RC|V|EV|FN)-\d+"`` — 加新前缀 (如 RC-017) 时
    只改 review-dimensions.yaml, evidence_verify 自动同步.

    Args:
        workspace: 工作目录路径, 传给 SchemaRegistry.get 拿对应 registry.
        allow_bmad_prefix: True 时同时识别 ``BMAD V-XX`` 写法 (向后兼容).

    Returns:
        compiled regex (re.Pattern), 用于 findall 抽 rule_id substring.
    """
    from review.schema_registry import SchemaRegistry

    registry = SchemaRegistry.get(workspace=workspace)
    anchored = registry.rule_id_pattern()           # 例 r"^(V|RC|EV|FN)-\d+$"
    m = _ANCHOR_STRIP.match(anchored)
    bare = m.group(1) if m else anchored            # → r"(V|RC|EV|FN)-\d+"
    # 把 capturing group 转成 non-capturing — 否则 findall 只返 prefix 不返完整 id.
    # registry rule_id_pattern() 用 capturing group `(V|RC|...)`, findall 行为是返
    # group 1, 这里把第一个 `(` 换成 `(?:` 让 findall 拿完整 substring.
    bare_noncap = re.sub(r"^\(([^?])", r"(?:\1", bare)

    if allow_bmad_prefix:
        # BMAD 前缀只与 V-XX 搭配 (历史 BMAD 框架兼容, 与 P0-B 改前一致)
        return re.compile(rf"(?:BMAD\s+V-\d+|{bare_noncap})")
    return re.compile(bare_noncap)


def _extract_rule_ids(text, workspace=None, allow_bmad_prefix=False):
    """从文本抽合法 rule_id 列表 (registry 已知前缀过滤).

    单点入口, 取代散落 re.findall 调用.
    """
    if not text:
        return []
    pattern = _registry_rule_id_extractor(workspace=workspace, allow_bmad_prefix=allow_bmad_prefix)
    return pattern.findall(text)


def _is_known_rule_id(rule_id, workspace=None):
    """rule_id 合法性校验: registry.all_rule_ids() set membership.

    替代字符串 regex 校验 — V-99 / FN-50 这种"前缀对但 yaml 没注册"的 id 也能拒掉.
    """
    if not rule_id:
        return False
    from review.schema_registry import SchemaRegistry
    registry = SchemaRegistry.get(workspace=workspace)
    # BMAD V-XX 兼容: 剥前缀再查
    clean = rule_id.replace("BMAD ", "").strip()
    return clean in registry.all_rule_ids()


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
            # 2026-04-26 P0-A: 剥 YAML 引号风格 — `authority: "canonical"` 老逻辑解析成
            # `'"canonical"'` 不在 _VALID_AUTHORITY set, 静默走 default 降级到 contextual.
            # 修: strip 双/单引号后再放入 dict.
            value = kv[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            fm[kv[0].strip()] = value
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
    # 2026-04-26 P1-D audit fix: 拒绝占位串提权.
    # `verified_by: TBD/-/待定/?` 等 placeholder 不应判 trusted, 老逻辑 truthy 检查太宽.
    verified_by = fm.get("verified_by", "").strip()
    _PLACEHOLDER_VERIFIED_BY = frozenset({
        "tbd", "TBD", "Tbd", "待定", "待", "未知", "-", "?", "??", "???", "n/a", "N/A", "nil", "null",
    })
    if verified_by and verified_by not in _PLACEHOLDER_VERIFIED_BY and len(verified_by) >= 2:
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

    2026-04-27 P0-A 修复: 走 content_loader.iter_wiki_files 同步外挂 canonical wiki —
    workspace 本身可能 sparse, 但外挂 49 个 canonical 在 worker prompt 已生效,
    evidence_verify 也应认为 wiki rich. 否则 wiki_mode=sparse 触发宽松模式,
    LLM NLI 永不触发 + 23 条 A 类被宽松降权掩盖真 fail.

    Args:
        wiki_dir: wiki 目录绝对路径
        min_business_files: 认定 "有业务上下文" 的最小业务 md 数量

    Returns:
        True 表示 sparse(走宽松模式), False 表示 rich(维持严格校验)
    """
    from content_loader import iter_wiki_files
    md_files = iter_wiki_files(wiki_dir)
    if not md_files:
        return True
    business_files = [
        f for f in md_files
        if os.path.basename(f) not in _META_WIKI_FILENAMES
        and not _is_pecker_generated(f)  # 剔除 pecker 自回归生成的
    ]
    return len(business_files) < min_business_files


def _build_wiki_index(wiki_dir):
    """构建 wiki 文件索引(一次扫描, 多次复用)。

    2026-04-24 pecker 自生成过滤: pecker 上次评审的 C 类回写文件 (`sources: 0`)
    不应作为本次 A 类依据的验证权威(自回归偏见)。

    2026-04-27 P0-A 修复: 走 content_loader.iter_wiki_files 同步外挂 canonical
    wiki — 让 49 个 canonical page 也进 index, 不再丢. workspace 本地 + 外挂同
    basename 时 workspace 优先 (与 load_wiki_pages 语义一致).
    """
    from content_loader import iter_wiki_files
    md_files = iter_wiki_files(wiki_dir)
    index = {}
    for wiki_file in md_files:
        # 剔除 pecker 自动生成的 wiki,防自回归
        if _is_pecker_generated(wiki_file):
            continue
        basename = os.path.basename(wiki_file)
        # 同 basename: 后到的覆盖 (iter_wiki_files 顺序: 外挂在先 / workspace 在后,
        # workspace 自动覆盖外挂, 跟 load_wiki_pages 语义一致)
        index[basename] = wiki_file
    return index


def _find_wiki_page_with_signal(evidence_content, wiki_dir, wiki_index=None):
    """`_find_wiki_page` 的扩展版, 同时返回匹配信号 dict (供 LLM NLI 消费).

    Sprint #6 EvidenceRL 升级 (2026-04-26):
    输出连续匹配信号取代 binary, 让下游 EMA delta 能区分"精确引用"vs"模糊关键词命中".

    L4 GraphRAG Phase 3 (2026-04-28):
    支持 `[[entity:e_xxx]]` 引用 — 走 wiki_kg_tools.entity_exists() 而非页面名匹配.
    向后兼容: 老 [[页面名]] 引用仍按老逻辑走 manifest 字符串匹配.

    Returns:
        tuple (found: bool, signal: dict)
        signal = {
            "method": "entity_exact" | "entity_missing" | "ref_exact" | "ref_substring" | "keyword" | "no_match",
            "matched_pages": [basename, ...],   # 最多前 3 个匹配页面
            "ref_count": int,                    # [[ref]] 引用数
            "keyword_count": int,                # 兜底关键词搜数
            "entity_ids": [eid, ...],            # 抽到的 entity_id 列表 (新格式)
        }
    """
    signal = {
        "method": "no_match",
        "matched_pages": [],
        "ref_count": 0,
        "keyword_count": 0,
        "entity_ids": [],
    }

    if not os.path.isdir(wiki_dir):
        return False, signal

    # L4 Phase 3: 优先检查 [[entity:e_xxx]] 引用 — workspace 走 wiki_dir 反推
    workspace = os.path.dirname(wiki_dir.rstrip(os.sep))
    try:
        from review.wiki_kg_tools import parse_entity_refs, entity_exists
        entity_refs = parse_entity_refs(evidence_content)
        signal["entity_ids"] = entity_refs
        if entity_refs:
            # 有 entity 引用 — 检查是否都存在
            all_exist = all(entity_exists(eid, workspace=workspace) for eid in entity_refs)
            if all_exist:
                signal["method"] = "entity_exact"
                signal["matched_pages"] = entity_refs[:3]
                return True, signal
            else:
                signal["method"] = "entity_missing"
                # 不直接 return — 让下面老格式 page name 匹配也跑一遍, 容许混合引用
    except ImportError:
        # wiki_kg_tools 没装 (老 workspace) — 跳过 entity 路径, 走老逻辑
        pass

    page_refs = re.findall(r"\[\[(.+?)\]\]", evidence_content)
    # 把 entity:xxx 形式的 ref 从 page_refs 里剔除 (避免重复处理)
    page_refs = [r for r in page_refs if not r.startswith("entity:")]
    signal["ref_count"] = len(page_refs)

    if page_refs:
        from review.wiki_selection import normalize_wiki_title, wiki_title_aliases

        # 有明确 [[ref]] 引用
        for ref in page_refs:
            for basename in (wiki_index or {}):
                if ref == basename or ref == basename.replace(".md", ""):
                    signal["matched_pages"].append(basename)
                    signal["method"] = "ref_exact"
                    return True, signal
            ref_norm = normalize_wiki_title(ref)
            for basename in (wiki_index or {}):
                if ref_norm in wiki_title_aliases(basename):
                    signal["matched_pages"].append(basename)
                    signal["method"] = "ref_normalized"
                    return True, signal
            for basename in (wiki_index or {}):
                if ref in basename:
                    signal["matched_pages"].append(basename)
                    signal["method"] = "ref_substring"
                    return True, signal
            if not wiki_index:
                pattern = os.path.join(wiki_dir, f"*{ref}*")
                matches = glob_module.glob(pattern)
                if matches:
                    signal["matched_pages"] = [os.path.basename(m) for m in matches[:3]]
                    signal["method"] = "ref_substring"
                    return True, signal
        return False, signal

    # 模糊关键词兜底
    all_basenames = list(wiki_index.keys()) if wiki_index else [
        os.path.basename(f) for f in glob_module.glob(os.path.join(wiki_dir, "*.md"))
    ]
    cn_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', evidence_content)
    en_keywords = [w for w in re.findall(r'[a-zA-Z_-]+', evidence_content) if len(w) > 2]
    keywords = cn_keywords + en_keywords
    signal["keyword_count"] = len(keywords)

    from review.wiki_selection import wiki_title_aliases

    for basename in all_basenames:
        aliases = wiki_title_aliases(basename)
        for kw in keywords[:5]:
            kw_norm = kw.lower()
            if kw in basename or any(kw_norm in alias for alias in aliases):
                signal["matched_pages"].append(basename)
                signal["method"] = "keyword"
                return True, signal
    return False, signal


def _find_wiki_page(evidence_content, wiki_dir, wiki_index=None):
    """向后兼容 wrapper — 仅返 bool. 7 个 caller 不用改.

    Sprint #6 后内部走 `_find_wiki_page_with_signal`, signal dict 在 verify_evidence
    主入口才被消费 (写入 v_details + 可选 LLM NLI 升级).
    """
    found, _signal = _find_wiki_page_with_signal(evidence_content, wiki_dir, wiki_index)
    return found


def _llm_nli_score(client, item, wiki_pages, n_samples=4, model=None):
    """Sprint #6 EvidenceRL: 用 LLM 三选一判 evidence 与 wiki 的支持度 (entail/contradict/neutral).

    Anthropic API 不暴露 token logprobs, 用蒙特卡洛重采样近似 (N=4 默认 + temperature=0.7).
    比 logprobs 公式精度粗 (95% CI ±25%), 但够替代 binary 信号给 EMA 用.

    Wave 2 路由:
    - client is None → 走 model_router.route_call("verify.nli", ...) (推荐路径)
    - client is not None → 仍走入参 client.create (兼容 mock 测试 + 老 caller)

    设计 (来自 audit feasibility 调研):
    - 拒 hedging: prompt 强制非 entail 时给 ≥ 30 字理由, 否则采样无效
    - 失败采样静默 skip (network/parse error), 不影响分母
    - 失败回 default `{entail=0, contradict=0, neutral=1, max_signal=0}` 让 caller 知道 NLI 没生效

    Args:
        client: 有 .create() 方法的 LLM client (兼容 mock 测试). None → 走 router.
        item: review item dict, 必须含 "issue" + "evidence_content"
        wiki_pages: dict {page_title: page_content}, 从 verify_evidence 上层传入
        n_samples: 重采样次数, 默认 4 (单 PRD 评审 ~5s 串行 / ~2s 并行)
        model: 默认 None (走 router 配置). 显式传完整 model 名时仍用入参 client (兼容老 caller).

    Returns:
        {
            "entail_score": 0.0-1.0,
            "contradict_score": 0.0-1.0,
            "neutral_score": 0.0-1.0,
            "max_signal": 0.0-1.0 (entail vs contradict 偏向强度, 越大越确定),
            "n_samples_succeeded": int (有效采样数, < n_samples 说明部分失败),
        }
    """
    default = {
        "entail_score": 0.0,
        "contradict_score": 0.0,
        "neutral_score": 1.0,
        "max_signal": 0.0,
        "n_samples_succeeded": 0,
    }
    # Wave 2: client=None 时走 router. 老 caller 传 client 时为兼容 mock 测试不走 router.
    use_router = client is None
    if not wiki_pages or not item:
        return default
    if not use_router and not client:
        return default

    issue = (item.get("issue") or "").strip()
    evidence = (item.get("evidence_content") or "").strip()
    if not issue or not evidence:
        return default

    # 提取 [[ref]] 找对应 wiki 内容 (限前 3 页 / 每页 1500 字防超 token)
    page_refs = re.findall(r"\[\[(.+?)\]\]", evidence)
    relevant_pages = []
    from review.wiki_selection import normalize_wiki_title, wiki_title_aliases

    for ref in page_refs:
        ref_norm = normalize_wiki_title(ref)
        for title, content in wiki_pages.items():
            if (
                ref in title
                or title in ref
                or ref == title.replace(".md", "")
                or ref_norm in wiki_title_aliases(title)
            ):
                relevant_pages.append((title, (content or "")[:1500]))
                break
        if len(relevant_pages) >= 3:
            break

    # 2026-04-27 P2 修: evidence 明确引用 [[ref]] 但 wiki_pages 全找不到对应页面
    # = 引用了不存在的 wiki 页面 = 经典 hallucination 模式 (fake_ref).
    # 之前 return default (neutral_score=1) 让这类 case 在 NLI 评测中永远漏检 (TPR=0).
    # 现在直接判 contradict, 节省 LLM 调用 + 修复 fake_ref 漏检.
    if page_refs and not relevant_pages:
        return {
            "entail_score": 0.0,
            "contradict_score": 1.0,
            "neutral_score": 0.0,
            "max_signal": 1.0,
            "n_samples_succeeded": -1,  # -1 标识 fast-path (没调 LLM)
        }

    if not relevant_pages:
        # evidence 没 [[ref]] 引用 + wiki 也对不上 → 真 neutral, default 回
        return default

    wiki_block = "\n---\n".join(f"# {t}\n{c}" for t, c in relevant_pages)
    # 2026-04-27 P2 修: Wave 5 真 baseline 显示 n_samples_succeeded=0 (LLM 输出全被
    # 解析层吃掉, 不是 LLM 不输出 contradict). 三处放宽:
    #   1. reason 长度 30→15 (env PECKER_NLI_REASON_MIN_LEN)
    #   2. hedging filter 默认关 (env PECKER_NLI_HEDGING_FILTER=1 才启用)
    #   3. verdict regex 加宽容 fallback (无引号 / markdown 加粗 / 单词形式)
    # 配 PECKER_NLI_DEBUG=1 dump 每次 LLM raw text + 拒收原因, 方便后续诊断.
    system = (
        "你判断 PRD 评审改进项的引用依据是否被 wiki 页面支持。\n\n"
        "三选一:\n"
        "- entail: wiki 中有原文/数值/字段/规则明确支持改进项\n"
        "- contradict: wiki 与改进项**任何**具体不一致 (任一即必选 contradict, 不要选 neutral):\n"
        "  · 改进项引用 [[页面名]] 但 wiki 提供的页面里实际没这个页面\n"
        "  · 改进项断言的字段名 / 枚举值 / 数值 / 流程顺序 与 wiki 不同\n"
        "  · 改进项凭推理得出 wiki 根本没说的结论 (无凭据推断 = contradict 而非 neutral)\n"
        "  · 改进项引用 wiki 内容但 wiki 实际表达相反含义\n"
        "- neutral: wiki 完全未涉及该话题, 也没有任何字段/数值能比对\n\n"
        "关键判准: 只要 wiki 与改进项**有任何具体可比的不一致点**, 就必须选 contradict.\n"
        "neutral 只用于 wiki 跟改进项完全不相干 (e.g. 改进项谈支付, wiki 只讲登录).\n\n"
        "如果不是 entail, 用 1-2 句 (≥15 字) 说明具体哪个字段/数值/页面不一致.\n\n"
        "只输出 JSON 一行 (不要 markdown 代码块): "
        '{"verdict": "entail|contradict|neutral", "reason": "<具体理由>"}'
    )
    user = f"# 改进项问题\n{issue}\n\n# 引用依据\n{evidence}\n\n# Wiki 相关页面\n{wiki_block}"

    # P2 调参 (env-gated, 默认更宽容)
    reason_min_len = int(os.environ.get("PECKER_NLI_REASON_MIN_LEN", "15"))
    hedging_on = os.environ.get("PECKER_NLI_HEDGING_FILTER", "0") == "1"
    debug_on = os.environ.get("PECKER_NLI_DEBUG", "0") == "1"
    _HEDGING_WORDS = ("可能", "也许", "不确定", "或许", "大概", "应该是", "貌似", "看起来")

    counts = {"entail": 0, "contradict": 0, "neutral": 0}
    succeeded = 0
    debug_samples: List[Dict[str, Any]] = [] if debug_on else None

    for _ in range(n_samples):
        try:
            if use_router:
                from model_router import route_call
                resp = route_call(
                    "verify.nli",
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    max_tokens=300,
                    temperature=0.7,
                )
            else:
                # 老 caller (传 client) 路径: 兼容 mock 测试 / 直接复用 worker client
                resp = client.create(
                    model=model,
                    max_tokens=300,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    temperature=0.7,
                )
            text_parts = []
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text_parts.append(getattr(block, "text", ""))
            text = "".join(text_parts)

            # verdict 解析: 三层 fallback
            #  1. 标准 JSON: "verdict": "contradict"
            #  2. 无引号或单引号: verdict: contradict / 'verdict': 'contradict'
            #  3. 单词形式: 文本里出现明确 "contradict" / "entail" / "neutral" 词
            verdict = None
            v_match = re.search(r'["\']?verdict["\']?\s*[:：]\s*["\']?(entail|contradict|neutral)["\']?', text, re.IGNORECASE)
            if v_match:
                verdict = v_match.group(1).lower()
            else:
                # 单词扫描 fallback
                for w in ("contradict", "entail", "neutral"):
                    if re.search(rf"\b{w}\b", text, re.IGNORECASE):
                        verdict = w
                        break
            if not verdict:
                if debug_on:
                    debug_samples.append({"reject_reason": "no_verdict", "text": text[:300]})
                continue

            # reason 解析: 标准 JSON + 单引号 fallback + 取整段 text 作为 reason
            r_match = re.search(r'["\']?reason["\']?\s*[:：]\s*["\']([^"\']*)["\']', text)
            if r_match:
                reason = r_match.group(1)
            else:
                # 没找到结构化 reason, 用整个 LLM 输出当 reason (最大兼容)
                reason = text.strip()

            if hedging_on and any(h in reason for h in _HEDGING_WORDS):
                if debug_on:
                    debug_samples.append({"reject_reason": "hedging", "verdict": verdict, "reason": reason[:200]})
                continue
            if verdict != "entail" and len(reason) < reason_min_len:
                if debug_on:
                    debug_samples.append({"reject_reason": "reason_too_short", "verdict": verdict,
                                          "reason_len": len(reason), "reason": reason[:200]})
                continue

            counts[verdict] += 1
            succeeded += 1
            if debug_on:
                debug_samples.append({"accepted": True, "verdict": verdict, "reason_len": len(reason)})
        except Exception as e:
            if debug_on:
                debug_samples.append({"reject_reason": "exception", "error": str(e)[:200]})
            continue

    if debug_on and debug_samples:
        from logger import get_logger
        _log = get_logger("nli_debug")
        for d in debug_samples:
            _log.info(f"[nli] {d}")

    if succeeded == 0:
        # Metrics 埋点: nli.score - 0 succeeded (LLM 输出全被解析吃掉)
        try:
            _record_event(
                "nli.score",
                status="failed",
                details={
                    "n_samples": n_samples,
                    "n_samples_succeeded": 0,
                    "entail": 0, "contradict": 0, "neutral": 0,
                },
            )
        except Exception:
            pass
        return default

    entail = counts["entail"] / succeeded
    contradict = counts["contradict"] / succeeded
    neutral = counts["neutral"] / succeeded

    # Metrics 埋点: nli.score (entail/contradict/neutral 分布)
    try:
        # status 字段简化记 winning verdict (entail/contradict/neutral)
        _winner = max(counts.items(), key=lambda kv: kv[1])[0] if any(counts.values()) else "neutral"
        _record_event(
            "nli.score",
            status=_winner,
            details={
                "n_samples": n_samples,
                "n_samples_succeeded": succeeded,
                "entail": counts["entail"],
                "contradict": counts["contradict"],
                "neutral": counts["neutral"],
                "max_signal": round(abs(entail - contradict), 3),
            },
        )
    except Exception:
        pass

    return {
        "entail_score": round(entail, 3),
        "contradict_score": round(contradict, 3),
        "neutral_score": round(neutral, 3),
        "max_signal": round(abs(entail - contradict), 3),
        "n_samples_succeeded": succeeded,
    }


def _verify_evidence_chain(chain, wiki_dir=None, wiki_index=None, prd_content=None):
    """CaRR 借鉴 (arXiv 2601.06021): 检查 evidence_chain 多跳完整性 (2026-04-26).

    每跳 = {hop_idx, claim, citation}. citation 应该是:
    - PRD 章节号: "第 3.2 节" / "3.2" / "L120-L150"
    - wiki 页面引用: "[[页面名]]"
    - 表/字段名: "ds_xxx.field_y"

    Returns:
        (passed: bool, signal: dict)
        signal = {
            "chain_length": int,
            "broken_hops": [hop_idx, ...],   # citation 找不到的 hop
            "completeness": 0.0-1.0,         # 通过的 hop 比例
            "method": "wiki" | "prd_section" | "mixed" | "no_chain",
        }

    chain 缺失或空 → passed=True, completeness=1.0 (不强制), method="no_chain"
    所有跳通过 → passed=True, completeness=1.0
    部分通过 → passed=True (软强制不 fail), completeness < 1.0
    """
    signal = {
        "chain_length": 0,
        "broken_hops": [],
        "completeness": 1.0,
        "method": "no_chain",
    }
    if not chain or not isinstance(chain, list):
        return True, signal

    signal["chain_length"] = len(chain)
    methods_used = set()
    broken = []

    for hop in chain:
        if not isinstance(hop, dict):
            broken.append(hop.get("hop_idx", "?") if isinstance(hop, dict) else "?")
            continue
        hop_idx = hop.get("hop_idx", -1)
        citation = (hop.get("citation") or "").strip()
        claim = (hop.get("claim") or "").strip()
        if not citation or not claim:
            broken.append(hop_idx)
            continue

        # 判断 citation 类型
        if "[[" in citation and "]]" in citation:
            # wiki 引用
            methods_used.add("wiki")
            if wiki_dir is None and wiki_index is None:
                # 没 wiki context, 无法验证, 视为通过 (软强制)
                continue
            found, _sig = _find_wiki_page_with_signal(citation, wiki_dir or "", wiki_index)
            if not found:
                broken.append(hop_idx)
        elif re.search(r'\d+(\.\d+)?', citation):
            # 看像 PRD 章节号
            methods_used.add("prd_section")
            if prd_content:
                # 提取章节号 (如 "第 3.2 节" → "3.2") 在 PRD 文本里搜
                section_match = re.search(r'(\d+(?:\.\d+)*)', citation)
                if section_match:
                    section_id = section_match.group(1)
                    if section_id not in prd_content:
                        broken.append(hop_idx)
            # 没 prd_content 视为通过 (软强制)
        else:
            # 其他形式 (表名 / 字段名 等), 不强求验证
            methods_used.add("other")

    signal["broken_hops"] = broken
    if signal["chain_length"] > 0:
        signal["completeness"] = round(
            (signal["chain_length"] - len(broken)) / signal["chain_length"], 3
        )

    if len(methods_used) == 1:
        signal["method"] = methods_used.pop()
    elif len(methods_used) > 1:
        signal["method"] = "mixed"

    # 软强制: 即使部分跳 broken 也不 fail, 让 PM 看到 completeness 自行判断
    return True, signal


def _find_rule_reference(evidence_content, rules_dir):
    r"""检查规则编号是否在 review-rules 目录中存在.

    2026-04-27 step 3.4: rule_id 抽取走 SchemaRegistry.rule_id_pattern() 单点 SoT,
    替代原硬编码 ``(?:RC|V|EV|FN)-\d+`` regex. 加新前缀 (RC-017 / V-13 / FN-04)
    时只改 review-dimensions.yaml, evidence_verify 自动同步, 不再 P0-B 漂移.

    workspace 用 ``rules_dir`` 反推 (rules_dir = workspace/review-rules), 避免
    改函数签名破坏 caller.
    """
    if not os.path.isdir(rules_dir):
        return False

    # 反推 workspace (rules_dir = workspace/review-rules)
    workspace = os.path.dirname(rules_dir.rstrip(os.sep))
    # 提取规则编号（如 RC-005, V-07, EV-01, FN-09, BMAD V-02 等）
    rule_ids = _extract_rule_ids(evidence_content, workspace=workspace, allow_bmad_prefix=True)
    if not rule_ids:
        # 没有明确规则编号，视为验证失败
        return False

    # 2026-04-29 SSOT 修复: extends 模式下 workspace yaml 只含 extends + additional_rules
    # 直接字符串搜会全 miss → 走 rule_loader 拿全集 rule_id 集合 (含 SSOT)
    try:
        from review.rule_loader import load_review_checklist
        all_rules = load_review_checklist(workspace) or []
        valid_ids = {r.get("id") for r in all_rules if r.get("id")}
        if valid_ids:
            for rid in rule_ids:
                clean_rid = rid.replace("BMAD ", "")
                if clean_rid in valid_ids:
                    return True
            # rule_loader 加载到了规则但都不匹配 → 真不存在
            return False
    except Exception:
        # rule_loader 失败 → 回退老字符串搜索路径
        pass

    # 老路径: 在 review-rules 目录下递归字符串搜索 (老 inline yaml 仍 work)
    all_rules_files = glob_module.glob(os.path.join(rules_dir, "**", "*"), recursive=True)
    for rules_file in all_rules_files:
        if not os.path.isfile(rules_file):
            continue
        try:
            with open(rules_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for rid in rule_ids:
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
    # 2026-04-27 step 3.4: rule_id 抽取走 SchemaRegistry 单点 SoT, 替代散落 regex.
    # 不传 allow_bmad_prefix — 语义验证拿不到 BMAD V-XX 在 review-rules 里独立条目,
    # 与原 regex 行为一致 (上面 _find_rule_reference 才需要 BMAD 兼容).
    workspace = os.path.dirname(rules_dir.rstrip(os.sep))
    rule_ids = _extract_rule_ids(ev_content, workspace=workspace, allow_bmad_prefix=False)
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

    # 提取 item 的关键词 (jieba 真实词切分 + 英文 3+ 字母词)
    item_text = f"{item.get('issue', '')} {item.get('suggestion', '')}"
    cn_kw = _extract_cn_keywords(item_text)
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
    rule_cn_kw = _extract_cn_keywords(rule_text)
    rule_en_kw = set(w.lower() for w in re.findall(r'[a-zA-Z_-]{3,}', rule_text))
    rule_keywords = (rule_cn_kw | rule_en_kw) - stop_words

    if not rule_keywords:
        return True, ""

    # 计算 overlap ratio
    overlap = item_keywords & rule_keywords
    ratio = len(overlap) / len(item_keywords) if item_keywords else 0

    # 阈值 0.05 (2026-04-28 jieba 修复后调优):
    # - 老滑窗 + 0.10 阈值: 误降级率 80% (50/51), 几乎全部 finding 被误判
    # - jieba + 0.10 阈值: 仍误降级 23% (10/43), 救回 0.07-0.10 真有效 finding
    # - jieba + 0.05 阈值: 误降级 4.7% (2/43), 剩下边缘案例苍鹰兜底
    # 详见 scripts/tune_overlap_threshold.py 的 oracle 分析
    SEMANTIC_OVERLAP_THRESHOLD = 0.05
    if ratio < SEMANTIC_OVERLAP_THRESHOLD:
        note = (
            f"B 类依据语义薄弱: {target_rid} 原文与 item 关键词 overlap={ratio:.2f} "
            f"(阈值 {SEMANTIC_OVERLAP_THRESHOLD}), item 可能引用了不相关规则"
        )
        return False, note

    return True, ""


# ============================================================
# 主入口:verify_evidence + summarize_verification
# ============================================================


def verify_evidence(items, workspace, client=None, wiki_pages=None, prd_content=None):
    """
    验证每条改进项的依据是否可回溯

    v1.2(B1): 细化返回字段
    - item["status"]: "VERIFIED" / "RETRACTED"  (向后兼容,run_session.py:336 的过滤仍有效)
    - item["verification_status"]: "verified" / "verified_with_caveat" / "retracted"  (细粒度)
    - item["verification_reason"]: 详细原因(成功/失败都有)
    - item["verification_details"]: {evidence_type, target, found, [match_signal], [nli_score], [chain_signal]}
    - item["retract_reason"]: 向后兼容(同 verification_reason)

    2026-04-26 Sprint #6 EvidenceRL 升级:
    A 类命中分支 client + wiki_pages 都非 None 时, 调 _llm_nli_score 加 entail/contradict 连续分,
    写到 verification_details. 失败 / client=None 不影响主流程, 老 caller 不传 client 走 100% 等价老逻辑.

    2026-04-26 Sprint #B CaRR 借鉴 (arXiv 2601.06021):
    item.evidence_chain 字段 (worker tool schema 新加, 可选) 给多跳证据链, 本函数检查 chain 完整性
    写到 v_details.chain_signal. 软强制: 即使部分跳 broken 也不 retract, 让 PM 看 completeness.
    需要 prd_content 才能验证 PRD 章节号 citation, 不传则只验 wiki citation.

    Args:
        items: 改进项列表
        workspace: 工作目录路径
        client: (可选) LLM client, A 类命中时调 NLI
        wiki_pages: (可选) {page_title: page_content} dict, NLI 用
        prd_content: (可选) PRD 全文字符串, evidence_chain 验证 PRD 章节号 citation 用

    Returns:
        验证后的 items 列表(失败的标记 RETRACTED)
    """
    import time as _t
    _ev_started_at = _t.time()
    _ev_input_count = len(items) if items else 0
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
            else:
                # 2026-04-26 Sprint #6 EvidenceRL: 用 _find_wiki_page_with_signal 拿匹配方法 +
                # 命中页面列表, 写到 v_details. method 区分 ref_exact / ref_substring / keyword.
                _found, _match_signal = _find_wiki_page_with_signal(ev_content, wiki_dir, wiki_index)
                if not _found:
                    # 2026-04-24 P0 放宽: wiki 未命中不再 retract, 改降权保留.
                    # 原逻辑粗暴 retract,等于把"证据链弱"等同"item 错",
                    # 会把合理 item 一并抹杀(侵权软件模板 PRD 实测 4 条 A 类被撤).
                    # 新逻辑: confidence × 0.7 降权保留,让 PM 自己判断.
                    v_status = "verified_with_caveat"
                    # L4 Phase 3: 区分 entity_missing (entity_id 不存在) vs page_not_found (页面名错).
                    # entity_missing 比 page_not_found 更严重 — worker 引用了不存在的 KG 节点.
                    if _match_signal.get("method") == "entity_missing":
                        v_reason = (
                            f"A 类依据: 引用的 entity_id 不存在于 KG "
                            f"({_match_signal.get('entity_ids', [])}), 降权保留"
                        )
                        v_details["reason_code"] = "A_entity_id_not_found_weak"
                    else:
                        v_reason = (
                            "A 类依据: wiki 未找到匹配页面, 降权保留 "
                            "(证据链弱但 item 可能仍有效, 由 PM 复核)"
                        )
                        v_details["reason_code"] = "A_wiki_page_not_found_weak"
                    v_details["found"] = False
                    v_details["match_signal"] = _match_signal
                    old_conf = item.get("confidence_score", 0.8)
                    item["confidence_score"] = round(old_conf * 0.7, 2)
                else:
                    v_details["found"] = True
                    v_details["match_signal"] = _match_signal
                    # Sprint #6: 有 client + wiki_pages 时调 LLM NLI 给连续 entail/contradict 分,
                    # 写到 v_details. 失败/client=None 跳过, 不影响主流程.
                    if client is not None and wiki_pages:
                        try:
                            nli = _llm_nli_score(client, item, wiki_pages, n_samples=4)
                            v_details["nli_score"] = nli
                            # contradict 占主时降权 (entail-contradict 越负越拉低 confidence)
                            # 不直接 retract, 让 PM 看到 contradict signal 自行决定
                            if nli["contradict_score"] > nli["entail_score"]:
                                v_details["reason_code"] = "A_nli_contradict_signal"
                                old_conf = item.get("confidence_score", 0.85)
                                item["confidence_score"] = round(old_conf * 0.7, 2)
                        except Exception as _nli_err:
                            log.warning(f"[verify] NLI score 失败, skip: {_nli_err}")

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

        # 2026-04-26 CaRR: 检查 evidence_chain 完整性 (软强制, 不 fail).
        # item.evidence_chain 字段 worker 可选输出 (review/worker.py SUBMIT_REVIEW_ITEMS_TOOL),
        # 缺失时跳过. 检查通过/部分通过 → 写 v_details.chain_signal 让 PM 看 completeness.
        chain = item.get("evidence_chain", []) or []
        if chain:
            try:
                _chain_passed, chain_signal = _verify_evidence_chain(
                    chain, wiki_dir=wiki_dir, wiki_index=wiki_index, prd_content=prd_content,
                )
                v_details["chain_signal"] = chain_signal
                # completeness < 0.5 时给 v_reason 加注但不改 status
                if chain_signal["completeness"] < 0.5 and chain_signal["chain_length"] > 0:
                    v_reason = (v_reason or "") + (
                        f"; CaRR chain completeness={chain_signal['completeness']} "
                        f"({len(chain_signal['broken_hops'])}/{chain_signal['chain_length']} 跳 citation 找不到)"
                    )
            except Exception as _chain_err:
                log.warning(f"[verify] evidence_chain check 失败 skip: {_chain_err}")

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

    # Metrics 埋点: evidence_verify.completed (汇总 retracted / downgraded 分布)
    try:
        _retracted = sum(1 for i in verified if i.get("verification_status") == "retracted")
        _downgraded = sum(1 for i in verified if i.get("verification_status") == "verified_with_caveat")
        _retracted_by_reason: Dict[str, int] = {}
        for i in verified:
            if i.get("verification_status") == "retracted":
                _code = (i.get("verification_details") or {}).get("reason_code", "unknown")
                _retracted_by_reason[_code] = _retracted_by_reason.get(_code, 0) + 1
        _record_event(
            "evidence_verify.completed",
            workspace=workspace,
            duration_ms=int((_t.time() - _ev_started_at) * 1000),
            status="success",
            details={
                "input_count": _ev_input_count,
                "retracted": _retracted,
                "downgraded": _downgraded,
                "retracted_by_reason": _retracted_by_reason,
                "wiki_sparse": wiki_sparse,
            },
        )
    except Exception:
        pass

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
    down_by_code = Counter()   # T3 2026-04-24: caveat 细分, 供 funnel_stage_after_evidence_verify 消费
    for item in items:
        vs = item.get("verification_status", "")
        if vs == "verified":
            verified_count += 1
        elif vs == "verified_with_caveat":
            verified_count += 1
            caveat_count += 1
            down_code = item.get("verification_details", {}).get("reason_code", "unknown")
            down_by_code[down_code] += 1
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
        "downgraded": caveat_count,                       # T3 alias, caveat = downgraded (语义一致)
        "retracted_by_reason_code": dict(by_code),
        "downgraded_by_reason_code": dict(down_by_code),  # T3 新增
        "reliability": round(reliability, 3),
    }
