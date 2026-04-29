"""啄木鸟 v2 路线图步骤 4: L4 GraphRAG Phase 1 — wiki 实体/关系抽取.

把平面 markdown wiki 升级成 entity+relation 知识图谱:
- 读 workspace-劳动仲裁/wiki/ 下所有 .md 页面 (含子目录)
- 对每页调 DeepSeek-flash (走 model_router verify.nli 路由) 抽 entity + relation
- 用 GraphRAG 风格 tuple-delimited 格式: "entity"<|>NAME<|>TYPE<|>DESC + "relationship"<|>SRC<|>TGT<|>...
- 固定 entity_types (spec_doc/data_table/field/ui_state/masking_rule/api_endpoint/page_concept)
- 加 gleaning loop (max_gleanings=2)
- 加去重: 同一 title+type 合并 aliases
- 输出 entities.json + relations.json 到 wiki/_kg/

跑法:
    python scripts/build_wiki_kg.py
    python scripts/build_wiki_kg.py --workspace workspace-劳动仲裁
    python scripts/build_wiki_kg.py --max-pages 5     # 调试用, 只抽前 5 页
    python scripts/build_wiki_kg.py --no-gleaning     # 跳过遗漏轮
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 加载 .env (DEEPSEEK_API_KEY)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=True)
except ImportError:
    pass


# ============================================================
# 固定 entity_types (不让 LLM 自由发挥)
# ============================================================

ENTITY_TYPES = {
    "spec_doc":     "规范类页面 (命名/字段映射/UI 4-state)",
    "data_table":   "DDL 数据表 (如 ds_risk_labour_arbitration)",
    "field":        "表字段 (含脱敏标记)",
    "ui_state":     "UI 状态 (loading/empty/error/success)",
    "masking_rule": "脱敏规则",
    "api_endpoint": "API 接口",
    "page_concept": "业务概念页 (订阅/收藏/筛选 等)",
}

# tuple 分隔符 — 跟 GraphRAG 一致
TUPLE_DELIM = "<|>"
RECORD_DELIM = "##"   # 一条 entity/relation 记录的结束标记
COMPLETION_DELIM = "<|COMPLETE|>"


# ============================================================
# Prompt 模板
# ============================================================

_EXTRACTION_PROMPT = f"""你是一个知识图谱抽取助手, 任务是从一个 wiki 页面里抽出实体 (entity) 和关系 (relationship).

## 实体类型 (entity_types) — 严格只用这 7 种, 不要发明新的:
{chr(10).join(f'- {t}: {desc}' for t, desc in ENTITY_TYPES.items())}

## 输出格式 — 严格用 tuple-delimited 文本, 不要 JSON, 不要 markdown 代码块:

每条 entity 一行:
("entity"{TUPLE_DELIM}<NAME>{TUPLE_DELIM}<TYPE>{TUPLE_DELIM}<DESCRIPTION>{TUPLE_DELIM}<ALIASES>){RECORD_DELIM}

每条 relationship 一行:
("relationship"{TUPLE_DELIM}<SRC_NAME>{TUPLE_DELIM}<TGT_NAME>{TUPLE_DELIM}<RELATION_TYPE>{TUPLE_DELIM}<DESCRIPTION>{TUPLE_DELIM}<WEIGHT>){RECORD_DELIM}

最后一行写: {COMPLETION_DELIM}

## 字段说明:
- NAME: 实体名 (中文优先, 数据表 / 字段名用英文 snake_case 原样)
- TYPE: 必须是上面 7 种之一 (spec_doc/data_table/field/ui_state/masking_rule/api_endpoint/page_concept)
- DESCRIPTION: 一句话, ≤60 字
- ALIASES: 同义词 / 别名 (用 `|` 分隔). **强烈建议给至少 1 个**: 中文名给英文别名, 英文名给中文别名; 概念页给"短名 / 关键词缩写"; 数据表给"业务俗称 / 文档中常用叫法". 实在没有变体才写 "无".
- SRC_NAME / TGT_NAME: 关系两端实体名, 必须跟前面 entity 的 NAME 一致 (大小写敏感)
- RELATION_TYPE: 自由短词 (如 "依赖" / "属于" / "脱敏" / "包含字段")
- WEIGHT: 关系强度 1-10 整数, 默认 5

