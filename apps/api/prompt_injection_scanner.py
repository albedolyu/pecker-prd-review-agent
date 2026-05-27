"""prompt_injection_scanner.py — PRD 正文 / 补充资料里的典型 prompt injection 检测.

为什么做 (2026-04-23 C 优化, memory: gate v2 第 7 层安全):
PRD / 补充资料是外部用户输入, 会原文进 worker system+user prompt. 若 PRD 里
塞 "ignore all previous instructions", worker LLM 可能服从而不是按 checklist
评审.

本扫描器是**低强度启发式**, 识别典型 jailbreak pattern, 只 warn-only 不 block
(技术 PRD 可能合法出现"忽略"/"指令"/"系统提示"等词). 结果挂到 review 响应里
让前端可选显示"本次 PRD 检测到 N 处可疑指令, 请人工确认".

不做强检测的原因:
- 强阻断会误伤正常文档 (API 文档里真的会说 "ignore the 'example' prefix")
- 真正攻击者可以用变体绕过, 靠字符串匹配止不住
- 当前威胁模型是"无意识污染"而非"恶意攻击者", 提醒比拦截更实用

未来可升级:
- 加 Claude 级语义判定 (贵)
- 加严格模式 env `PECKER_STRICT_INJECTION=1` 直接 block
- 对 raw_materials 和 PRD body 分别评估
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


# 典型 jailbreak / injection pattern. 每条会 compile 一次, 调用点廉价.
# 英文 + 中文混合, 按真实场景命中率排序.
_PATTERNS = [
    # "ignore all previous instructions" 经典攻击
    (r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:above|previous|prior|preceding)[^\n]{0,40}?(?:instructions?|rules?|prompts?|directives?)\b", "jailbreak_ignore"),
    (r"(?:忽略|无视)(?:以上|之前|上面|前面)[^\n]{0,20}?(?:指令|规则|提示|命令)", "jailbreak_ignore_cn"),

    # "you are now X" 角色覆写
    (r"\byou\s+are\s+now\s+(?:an?|the)?\s*[a-z][^\n.]{0,60}", "role_override"),
    (r"(?:你现在是|你是一个|从现在起你是)[^\n。]{0,40}", "role_override_cn"),

    # "forget your role / system prompt"
    (r"\bforget\s+(?:your\s+|everything\s+|all\s+)(?:role|system|instructions|rules)\b", "forget_role"),
    (r"(?:忘记|遗忘)(?:你的|之前的)(?:角色|系统|指令|规则)", "forget_role_cn"),

    # 系统 prompt 标签注入
    (r"<\|(?:im_start|im_end|system|endoftext)\|>", "chat_template_inject"),
    (r"###\s*(?:instruction|system|assistant|user)\s*(?::|\n)", "instruction_marker"),

    # DAN / developer mode 类
    (r"\b(?:DAN|developer\s+mode|jailbreak\s+mode)\b", "dan_mode"),

    # "output in format X bypassing" 绕过
    (r"\b(?:bypass|circumvent|override)\s+(?:the\s+)?(?:safety|filter|guard|rule)", "bypass_intent"),
]

# 预编译正则, import 时一次性完成
_COMPILED = [(re.compile(p, re.IGNORECASE | re.MULTILINE), tag) for p, tag in _PATTERNS]


@dataclass
class InjectionHit:
    tag: str          # pattern 标签, 如 "jailbreak_ignore"
    line: int         # 1-based 行号
    excerpt: str      # 命中片段(周围 ~60 字符), 方便 PM 快速定位

    def to_dict(self) -> dict:
        return {"tag": self.tag, "line": self.line, "excerpt": self.excerpt}


def scan(text: str, max_hits: int = 10) -> List[InjectionHit]:
    """扫 text, 返回命中列表. 超 max_hits 截断 (防恶意输入洪水淹没响应)."""
    if not text:
        return []
    hits: List[InjectionHit] = []
    for regex, tag in _COMPILED:
        for m in regex.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            excerpt = text[start:end].replace("\n", " ").strip()
            hits.append(InjectionHit(tag=tag, line=line, excerpt=excerpt[:120]))
            if len(hits) >= max_hits:
                return hits
    return hits


def summarize(hits: List[InjectionHit]) -> dict:
    """把 InjectionHit list 转成给 API response 用的 dict."""
    if not hits:
        return {"risk": False, "hit_count": 0, "hits": []}
    # 去重: 同一 tag 只报首次, 避免重复噪声
    seen_tags: set = set()
    unique: List[InjectionHit] = []
    for h in hits:
        if h.tag not in seen_tags:
            seen_tags.add(h.tag)
            unique.append(h)
    return {
        "risk": True,
        "hit_count": len(hits),  # 含重复
        "unique_tags": len(unique),
        "hits": [h.to_dict() for h in unique[:5]],  # 展示 top 5 去重后
    }


def scan_inputs(prd_content: str, raw_materials: List[str] | None = None,
                user_notes: str = "") -> dict:
    """一次性扫 PRD + raw_materials + user_notes 三个来源, 返回汇总 dict.

    这是 api/routes/review.py 的 precheck/run 入口唯一应该调的 API.
    """
    all_hits: List[InjectionHit] = []
    all_hits.extend(scan(prd_content or ""))
    if raw_materials:
        for i, rm in enumerate(raw_materials):
            for h in scan(rm or ""):
                # 给 raw_materials 的 tag 加前缀区分来源
                h.tag = f"rm{i}:{h.tag}"
                all_hits.append(h)
    if user_notes:
        for h in scan(user_notes):
            h.tag = f"notes:{h.tag}"
            all_hits.append(h)
    return summarize(all_hits)