## 抽取要求:
1. **保留原 wiki 链接形式**: wiki 里的 `[[xxx]]` 引用对应 entity, 把 `xxx` 当 NAME
2. **alias 优先填**: 同一概念页标题 / frontmatter 内 title / 正文里出现的关键词缩写都应进 ALIASES (例: "诉前调解PRD评审" 别名 "诉前调解评审|PRD评审"); 数据表如 ds_risk_court_lian 别名 "司法案件主表|立案信息表"
3. **字段 entity 用 `<table>.<field>` 格式**: 如 ds_risk_labour_arbitration.title (避免 field name 撞名)
4. **不要重复**: 同名同类型的 entity 只抽一次
5. **关系要有意义**: 不要硬凑 "页面 A 提到 页面 B" 这种弱关系, 至少表达"依赖/包含/脱敏/约束"等业务语义
6. **抽取颗粒度**: 概念页里的具体业务名词 (规则 / 字段 / 状态 / 接口) 都要单独成 entity, 不要把整段话压成 1 个 page_concept; 短页 (<500 字) 至少抽 3-5 个 entity, 长页按内容多抽

## 示例:
("entity"{TUPLE_DELIM}ds_risk_labour_arbitration{TUPLE_DELIM}data_table{TUPLE_DELIM}劳动仲裁主表, 存仲裁公告基础信息{TUPLE_DELIM}劳动仲裁主表|主表){RECORD_DELIM}
("entity"{TUPLE_DELIM}ds_risk_labour_arbitration.title{TUPLE_DELIM}field{TUPLE_DELIM}公告标题字段, varchar(500){TUPLE_DELIM}无){RECORD_DELIM}
("relationship"{TUPLE_DELIM}ds_risk_labour_arbitration{TUPLE_DELIM}ds_risk_labour_arbitration.title{TUPLE_DELIM}包含字段{TUPLE_DELIM}主表的标题列{TUPLE_DELIM}8){RECORD_DELIM}
{COMPLETION_DELIM}

请严格按上面格式输出, 不要任何额外说明文字."""


_GLEANING_PROMPT = """上一轮抽取已完成. 现在请检查是否还有遗漏的实体或关系 — 重点关注:
1. wiki 里出现但未抽出的 [[页面引用]]
2. 表里列举的字段但没建 entity 的
3. UI 状态 / 脱敏规则 / API 接口的隐式提及

如果有遗漏, 用同样的 tuple-delimited 格式补充输出 (不要重复已抽出的);
如果没有遗漏, 只输出 <|COMPLETE|>.

不要 JSON, 不要 markdown 代码块, 直接输出 tuple."""


# ============================================================
# 工具: short hash + 解析
# ============================================================

def _short_hash(text: str, length: int = 8) -> str:
    """sha1 前 length 位作为 entity_id."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def _entity_id(name: str, etype: str) -> str:
    """entity_id = e_<sha1(name+type)前8位>."""
    return "e_" + _short_hash(f"{etype}:{name}")


def _relation_id(src_id: str, tgt_id: str, relation_type: str) -> str:
    """relation_id = r_<sha1(src+tgt+type)前8位>."""
    return "r_" + _short_hash(f"{src_id}->{tgt_id}:{relation_type}")


def _parse_tuple_line(line: str) -> Tuple[str, List[str]] | Tuple[None, None]:
    """解析一条 tuple 记录, 返回 (kind, fields) 或 (None, None).

    kind: 'entity' | 'relationship'
    fields: 不含 kind 的剩余字段列表
    """
    line = line.strip()
    if not line or COMPLETION_DELIM in line:
        return None, None
    # 容错去掉行尾 RECORD_DELIM 与括号
    line = line.rstrip(RECORD_DELIM).strip()
    if line.startswith("(") and line.endswith(")"):
        line = line[1:-1]
    elif line.startswith("("):
        line = line[1:]
    parts = line.split(TUPLE_DELIM)
    if len(parts) < 4:
        return None, None
    kind = parts[0].strip().strip('"').strip("'").lower()
    if kind not in ("entity", "relationship"):
        return None, None
    return kind, [p.strip().strip('"').strip("'") for p in parts[1:]]


def _parse_extraction(text: str) -> Tuple[List[Dict], List[Dict]]:
    """把 LLM 抽出的 tuple 文本解析成 entities + relations 两个 list."""
    entities = []
    relations = []
    # 按 RECORD_DELIM 切, 兼容 LLM 不严格换行
    chunks = re.split(rf"{re.escape(RECORD_DELIM)}\s*\n?", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # 一个 chunk 可能含多行, 但有效 tuple 就一行
        for line in chunk.splitlines():
            kind, fields = _parse_tuple_line(line)
            if kind == "entity" and len(fields) >= 4:
                name, etype, desc = fields[0], fields[1].lower(), fields[2]
                aliases_raw = fields[3] if len(fields) > 3 else ""
                aliases = []
                if aliases_raw and aliases_raw.lower() not in ("无", "none", "null", "n/a"):
                    aliases = [a.strip() for a in aliases_raw.split("|") if a.strip()]
                if etype not in ENTITY_TYPES:
                    # 类型不合法 — 兜底归到 page_concept
                    etype = "page_concept"
                if not name:
                    continue
                entities.append({
                    "name": name,
                    "type": etype,
                    "description": desc,
                    "aliases": aliases,
                })
            elif kind == "relationship" and len(fields) >= 4:
                src, tgt, rtype, rdesc = fields[0], fields[1], fields[2], fields[3]
                weight_raw = fields[4] if len(fields) > 4 else "5"
                try:
                    weight = int(re.search(r"\d+", weight_raw).group()) if re.search(r"\d+", weight_raw) else 5
                except (AttributeError, ValueError):
                    weight = 5
                if not src or not tgt:
                    continue
                relations.append({
                    "source_name": src,
                    "target_name": tgt,
                    "relation_type": rtype,
                    "description": rdesc,
                    "weight": min(max(weight, 1), 10),
                })
    return entities, relations


# ============================================================
# LLM 调用 (走 model_router verify.nli 路由 = DeepSeek-flash)
# ============================================================

def _call_llm(system: str, user: str, max_tokens: int = 8192) -> str:
    """走 verify.nli (DeepSeek-flash) 抽实体. 返回纯文本.

    max_tokens: 默认 8192 (DeepSeek-flash 上限). 老调用点继续传 4096 以兼容.
    """
    from model_router import route_call
    resp = route_call(
        "verify.nli",
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.1,   # 抽取场景温度调低保稳定
    )
    text_parts = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            text_parts.append(getattr(block, "text", ""))
    return "".join(text_parts)


# ============================================================
# DDL 大页分块策略 (单页 >1500 字 + 含 SQL/markdown 表 → 切段抽取)
# ============================================================

# 切段标记 — 优先级从高到低 (越靠前越粗粒度, 越好维持语义完整性)
# 1) DDL 专属 (## 表名 / ### N. 表 / #### 子节 / ## JOIN)
# 2) 通用 markdown 二级标题 (## ...) — 大多 wiki 业务页用 ## 划分章节
# 3) 通用 markdown 三级标题 (### ...) — fallback
_CHUNK_SPLIT_PATTERNS = [
    re.compile(r"^###\s+\d+\.\s+", re.MULTILINE),     # ### 1. 直接投资表
    re.compile(r"^####\s+", re.MULTILINE),             # #### 子节
    re.compile(r"^##\s+(?:JOIN|跨表|表关系|降级处理)", re.MULTILINE),  # 关系表
    re.compile(r"^##\s+", re.MULTILINE),               # 通用二级标题
    re.compile(r"^###\s+", re.MULTILINE),              # 通用三级标题
]
_DDL_KEYWORDS = ("CREATE TABLE", "| 字段名 |", "| Field |", "JOIN", "PostgreSQL", "MySQL")
_LARGE_PAGE_THRESHOLD = 1500   # 单页字符数, 超过则尝试切块抽取
_MIN_CHUNK_CHARS = 300         # 切出的单 chunk 至少这么多字, 避免过碎


def _looks_like_ddl_page(content: str) -> bool:
    """启发式: 内容含 ≥2 个 DDL 关键字且 ≥1500 字 → 视为 DDL/大表页 (会用更激进的切块阈值)."""
    if len(content) < _LARGE_PAGE_THRESHOLD:
        return False
    hits = sum(1 for kw in _DDL_KEYWORDS if kw in content)
    return hits >= 2


def _looks_like_large_page(content: str) -> bool:
    """启发式: 普通业务 wiki 页面 ≥1500 字 (不含 DDL 关键字) 也建议切块, 避免漏抽."""
    return len(content) >= _LARGE_PAGE_THRESHOLD


def _split_by_paragraphs(content: str, target_chars: int = 1500) -> List[str]:
    """按双换行 (段落级) 切, 累计到 target_chars 一段, 用作 fallback."""
    paras = re.split(r"\n\s*\n", content)
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if buf_len + len(p) > target_chars and buf:
            chunks.append("\n\n".join(buf))
            buf = [p]
            buf_len = len(p)
        else:
            buf.append(p)
            buf_len += len(p)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _split_ddl_page(content: str) -> List[str]:
    """把大页按 ### 表名 / #### 表名 / ## ... / ### ... / 段落 切段, 每段独立抽取.

    返回切段后的 chunk 列表 (≥1). 若所有 markdown 标题策略都不可分, 退回段落聚合切块。
    """
    # 1. 优先 markdown 标题策略
    for pat in _CHUNK_SPLIT_PATTERNS:
        positions = [m.start() for m in pat.finditer(content)]
        if len(positions) < 2:
            continue
        chunks = []
        # 头部 (positions[0] 之前的 frontmatter / 引言)
        head = content[:positions[0]].strip()
        if len(head) > 100:
            chunks.append(head)
        for i, start in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(content)
            seg = content[start:end].strip()
            if len(seg) >= _MIN_CHUNK_CHARS:
                chunks.append(seg)
        if len(chunks) >= 2:
            return chunks
    # 2. fallback: 段落聚合切块 (当全文一段没标题时, 至少不漏抽)
    para_chunks = _split_by_paragraphs(content, target_chars=1500)
    if len(para_chunks) >= 2:
        return para_chunks
    # 3. 真切不动 → 整页一块
    return [content]


def _adaptive_gleaning_rounds(page_text: str, default_max: int) -> int:
    """根据页长度自适应调整 gleaning 轮数 — 性能优化 #3.

    - 小页 (≤500 字): 1 轮 (大概率没遗漏, 省时间)
    - 中页 (500-2000 字): 沿用 default
    - 大页 (>2000 字): max(default, 3) — 大页更可能漏
    """
    if default_max <= 0:
        return 0
    n = len(page_text)
    if n <= 500:
        return min(default_max, 1)
    if n > 2000:
        return max(default_max, 3)
    return default_max


def _extract_one_page(page_text: str, page_title: str, max_gleanings: int = 2,
                      adaptive: bool = True, max_tokens: int = 8192,
                      enable_chunking: bool = True) -> Tuple[List[Dict], List[Dict]]:
    """对单个 wiki 页面跑抽取 + gleaning loop. 返回 (entities, relations).

    Args:
        adaptive: True 则按页面长度自适应 gleaning 轮数 (优化 #3)
        max_tokens: LLM 每次返回 token 上限. 默认 8192; DeepSeek-flash 支持上限.
        enable_chunking: True 则对大页 (>1500 字) 自动按标题/段落切段抽取.
    """
    # ---- 大页分块: 防 max_tokens 截断 + 提升抽取召回 ----
    # DDL 大页和普通业务大页都走切块, 标记不同便于日志区分
    is_ddl = _looks_like_ddl_page(page_text)
    is_large = _looks_like_large_page(page_text)
    if enable_chunking and (is_ddl or is_large):
        chunks = _split_ddl_page(page_text)
        if len(chunks) >= 2:
            tag = "DDL-CHUNK" if is_ddl else "LARGE-CHUNK"
            print(f"    [{tag}] 切成 {len(chunks)} 段 (原 {len(page_text)} 字)")
            all_ents: List[Dict] = []
            all_rels: List[Dict] = []
            for i, chunk in enumerate(chunks, 1):
                sub_title = f"{page_title} [chunk {i}/{len(chunks)}]"
                # 单段抽取, 关闭 chunking 防递归
                ents, rels = _extract_one_page(
                    chunk, sub_title,
                    max_gleanings=max_gleanings,
                    adaptive=adaptive,
                    max_tokens=max_tokens,
                    enable_chunking=False,
                )
                all_ents.extend(ents)
                all_rels.extend(rels)
                print(f"    [{tag} {i}/{len(chunks)}] {len(ents)} ent / {len(rels)} rel")
            return all_ents, all_rels

    user_msg = f"## 页面标题\n{page_title}\n\n## 页面内容\n{page_text[:6000]}"  # 截断超长页

    eff_gleanings = _adaptive_gleaning_rounds(page_text, max_gleanings) if adaptive else max_gleanings

    # 第一轮: 主抽取
    raw = _call_llm(_EXTRACTION_PROMPT, user_msg, max_tokens=max_tokens)
    entities, relations = _parse_extraction(raw)

    # gleaning loop: eff_gleanings 轮"是否还有遗漏"
    for round_idx in range(eff_gleanings):
        # 构造 gleaning user msg: 含已抽出的实体名字以提示 LLM 不要重复
        already_names = ", ".join(e["name"] for e in entities[-30:])  # 太多会撑爆 prompt
        gleaning_user = (
            f"## 原页面标题\n{page_title}\n\n"
            f"## 原页面内容\n{page_text[:6000]}\n\n"
            f"## 已抽出的实体名 (不要重复抽)\n{already_names}\n\n"
            f"{_GLEANING_PROMPT}"
        )
        # gleaning 用一半 max_tokens 节省
        raw_g = _call_llm(_EXTRACTION_PROMPT, gleaning_user, max_tokens=max(2048, max_tokens // 2))
        if COMPLETION_DELIM in raw_g and len(raw_g.strip()) < 100:
            # LLM 说没遗漏了
            break
        new_entities, new_relations = _parse_extraction(raw_g)
        if not new_entities and not new_relations:
            break
        entities.extend(new_entities)
        relations.extend(new_relations)
        print(f"    gleaning #{round_idx+1}: +{len(new_entities)} entity, +{len(new_relations)} relation")

    return entities, relations


# ============================================================
# 公共工具: meta 文件判定 / wiki dir 列页 / 写 KG
# ============================================================

_META_FILES = {"index.md", "log.md", "readme.md", "toc.md"}


def is_meta_page(relpath_or_basename: str) -> bool:
    """判断是否元文件 (index/log/readme/toc), 元文件无业务实体, 抽取时跳过."""
    bn = os.path.basename(relpath_or_basename).lower()
    return bn in _META_FILES


def _wiki_max_mtime(wiki_dir: str) -> float:
    """wiki/ 目录所有 .md 的最大 mtime (含子目录, 跳过 _kg/), 用于断点续跑判定."""
    max_m = 0.0
    for root, dirs, files in os.walk(wiki_dir):
        dirs[:] = [d for d in dirs if d != "_kg" and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            try:
                m = os.path.getmtime(os.path.join(root, fn))
                if m > max_m:
                    max_m = m
            except OSError:
                continue
    return max_m


def kg_is_fresh(out_dir: str, wiki_dir: str) -> bool:
    """断点续跑: out_dir/entities.json 存在且 mtime > 任一 wiki md mtime → 视为新鲜可跳过."""
    ents = os.path.join(out_dir, "entities.json")
    if not os.path.isfile(ents):
        return False
    try:
        kg_mtime = os.path.getmtime(ents)
    except OSError:
        return False
    return kg_mtime >= _wiki_max_mtime(wiki_dir)


def _write_kg_outputs(out_dir: str, entities: List[Dict], relations: List[Dict],
                      meta: Dict[str, Any]) -> Tuple[str, str, str]:
    """写 entities.json + relations.json + meta.json. 返回三个路径."""
    os.makedirs(out_dir, exist_ok=True)
    ents_path = os.path.join(out_dir, "entities.json")
    rels_path = os.path.join(out_dir, "relations.json")
    meta_path = os.path.join(out_dir, "meta.json")
    with open(ents_path, "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)
    with open(rels_path, "w", encoding="utf-8") as f:
        json.dump(relations, f, ensure_ascii=False, indent=2)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return ents_path, rels_path, meta_path


def extract_page(relpath: str, content: str, max_gleanings: int = 2,
                 adaptive: bool = True, max_tokens: int = 8192,
                 enable_chunking: bool = True) -> Tuple[List[Dict], List[Dict], Dict[str, Any]]:
    """高层 API: 抽一页, 返回 (entities, relations, page_metric).

    page_metric: {relpath, chars, gleaning_rounds, entities, relations, elapsed_s, chunked?}
    元文件直接返回空列表 + meta 标 skipped.

    Args:
        max_tokens: LLM 输出上限, 默认 4096; DDL 大页传 8192 防截断.
        enable_chunking: 默认 True, 大 DDL 页会自动切段抽取.
    """
    if is_meta_page(relpath):
        return [], [], {"relpath": relpath, "skipped": True, "reason": "meta_page"}
    page_title = relpath.rsplit(".", 1)[0]
    eff_g = _adaptive_gleaning_rounds(content, max_gleanings) if adaptive else max_gleanings
    is_ddl = enable_chunking and _looks_like_ddl_page(content)
    t0 = time.time()
    ents, rels = _extract_one_page(
        content, page_title,
        max_gleanings=max_gleanings,
        adaptive=adaptive,
        max_tokens=max_tokens,
        enable_chunking=enable_chunking,
    )
    for e in ents:
        e["source_page"] = relpath
    elapsed = round(time.time() - t0, 1)
    metric = {
        "relpath": relpath,
        "chars": len(content),
        "gleaning_rounds": eff_g,
        "entities_raw": len(ents),
        "relations_raw": len(rels),
        "elapsed_s": elapsed,
        "skipped": False,
        "ddl_chunked": is_ddl,
        "max_tokens": max_tokens,
    }
    return ents, rels, metric


# ============================================================
# 去重 + 合并 + ID 分配
# ============================================================

def _dedupe_and_assign_ids(
    raw_entities: List[Dict],
    raw_relations: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """去重 entities (按 name+type), 合并 aliases. 给 entity/relation 加上 short hash id.

    去重策略:
    - 同 name + 同 type → 合并为 1 条, aliases 取并集, description 选最长的
    - 不同 type 同 name → 保留两条 (字段名跟概念名可能撞)

    relation 去重: 同 src_id + tgt_id + relation_type → 合并 (weight 取大)
    relation 也会做 name → id 映射, 找不到 entity 的 relation 直接丢弃 + log.
    """
    # 1. entity 去重
    by_key: Dict[str, Dict] = {}   # key = "name|type"
    for ent in raw_entities:
        key = f"{ent['name']}|{ent['type']}"
        if key not in by_key:
            by_key[key] = {
                "id": _entity_id(ent["name"], ent["type"]),
                "title": ent["name"],
                "type": ent["type"],
                "description": ent.get("description", ""),
                "aliases": list(set(ent.get("aliases", []))),
                "source_pages": [ent.get("source_page", "")] if ent.get("source_page") else [],
            }
        else:
            # 合并: aliases 并集, description 选更长的, source_pages 加入
            existing = by_key[key]
            new_aliases = set(existing["aliases"]) | set(ent.get("aliases", []))
            existing["aliases"] = sorted(new_aliases)
            new_desc = ent.get("description", "")
            if len(new_desc) > len(existing.get("description", "")):
                existing["description"] = new_desc
            sp = ent.get("source_page", "")
            if sp and sp not in existing["source_pages"]:
                existing["source_pages"].append(sp)

    # 2. 建 name → id 索引 (alias 也算)
    name_to_id: Dict[str, str] = {}
    for ent in by_key.values():
        name_to_id[ent["title"]] = ent["id"]
        for alias in ent["aliases"]:
            # alias 可能跟 title 撞名 — title 优先, 不覆盖
            name_to_id.setdefault(alias, ent["id"])

    # 3. relation 去重 + 解析 src/tgt 名字到 id
    rel_by_key: Dict[str, Dict] = {}
    dropped = 0
    for rel in raw_relations:
        src_name = rel["source_name"]
        tgt_name = rel["target_name"]
        src_id = name_to_id.get(src_name)
        tgt_id = name_to_id.get(tgt_name)
        if not src_id or not tgt_id:
            # 引用了不存在的 entity — 丢弃
            dropped += 1
            continue
        rkey = f"{src_id}|{tgt_id}|{rel['relation_type']}"
        if rkey not in rel_by_key:
            rel_by_key[rkey] = {
                "id": _relation_id(src_id, tgt_id, rel["relation_type"]),
                "source_id": src_id,
                "target_id": tgt_id,
                "relation_type": rel["relation_type"],
                "description": rel.get("description", ""),
                "weight": rel.get("weight", 5),
            }
        else:
            # 同关系再次出现 — weight 取大, description 选长
            existing = rel_by_key[rkey]
            existing["weight"] = max(existing["weight"], rel.get("weight", 5))
            new_desc = rel.get("description", "")
            if len(new_desc) > len(existing.get("description", "")):
                existing["description"] = new_desc

    if dropped:
        # 用 ASCII [warn] 替代 ⚠ 防 windows GBK 控制台编码崩 (UnicodeEncodeError)
        print(f"  [warn] 丢弃 {dropped} 条引用了不存在 entity 的 relation")

    return list(by_key.values()), list(rel_by_key.values())


# ============================================================
# 主流程
# ============================================================

def _walk_wiki_md(wiki_dir: str) -> List[Tuple[str, str]]:
    """递归扫 wiki_dir 下所有 .md, 返回 [(relpath, content), ...].

    跳过 _kg/ 目录 (本脚本输出) 和 . 开头的隐藏文件.
    """
    pages = []
    for root, dirs, files in os.walk(wiki_dir):
        # 跳过 _kg/ 输出目录
        dirs[:] = [d for d in dirs if d != "_kg" and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".md") or fn.startswith("."):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                print(f"  [warn] 读取失败 {fpath}: {e}")
                continue
            relpath = os.path.relpath(fpath, wiki_dir).replace("\\", "/")
            pages.append((relpath, content))
    return pages


def build_kg(wiki_dir: str, out_dir: str, max_pages: int = 0, max_gleanings: int = 2,
             max_tokens: int = 8192, only_pages: Optional[List[str]] = None,
             enable_chunking: bool = True) -> Dict[str, Any]:
    """主入口: 扫 wiki_dir, 抽 entity+relation, 写 entities.json + relations.json 到 out_dir.

    Args:
        max_tokens: LLM 输出上限, 默认 4096. DDL 大页传 8192.
        only_pages: 只抽指定 relpath (basename 匹配亦可), None 则抽全部.
        enable_chunking: 大 DDL 页是否自动切段, 默认 True.
    """
    os.makedirs(out_dir, exist_ok=True)
    pages = _walk_wiki_md(wiki_dir)
    if only_pages:
        # 兼容传入 basename 或 relpath
        wanted = set(only_pages)
        pages = [(rp, ct) for rp, ct in pages if rp in wanted or os.path.basename(rp) in wanted]
        print(f"=== --pages 过滤后保留 {len(pages)} 页 ===")
    if max_pages and max_pages > 0:
        pages = pages[:max_pages]
    print(f"=== 扫到 {len(pages)} 个 wiki 页面 (gleaning_max={max_gleanings}, "
          f"max_tokens={max_tokens}, chunking={enable_chunking}) ===")

    raw_entities: List[Dict] = []
    raw_relations: List[Dict] = []
    failed_pages: List[str] = []
    t0 = time.time()

    for idx, (relpath, content) in enumerate(pages, 1):
        # 元文件 (index/log/README/TOC) 跳过 — 没业务实体
        basename = os.path.basename(relpath).lower()
        if basename in ("index.md", "log.md", "readme.md", "toc.md"):
            print(f"[{idx}/{len(pages)}] {relpath}  (跳过元文件)")
            continue
        page_title = relpath.rsplit(".", 1)[0]
        print(f"[{idx}/{len(pages)}] {relpath} ({len(content)} 字)...")
        try:
            ents, rels = _extract_one_page(
                content, page_title,
                max_gleanings=max_gleanings,
                max_tokens=max_tokens,
                enable_chunking=enable_chunking,
            )
            for e in ents:
                e["source_page"] = relpath
            raw_entities.extend(ents)
            raw_relations.extend(rels)
            print(f"    -> {len(ents)} entity, {len(rels)} relation")
        except Exception as exc:
            failed_pages.append(relpath)
            print(f"    [fail] 抽取失败: {exc}")

    # 去重 + 分配 id
    print(f"\n=== 去重 + 分配 ID (raw: {len(raw_entities)} ent, {len(raw_relations)} rel) ===")
    entities, relations = _dedupe_and_assign_ids(raw_entities, raw_relations)
    print(f"=== 本次新抽: {len(entities)} entity, {len(relations)} relation ===")

    # ---- only_pages 模式: 与现有 KG 合并, 保留其他页面的实体 ----
    merged_with_existing = False
    if only_pages:
        ents_path_old = os.path.join(out_dir, "entities.json")
        rels_path_old = os.path.join(out_dir, "relations.json")
        if os.path.isfile(ents_path_old) and os.path.isfile(rels_path_old):
            try:
                with open(ents_path_old, "r", encoding="utf-8") as f:
                    old_entities = json.load(f)
                with open(rels_path_old, "r", encoding="utf-8") as f:
                    old_relations = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"  [warn] 读取已有 KG 失败 ({e}), 跳过合并")
                old_entities, old_relations = [], []
            else:
                # 移除来自本次抽取页面的旧实体 / 旧关系 (按 source_pages 过滤)
                pages_set = set(p.replace("\\", "/") for p in (only_pages or []))
                # 兼容传 basename
                pages_basenames = set(os.path.basename(p) for p in (only_pages or []))
                def _from_target_page(srcs: List[str]) -> bool:
                    for s in (srcs or []):
                        if s in pages_set or os.path.basename(s) in pages_basenames:
                            return True
                    return False

                kept_entities = [e for e in old_entities if not _from_target_page(e.get("source_pages", []))]
                # entity id 映射
                kept_ids = set(e["id"] for e in kept_entities)
                # relation 保留: src_id 和 tgt_id 都在 kept 里
                kept_relations = [r for r in old_relations
                                  if r.get("source_id") in kept_ids and r.get("target_id") in kept_ids]

                # 合并新抽
                new_ids = set(e["id"] for e in entities)
                merged_ids = kept_ids | new_ids
                # 旧 entity 若新 entity 同 id 已覆盖, 老的 source_pages / aliases 应合并保留
                by_id = {e["id"]: e for e in kept_entities}
                for ne in entities:
                    if ne["id"] in by_id:
                        ex = by_id[ne["id"]]
                        ex["aliases"] = sorted(set(ex.get("aliases", [])) | set(ne.get("aliases", [])))
                        sp_set = list(dict.fromkeys((ex.get("source_pages") or []) + (ne.get("source_pages") or [])))
                        ex["source_pages"] = sp_set
                        if len(ne.get("description", "")) > len(ex.get("description", "")):
                            ex["description"] = ne["description"]
                    else:
                        by_id[ne["id"]] = ne
                merged_entities = list(by_id.values())
                # relation: 同 id 用新覆盖
                rel_by_id = {r["id"]: r for r in kept_relations}
                for nr in relations:
                    rel_by_id[nr["id"]] = nr
                # 过滤孤立 relation
                final_ids = set(e["id"] for e in merged_entities)
                merged_relations = [r for r in rel_by_id.values()
                                     if r.get("source_id") in final_ids and r.get("target_id") in final_ids]

                print(f"=== 合并: 旧保留 {len(kept_entities)} ent / {len(kept_relations)} rel; "
                      f"新增 {len(entities) - len(set(e['id'] for e in entities) & kept_ids)} ent")
                entities = merged_entities
                relations = merged_relations
                merged_with_existing = True
                print(f"=== 合并后: {len(entities)} entity, {len(relations)} relation ===")

    # 写 JSON (utf-8, 兼容 windows GBK 控制台)
    ents_path = os.path.join(out_dir, "entities.json")
    rels_path = os.path.join(out_dir, "relations.json")
    with open(ents_path, "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)
    with open(rels_path, "w", encoding="utf-8") as f:
        json.dump(relations, f, ensure_ascii=False, indent=2)

    # 元数据
    meta = {
        "wiki_dir": wiki_dir,
        "pages_scanned": len(pages),
        "pages_failed": failed_pages,
        "entities_count": len(entities),
        "relations_count": len(relations),
        "by_type": {},
        "elapsed_seconds": round(time.time() - t0, 1),
        "max_gleanings": max_gleanings,
        "max_tokens": max_tokens,
        "merged_with_existing": merged_with_existing,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    for e in entities:
        meta["by_type"][e["type"]] = meta["by_type"].get(e["type"], 0) + 1
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\n=== 写入 ===\n  {ents_path}\n  {rels_path}\n  {meta_path}")
    print(f"=== 类型分布: {meta['by_type']} ===")
    print(f"=== 耗时 {meta['elapsed_seconds']}s ===")
    return meta


# ============================================================
# 公共别名 (供 build_kg_all / wiki_kg_watcher 复用)
# ============================================================

walk_wiki_md = _walk_wiki_md
dedupe_and_assign_ids = _dedupe_and_assign_ids


def main():
    parser = argparse.ArgumentParser(description="抽 wiki 实体+关系到 _kg/ 目录")
    parser.add_argument("--workspace", default="workspace-劳动仲裁", help="目标 workspace 名 (含 wiki/ 子目录)")
    parser.add_argument("--max-pages", type=int, default=0, help="只抽前 N 页 (0=全部)")
    parser.add_argument("--max-gleanings", type=int, default=2, help="gleaning 轮数 (默认 2)")
    parser.add_argument("--no-gleaning", action="store_true", help="跳过 gleaning loop")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="LLM 单次返回 token 上限 (默认 8192; DeepSeek-flash 上限)")
    parser.add_argument("--force", action="store_true",
                        help="强制重抽 (跳过 kg_is_fresh 断点续跑判定)")
    parser.add_argument("--pages", default="",
                        help="逗号分隔, 只抽指定页 (basename 或 relpath); 例: DDL.md,跨表关系.md")
    parser.add_argument("--no-chunking", action="store_true",
                        help="禁用 DDL 大页自动分块 (默认开启)")
    args = parser.parse_args()

    workspace_dir = _ROOT / args.workspace
    if not workspace_dir.is_dir():
        print(f"[fail]workspace 不存在: {workspace_dir}", file=sys.stderr)
        sys.exit(2)
    wiki_dir = workspace_dir / "wiki"
    if not wiki_dir.is_dir():
        print(f"[fail]wiki 目录不存在: {wiki_dir}", file=sys.stderr)
        sys.exit(2)
    out_dir = wiki_dir / "_kg"

    max_gleanings = 0 if args.no_gleaning else args.max_gleanings
    only_pages = [p.strip() for p in args.pages.split(",") if p.strip()] or None

    # --force 不传 + KG 已存在且新鲜 → 跳过 (only_pages 模式总是重抽指定页, 不走 fresh)
    if not args.force and not only_pages and kg_is_fresh(str(out_dir), str(wiki_dir)):
        print(f"[fresh] {out_dir} 已是最新, 跳过 (传 --force 强制重抽)")
        return
    build_kg(
        str(wiki_dir), str(out_dir),
        max_pages=args.max_pages,
        max_gleanings=max_gleanings,
        max_tokens=args.max_tokens,
        only_pages=only_pages,
        enable_chunking=not args.no_chunking,
    )


if __name__ == "__main__":
    main()
