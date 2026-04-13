"""
啄木鸟 PRD 评审 — Web 版（完整交互版）

交互流程：
  1. 上传 PRD + 可选业务资料
  2. 知识盲区预检 + 用户补充
  3. 并行评审 + 进度展示
  4. 逐条确认（接受/驳回/修改）
  5. 生成最终报告 + 导出

启动: streamlit run app.py
"""

import streamlit as st
import os
import sys
import time
import json
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


# ============================================================
# 页面配置 & 样式
# ============================================================

st.set_page_config(
    page_title="啄木鸟 PRD 评审",
    page_icon="🪶",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
    .stApp { background: linear-gradient(170deg, #FAF7F2 0%, #F0EBE3 40%, #E8E0D4 100%); font-family: 'Noto Sans SC', sans-serif; }
    #MainMenu, footer, header { visibility: hidden; }
    .hero-title { font-family: 'Noto Serif SC', serif; font-size: 2.6rem; font-weight: 700; color: #2D5016; text-align: center; margin-top: 0.5rem; letter-spacing: 0.08em; }
    .hero-sub { font-size: 1rem; color: #7A6E5E; text-align: center; margin-bottom: 1.5rem; font-weight: 300; }
    .bird-badge { display: inline-block; background: linear-gradient(135deg, #2D5016, #3D6B22); color: #F5E6C8; padding: 3px 12px; border-radius: 20px; font-size: 0.78rem; font-weight: 500; margin: 2px 3px; }
    .bird-badge-amber { background: linear-gradient(135deg, #8B6914, #B8860B); }
    .bird-badge-red { background: linear-gradient(135deg, #7A1B2A, #9B2335); }
    .divider { height: 1px; background: linear-gradient(to right, transparent, #C4B8A8, transparent); margin: 1.5rem 0; }
    .phase-bar { display: flex; justify-content: center; gap: 0; margin: 1rem 0; }
    .phase-step { padding: 8px 18px; font-size: 0.85rem; font-weight: 500; border: 1px solid #C4B8A8; color: #999; background: rgba(255,255,255,0.5); }
    .phase-step:first-child { border-radius: 20px 0 0 20px; }
    .phase-step:last-child { border-radius: 0 20px 20px 0; }
    .phase-step.active { background: #2D5016; color: white; border-color: #2D5016; font-weight: 700; }
    .phase-step.done { background: #4A8C2A; color: white; border-color: #4A8C2A; }
    .stat-card { background: rgba(255,255,255,0.85); border-radius: 12px; padding: 1rem; text-align: center; border: 1px solid #E0D8CC; }
    .stat-number { font-family: 'Noto Serif SC', serif; font-size: 2rem; font-weight: 700; color: #2D5016; }
    .stat-label { font-size: 0.82rem; color: #7A6E5E; }
    .peck-gauge { background: rgba(255,255,255,0.9); border: 2px solid #2D5016; border-radius: 16px; padding: 1.2rem; text-align: center; }
    .peck-score { font-family: 'Noto Serif SC', serif; font-size: 2.8rem; font-weight: 700; color: #2D5016; }
    .peck-label { font-size: 1.1rem; color: #7A6E5E; }
    .dim-header { font-family: 'Noto Serif SC', serif; font-size: 1.2rem; color: #2D5016; border-bottom: 2px solid #D4A017; padding-bottom: 0.4rem; margin: 1.2rem 0 0.8rem 0; }
    .gap-card { background: #FFF8E7; border: 1px solid #E8D5A3; border-radius: 10px; padding: 1rem; margin: 0.5rem 0; }
    .footer-text { text-align: center; color: #B0A898; font-size: 0.78rem; margin-top: 2rem; padding-bottom: 1.5rem; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ============================================================
# Session State 初始化
# ============================================================

def init_state():
    defaults = {
        "phase": 0,           # 0=上传, 1=预检, 2=评审中, 3=确认, 4=报告
        "prd_content": "",
        "prd_name": "",
        "raw_materials": [],   # 补充资料列表
        "user_notes": "",      # 用户补充说明
        "review_result": None,
        "item_decisions": {},  # {R-001: {"action": "accept"|"reject"|"edit", "reason": ""}}
        "final_report": "",
        "wiki_path": os.environ.get("WIKI_PATH", "") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared-wiki"),
        "wiki_pages": {},      # 从 wiki 扫描得到的相关页面内容
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ============================================================
# 核心逻辑
# ============================================================

def get_client():
    from api_adapter import create_client
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    if not api_key:
        st.error("未配置 ANTHROPIC_API_KEY，请在 .env 中设置")
        return None
    return create_client(api_key=api_key, base_url=base_url)


def run_precheck(client, prd_content, raw_texts):
    """Phase 1: 知识盲区预检"""
    context = f"PRD 内容：\n{prd_content[:3000]}"
    if raw_texts:
        context += "\n\n补充资料：\n" + "\n---\n".join(t[:1000] for t in raw_texts)

    from agent_config import MODEL_TIERS
    response = client.create(
        model=MODEL_TIERS["sonnet"],
        max_tokens=2048,
        system="""你是啄木鸟知识盲区预检模块。分析 PRD 内容，输出以下 3 类信息（JSON 格式）：
{
  "strong": ["强相关的已知知识点"],
  "weak": ["弱相关的知识点"],
  "gaps": ["知识盲区——PRD 涉及但你没有足够信息判断的领域"]
}
每类最多 5 条。盲区要具体说明缺什么信息。""",
        messages=[{"role": "user", "content": context}],
    )
    text = response.content[0].text if response.content else "{}"
    try:
        m = re.search(r'\{[\s\S]*\}', text)
        return json.loads(m.group()) if m else {"strong": [], "weak": [], "gaps": []}
    except:
        return {"strong": [], "weak": [], "gaps": [], "raw": text}


def run_review(client, prd_content, raw_texts, user_notes, mode="standard"):
    """Phase 2: 执行评审"""
    from agent_config import MODEL_TIERS

    # 构建增强上下文
    enhanced_prd = prd_content
    if raw_texts:
        enhanced_prd += "\n\n---\n## 补充业务资料\n\n" + "\n---\n".join(raw_texts)
    if user_notes:
        enhanced_prd += f"\n\n---\n## 评审人补充说明\n\n{user_notes}"

    if mode == "quick":
        return _review_single(client, enhanced_prd, MODEL_TIERS["sonnet"])
    else:
        return _review_parallel(client, enhanced_prd, MODEL_TIERS)


def _review_single(client, prd_content, model):
    """快速模式：复用 parallel_review 的逻辑，但全部用 sonnet"""
    from parallel_review import parallel_review_sync
    from agent_config import MODEL_TIERS
    # 快速模式也走 4 维度，但全部用同一个 model（忽略 opus/haiku 分配）
    quick_tiers = {k: model for k in MODEL_TIERS}
    wiki_pages = st.session_state.get("wiki_pages", {})
    result = parallel_review_sync(client, prd_content, wiki_pages, quick_tiers)
    return {
        "items": result["merged_items"],
        "workers": result.get("workers", []),
        "usage": result.get("total_usage", {}),
        "mode": "quick",
    }


def _review_parallel(client, prd_content, model_tiers):
    import asyncio
    from parallel_review import parallel_review

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    wiki_pages = st.session_state.get("wiki_pages", {})
    result = asyncio.run(parallel_review(client, prd_content, wiki_pages, model_tiers))
    return {
        "items": result["merged_items"],
        "workers": result.get("workers", []),
        "usage": result.get("total_usage", {}),
        "mode": "standard",
    }


def _parse_items(text):
    m = re.search(r'\[[\s\S]*\]', text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # 回退解析
    items, seen = [], set()
    blocks = re.split(r'(R-\d+)', text)
    i = 1
    while i < len(blocks) - 1:
        rid = blocks[i]
        if rid not in seen:
            seen.add(rid)
            body = blocks[i + 1]
            items.append({
                "id": rid,
                "location": _xf(body, "位置"), "issue": _xf(body, "问题"),
                "suggestion": _xf(body, "建议"), "evidence_content": _xf(body, "依据"),
                "severity": "must" if "must" in body else "should",
                "dimension": "",
            })
        i += 2
    return items


def _xf(text, field):
    m = re.search(rf'(?:\*\*)?{field}(?:\*\*)?\s*[：:]\s*(.+?)(?:\n|$)', text)
    return m.group(1).strip() if m else ""


def calculate_peck(items):
    must = sum(1 for i in items if i.get("severity") == "must")
    should = sum(1 for i in items if i.get("severity") == "should")
    score = min(100, must * 8 + should * 3)
    for low, high, lbl, desc in [(0,15,"皮毛之伤","PRD 质量上乘"),(16,35,"轻伤","贴个创可贴就好"),
        (36,60,"中伤","建议复查一轮"),(61,80,"重伤","建议住院一个迭代"),(81,100,"危重","建议回炉重写")]:
        if low <= score <= high:
            return {"score": score, "label": lbl, "desc": desc, "must": must, "should": should}
    return {"score": score, "label": "?", "desc": "", "must": must, "should": should}


def generate_report(items, decisions, peck):
    """根据确认结果生成最终报告"""
    accepted = [i for i in items if decisions.get(i["id"], {}).get("action") == "accept"]
    rejected = [i for i in items if decisions.get(i["id"], {}).get("action") == "reject"]
    edited = [i for i in items if decisions.get(i["id"], {}).get("action") == "edit"]
    pending = [i for i in items if i["id"] not in decisions]

    lines = [
        "# PRD 改动报告", "",
        f"**评审时间**: {time.strftime('%Y-%m-%d %H:%M')}",
        f"**改进项总数**: {len(items)} 条",
        f"**已确认**: {len(accepted)} 条 | **已驳回**: {len(rejected)} 条 | **已修改**: {len(edited)} 条 | **待处理**: {len(pending)} 条",
        f"**啄伤度**: {peck['score']}/100 — {peck['label']}", "", "---", "",
    ]

    if accepted:
        lines += ["## 已确认改动清单", ""]
        for i in accepted:
            lines += [f"### {i['id']}（{i.get('severity','should')}）",
                f"- **位置**: {i.get('location','')}", f"- **问题**: {i.get('issue','')}",
                f"- **建议**: {i.get('suggestion','')}", f"- **依据**: {i.get('evidence_content','')}", ""]

    if edited:
        lines += ["## 已修改改动清单", ""]
        for i in edited:
            reason = decisions[i["id"]].get("reason", "")
            lines += [f"### {i['id']}（{i.get('severity','should')}）",
                f"- **原问题**: {i.get('issue','')}", f"- **修改意见**: {reason}", ""]

    if rejected:
        lines += ["## 已驳回项记录", ""]
        for i in rejected:
            reason = decisions[i["id"]].get("reason", "")
            lines += [f"### {i['id']}", f"- **问题**: {i.get('issue','')}", f"- **驳回理由**: {reason}", ""]

    if pending:
        lines += ["## 待处理项", ""]
        for i in pending:
            lines += [f"- {i['id']}: {i.get('issue','')}", ""]

    lines += ["---", "", "*由啄木鸟 PRD 评审 Agent 生成，请人工复核全部改动项。*"]
    return "\n".join(lines)


# ============================================================
# UI 组件
# ============================================================

def render_header():
    st.markdown('<div class="hero-title">🪶 啄木鸟</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">PRD 结构化评审 · 找不到依据的改动不提</div>', unsafe_allow_html=True)
    badges = '<span class="bird-badge">织布鸟 结构</span><span class="bird-badge">猫头鹰 质量</span>'
    badges += '<span class="bird-badge bird-badge-amber">渡鸦 AI Coding</span>'
    badges += '<span class="bird-badge">鸬鹚 数据</span><span class="bird-badge bird-badge-red">苍鹰 校验</span>'
    st.markdown(f'<div style="text-align:center;margin-bottom:1rem">{badges}</div>', unsafe_allow_html=True)


def render_phase_bar(current):
    names = ["① 上传", "② 预检", "③ 评审", "④ 确认", "⑤ 报告"]
    steps = ""
    for i, name in enumerate(names):
        cls = "active" if i == current else ("done" if i < current else "")
        steps += f'<div class="phase-step {cls}">{name}</div>'
    st.markdown(f'<div class="phase-bar">{steps}</div>', unsafe_allow_html=True)


def render_phase0_upload():
    """Phase 0: 上传 PRD + 资料"""
    try:
        from easter_eggs import get_phase_line
        line = get_phase_line("phase0")
        if line:
            st.caption(f"*{line}*")
    except:
        pass
    st.subheader("📄 上传 PRD 文档")

    tab1, tab2 = st.tabs(["上传文件", "粘贴内容"])
    with tab1:
        uploaded = st.file_uploader("拖入 PRD（.md）", type=["md", "txt"], key="prd_upload")
        if uploaded:
            st.session_state["prd_content"] = uploaded.read().decode("utf-8")
            st.session_state["prd_name"] = uploaded.name
    with tab2:
        pasted = st.text_area("粘贴 PRD 内容", height=250, placeholder="Markdown 格式...", key="prd_paste")
        if pasted:
            st.session_state["prd_content"] = pasted
            st.session_state["prd_name"] = "粘贴的 PRD"

    if st.session_state["prd_content"]:
        st.success(f"已加载: {st.session_state['prd_name']} ({len(st.session_state['prd_content'])} 字)")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 补充资料
    st.subheader("📎 补充业务资料（可选）")
    st.caption("上传业务文档、竞品分析、数据字典等，帮助啄木鸟更准确地评审")
    raw_files = st.file_uploader("上传补充资料", type=["md", "txt", "csv"], accept_multiple_files=True, key="raw_upload")
    if raw_files:
        materials = []
        for f in raw_files:
            materials.append(f.read().decode("utf-8", errors="replace"))
        st.session_state["raw_materials"] = materials
        st.caption(f"已加载 {len(materials)} 份补充资料")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 评审配置
    col1, col2 = st.columns([2, 1])
    with col1:
        mode = st.radio("评审模式", ["quick", "standard"],
            format_func=lambda x: {"quick": "⚡ 快速（~30s）", "standard": "🔍 标准 · 4 鸟并行（~2min）"}[x],
            horizontal=True, key="review_mode")
    with col2:
        st.text_input("评审人", value="default", key="reviewer_name")

    if st.session_state["prd_content"]:
        if st.button("🪶 开始预检", type="primary", use_container_width=True):
            st.session_state["phase"] = 1
            st.rerun()


def scan_wiki_for_prd(prd_content, wiki_path):
    """扫描 wiki 知识库，找出与 PRD 相关的页面和知识盲区"""
    if not os.path.isdir(wiki_path):
        return {"strong": [], "weak": [], "gaps": [], "wiki_pages": {}}

    import re as _re

    # 提取 PRD 中的关键词
    prd_keywords = set(_re.findall(r'[\u4e00-\u9fff]{2,4}', prd_content[:3000]))
    # 过滤掉过于常见的词
    stop = {"文档", "说明", "需求", "版本", "内容", "数据", "系统", "功能", "用户", "信息", "通过", "支持", "进行", "使用", "相关", "以下", "如下", "其中"}
    prd_keywords -= stop

    wiki_pages = {}
    strong = []
    weak = []

    for fname in os.listdir(wiki_path):
        if not fname.endswith(".md") or fname in ("index.md", "log.md", "_scratchpad.md"):
            continue
        fpath = os.path.join(wiki_path, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        page_name = fname.replace(".md", "")
        wiki_pages[page_name] = content

        # 计算关键词命中数
        hits = sum(1 for kw in list(prd_keywords)[:30] if kw in fname or kw in content[:500])
        if hits >= 3:
            strong.append(f"[[{page_name}]] — 命中 {hits} 个关键词")
        elif hits >= 1:
            weak.append(f"[[{page_name}]] — 命中 {hits} 个关键词")

    return {"strong": strong, "weak": weak, "gaps": [], "wiki_pages": wiki_pages}


def render_phase1_precheck():
    """Phase 1: 知识盲区预检"""
    try:
        from easter_eggs import get_phase_line
        line = get_phase_line("phase0.5")
        if line:
            st.caption(f"*{line}*")
    except:
        pass
    st.subheader("🔍 知识盲区预检")

    client = get_client()
    if not client:
        return

    # 先扫描本地 wiki
    wiki_path = st.session_state["wiki_path"]
    wiki_scan = scan_wiki_for_prd(st.session_state["prd_content"], wiki_path)
    st.session_state["wiki_pages"] = wiki_scan.get("wiki_pages", {})

    if wiki_scan["strong"]:
        st.markdown("**✅ 知识库强相关页面**")
        for s in wiki_scan["strong"]:
            st.markdown(f"- {s}")

    if wiki_scan["weak"]:
        st.markdown("**🔶 知识库弱相关页面**")
        for w in wiki_scan["weak"]:
            st.markdown(f"- {w}")

    if not wiki_scan["strong"] and not wiki_scan["weak"]:
        st.info("知识库中未找到与 PRD 直接相关的页面")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    with st.spinner("啄木鸟正在检查知识覆盖范围..."):
        precheck = run_precheck(client, st.session_state["prd_content"], st.session_state["raw_materials"])

    # 强相关
    strong = precheck.get("strong", [])
    if strong:
        st.markdown("**✅ 已掌握的知识**")
        for s in strong:
            st.markdown(f"- {s}")

    # 弱相关
    weak = precheck.get("weak", [])
    if weak:
        st.markdown("**🔶 弱相关知识**")
        for w in weak:
            st.markdown(f"- {w}")

    # 盲区
    gaps = precheck.get("gaps", [])
    if gaps:
        st.markdown("**❌ 知识盲区**")
        for g in gaps:
            st.markdown(f'<div class="gap-card">⚠️ {g}</div>', unsafe_allow_html=True)

        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

        # 用户补充
        st.markdown("**📝 你可以补充说明（帮助啄木鸟更准确评审）**")
        notes = st.text_area(
            "补充说明",
            placeholder="例如：我们的脱敏规则是姓+**，企业名不脱敏。导出上限暂定 5000 条...",
            height=150, key="user_notes_input",
        )
        if notes:
            st.session_state["user_notes"] = notes
    else:
        st.info("知识覆盖充分，没有发现明显盲区")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ 返回修改", use_container_width=True):
            st.session_state["phase"] = 0
            st.rerun()
    with col2:
        label = "跳过补充，直接评审" if gaps else "开始评审"
        if st.button(f"🪶 {label}", type="primary", use_container_width=True):
            st.session_state["phase"] = 2
            st.rerun()


def render_phase2_review():
    """Phase 2: 执行评审"""
    try:
        from easter_eggs import get_phase_line
        line = get_phase_line("phase2")
        if line:
            st.caption(f"*{line}*")
    except:
        pass
    st.subheader("🐦 评审进行中")

    client = get_client()
    if not client:
        return

    mode = st.session_state.get("review_mode", "standard")

    with st.status("啄木鸟评审团出击...", expanded=True) as status:
        st.write("📋 读取 PRD 内容...")
        time.sleep(0.3)
        st.write(f"📝 PRD: {len(st.session_state['prd_content'])} 字")

        if st.session_state["raw_materials"]:
            st.write(f"📎 补充资料: {len(st.session_state['raw_materials'])} 份")
        if st.session_state["user_notes"]:
            st.write("💬 包含用户补充说明")

        if mode == "standard":
            st.write("🐦 派出: 织布鸟(结构) + 猫头鹰(质量) + 渡鸦(AI Coding) + 鸬鹚(数据)")
        else:
            st.write("⚡ 快速模式: 4 维度 checklist（全 Sonnet）")

        result = run_review(
            client, st.session_state["prd_content"],
            st.session_state["raw_materials"],
            st.session_state["user_notes"], mode,
        )

        items = result.get("items", [])
        st.write(f"✅ 评审完成，发现 {len(items)} 条改进项")

        # 各维度详情
        workers = result.get("workers", [])
        if workers:
            for w in workers:
                if "error" in w and w.get("error"):
                    st.write(f"  ❌ {w.get('dimension_name','?')}: 失败")
                else:
                    st.write(f"  ✅ {w.get('dimension_name','?')}: {len(w.get('items',[]))} 条")

        # 苍鹰交叉校验（仅标准模式）
        if mode == "standard" and items:
            st.write("🦅 苍鹰交叉校验中...")
            try:
                from goshawk_advisor import advisor_review, apply_advisor_result
                prd_with_context = st.session_state["prd_content"]
                if st.session_state.get("user_notes"):
                    prd_with_context += "\n\n补充说明：" + st.session_state["user_notes"]
                goshawk_result = advisor_review(client, prd_with_context, items, st.session_state.get("wiki_pages", {}))
                items = apply_advisor_result(items, goshawk_result)
                result["items"] = items
                result["goshawk"] = goshawk_result
                fp = len(goshawk_result.get("flagged_as_false_positive", []))
                add = len(goshawk_result.get("additional_findings", []))
                conf = len(goshawk_result.get("conflict_resolutions", []))
                st.write(f"🦅 苍鹰完成：误报 {fp}，补充 {add}，调解 {conf}")
            except Exception as e:
                st.write(f"🦅 苍鹰跳过: {str(e)[:50]}")

        status.update(label=f"评审完成 — {len(items)} 条改进项", state="complete")

    st.session_state["review_result"] = result
    st.session_state["phase"] = 3
    st.rerun()


def render_phase3_confirm():
    """Phase 3: 逐条确认"""
    try:
        from easter_eggs import get_phase_line
        line = get_phase_line("phase3")
        if line:
            st.caption(f"*{line}*")
    except:
        pass
    result = st.session_state["review_result"]
    items = result.get("items", [])

    if not items:
        st.warning("未发现改进项。这份 PRD 让啄木鸟无从下嘴。")
        if st.button("返回重新上传"):
            st.session_state["phase"] = 0
            st.rerun()
        return

    peck = calculate_peck(items)

    # 统计卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="stat-card"><div class="stat-number">{len(items)}</div><div class="stat-label">改进项总数</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#9B2335">{peck["must"]}</div><div class="stat-label">must 级</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#B8860B">{peck["should"]}</div><div class="stat-label">should 级</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="peck-gauge"><div class="peck-score">{peck["score"]}</div><div class="peck-label">{peck["label"]}</div></div>', unsafe_allow_html=True)
    st.caption(f"诊断：{peck['desc']}")
    try:
        import random
        from easter_eggs import DIMENSION_COMMENTS
        seen_dims = set()
        for item in items:
            dim = item.get("dimension", "")
            dim_key = ""
            if "结构" in dim: dim_key = "structure"
            elif "质量" in dim: dim_key = "quality"
            elif "AI" in dim or "Coding" in dim: dim_key = "ai_coding"
            elif "数据" in dim: dim_key = "data_quality"
            if dim_key and dim_key not in seen_dims:
                seen_dims.add(dim_key)
                comments = DIMENSION_COMMENTS.get(dim_key, [])
                if comments:
                    st.caption(f"*{random.choice(comments)}*")
    except:
        pass

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 批量操作
    st.markdown("**批量操作**")
    bcol1, bcol2, bcol3 = st.columns(3)
    with bcol1:
        if st.button("✅ 全部接受", use_container_width=True):
            for i in items:
                st.session_state["item_decisions"][i["id"]] = {"action": "accept", "reason": ""}
            st.rerun()
    with bcol2:
        if st.button("🔄 重置全部", use_container_width=True):
            st.session_state["item_decisions"] = {}
            st.rerun()
    with bcol3:
        decided = len(st.session_state["item_decisions"])
        st.markdown(f"**已处理: {decided}/{len(items)}**")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 按维度分组
    dims = {}
    for item in items:
        dim = item.get("dimension", "综合") or "综合"
        dims.setdefault(dim, []).append(item)

    dim_icons = {"结构层": "🪺", "质量层": "🦉", "AI Coding 友好度": "🐦‍⬛",
                 "数据质量": "🐟", "苍鹰补充": "🦅", "综合": "🪶"}

    for dim, dim_items in dims.items():
        icon = dim_icons.get(dim, "🪶")
        st.markdown(f'<div class="dim-header">{icon} {dim}（{len(dim_items)} 条）</div>', unsafe_allow_html=True)

        for item in dim_items:
            rid = item.get("id", "?")
            sev = item.get("severity", "should")
            current = st.session_state["item_decisions"].get(rid, {})
            current_action = current.get("action", "")

            # 状态标记
            status_icon = {"accept": "✅", "reject": "❌", "edit": "✏️"}.get(current_action, "⬜")

            with st.expander(f"{status_icon} {rid}  |  {item.get('location', '')[:40]}  |  {'🔴 must' if sev == 'must' else '🟡 should'}"):
                if item.get("issue"):
                    st.markdown(f"**问题**: {item['issue']}")
                if item.get("suggestion"):
                    st.markdown(f"**建议**: {item['suggestion']}")
                if item.get("evidence_content"):
                    st.markdown(f"**依据**: {item['evidence_content']}")

                ev_type = item.get("evidence_type", "")
                if ev_type == "A":
                    st.markdown("🟢 **A类** 内部知识")
                elif ev_type == "B":
                    st.markdown("🔵 **B类** 评审规则")
                elif ev_type == "C":
                    st.markdown("🟡 **C类** 外部参考 ⚠️待确定")
                elif item.get("evidence_content"):
                    st.markdown("⚪ 依据类型未标注")
                else:
                    st.markdown("🔴 无依据")

                st.markdown("---")

                # 操作按钮
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("✅ 接受", key=f"accept_{rid}", use_container_width=True,
                                 type="primary" if current_action == "accept" else "secondary"):
                        st.session_state["item_decisions"][rid] = {"action": "accept", "reason": ""}
                        st.rerun()
                with c2:
                    if st.button("❌ 驳回", key=f"reject_{rid}", use_container_width=True,
                                 type="primary" if current_action == "reject" else "secondary"):
                        st.session_state["item_decisions"][rid] = {"action": "reject", "reason": ""}
                        st.rerun()
                with c3:
                    if st.button("✏️ 修改", key=f"edit_{rid}", use_container_width=True,
                                 type="primary" if current_action == "edit" else "secondary"):
                        st.session_state["item_decisions"][rid] = {"action": "edit", "reason": ""}
                        st.rerun()

                # 驳回/修改理由
                if current_action in ("reject", "edit"):
                    reason = st.text_input(
                        "请说明理由" if current_action == "reject" else "请说明修改意见",
                        value=current.get("reason", ""),
                        key=f"reason_{rid}",
                    )
                    if reason != current.get("reason", ""):
                        st.session_state["item_decisions"][rid]["reason"] = reason

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 生成报告按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ 返回预检", use_container_width=True):
            st.session_state["phase"] = 1
            st.rerun()
    with col2:
        if st.button("📄 生成评审报告", type="primary", use_container_width=True):
            report = generate_report(items, st.session_state["item_decisions"], peck)
            st.session_state["final_report"] = report
            st.session_state["phase"] = 4
            st.rerun()


def generate_interaction_log(items, decisions):
    """生成交互记录"""
    lines = ["# PRD 评审交互记录", "", f"**时间**: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for item in items:
        rid = item.get("id", "?")
        d = decisions.get(rid, {})
        action = d.get("action", "pending")
        action_label = {"accept": "✅ 接受", "reject": "❌ 驳回", "edit": "✏️ 修改"}.get(action, "⏳ 待处理")
        lines.append(f"## {rid}")
        lines.append(f"- **问题**: {item.get('issue', '')}")
        lines.append(f"- **决策**: {action_label}")
        if d.get("reason"):
            lines.append(f"- **理由**: {d['reason']}")
        lines.append("")
    return "\n".join(lines)


def generate_diff_report(items, decisions):
    """生成差异报告（原文位置 vs 建议改动）"""
    lines = ["# PRD 差异报告", "", f"**时间**: {time.strftime('%Y-%m-%d %H:%M')}", "",
             "以下列出所有已确认和已修改的改动项，对比原文位置和建议变更。", ""]
    accepted = [i for i in items if decisions.get(i["id"], {}).get("action") in ("accept", "edit")]
    if not accepted:
        lines.append("*无已确认的改动项*")
    for item in accepted:
        rid = item["id"]
        d = decisions.get(rid, {})
        lines.append(f"## {rid}（{item.get('severity', 'should')}）")
        lines.append(f"**位置**: {item.get('location', '未标注')}")
        lines.append("")
        lines.append(f"**问题**: {item.get('issue', '')}")
        lines.append("")
        lines.append(f"**建议**: {item.get('suggestion', '')}")
        if d.get("action") == "edit" and d.get("reason"):
            lines.append(f"\n**评审人修改意见**: {d['reason']}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def render_phase4_report():
    """Phase 4: 最终报告"""
    try:
        from easter_eggs import get_phase_line
        line = get_phase_line("phase4")
        if line:
            st.caption(f"*{line}*")
    except:
        pass
    st.subheader("📄 评审报告")

    report = st.session_state["final_report"]
    items = st.session_state["review_result"]["items"]
    decisions = st.session_state["item_decisions"]

    # 统计
    accepted = sum(1 for d in decisions.values() if d.get("action") == "accept")
    rejected = sum(1 for d in decisions.values() if d.get("action") == "reject")
    edited = sum(1 for d in decisions.values() if d.get("action") == "edit")
    pending = len(items) - len(decisions)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#4A8C2A">{accepted}</div><div class="stat-label">已接受</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#9B2335">{rejected}</div><div class="stat-label">已驳回</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#B8860B">{edited}</div><div class="stat-label">已修改</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="stat-card"><div class="stat-number">{pending}</div><div class="stat-label">待处理</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 报告预览
    st.markdown(report)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 伯劳简易门禁
    st.markdown("**🐦 伯劳质量门禁**")

    pending_items = [i for i in items if i["id"] not in decisions]
    rejected_no_reason = [rid for rid, d in decisions.items() if d.get("action") == "reject" and not d.get("reason")]
    edited_no_reason = [rid for rid, d in decisions.items() if d.get("action") == "edit" and not d.get("reason")]

    checks = [
        ("所有项目已处理", len(pending_items) == 0, f"还有 {len(pending_items)} 条未处理" if pending_items else ""),
        ("驳回项均有理由", len(rejected_no_reason) == 0, f"{', '.join(rejected_no_reason)} 缺少驳回理由" if rejected_no_reason else ""),
        ("修改项均有说明", len(edited_no_reason) == 0, f"{', '.join(edited_no_reason)} 缺少修改说明" if edited_no_reason else ""),
        ("报告内容完整", len(report) > 200, "报告内容过短"),
    ]

    all_pass = all(c[1] for c in checks)
    for name, passed, detail in checks:
        if passed:
            st.write(f"✅ {name}")
        else:
            st.write(f"❌ {name} — {detail}")

    if all_pass:
        st.success("伯劳：报告质量合格，可以导出。")
    else:
        st.warning("伯劳：有待完善的项目，建议返回补充后再导出。")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # 导出
    interaction_log = generate_interaction_log(items, decisions)
    diff_report = generate_diff_report(items, decisions)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📥 改动报告", data=report,
            file_name=f"PRD_改动报告_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)
    with col2:
        st.download_button("📥 交互记录", data=interaction_log,
            file_name=f"PRD_交互记录_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)
    with col3:
        st.download_button("📥 差异报告", data=diff_report,
            file_name=f"PRD_差异报告_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)

    # 保存到知识库
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    wiki_path = st.session_state["wiki_path"]

    if os.path.isdir(wiki_path):
        st.markdown("**📚 保存到知识库**")
        peck = calculate_peck(items)

        if st.button("💾 保存评审记录到 Wiki", type="primary", use_container_width=True):
            try:
                from wiki_lock import wiki_write_lock

                with wiki_write_lock(wiki_path):
                    # 1. 保存改动报告
                    report_filename = f"评审记录-{st.session_state.get('prd_name','PRD')}-{time.strftime('%Y%m%d')}.md"
                    report_path = os.path.join(wiki_path, report_filename)
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(f"---\nsource: Web评审-{time.strftime('%Y-%m-%d')}\ncreated: {time.strftime('%Y-%m-%d')}\nupdated: {time.strftime('%Y-%m-%d')}\ntags: [domain/评审记录, status/已验证]\n---\n\n")
                        f.write(report)

                    # 2. 追加 log.md
                    log_path = os.path.join(wiki_path, "log.md")
                    prd_name = st.session_state.get("prd_name", "未命名")
                    reviewer = st.session_state.get("reviewer_name", "default")
                    log_entry = f"\n\n## [{time.strftime('%Y-%m-%d %H:%M')}] review | {prd_name} by {reviewer}\n"
                    log_entry += f"- 改进项: {len(items)} 条 (must {peck['must']}, should {peck['should']})\n"
                    log_entry += f"- 已接受: {accepted}, 已驳回: {rejected}, 已修改: {edited}\n"
                    log_entry += f"- 啄伤度: {peck['score']}/100 ({peck['label']})\n"

                    if os.path.exists(log_path):
                        with open(log_path, "r", encoding="utf-8") as f:
                            existing = f.read()
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write(existing.rstrip() + log_entry)
                    else:
                        with open(log_path, "w", encoding="utf-8") as f:
                            f.write("# 操作日志\n" + log_entry)

                    # 3. 重建索引
                    try:
                        from kakapo_dream import rebuild_index
                        rebuild_index(wiki_path)
                    except Exception:
                        pass

                st.success(f"已保存到: {wiki_path}/{report_filename}")
                st.caption("log.md 已更新，索引已重建")

            except Exception as e:
                st.error(f"保存失败: {str(e)[:80]}")
    else:
        st.caption(f"Wiki 路径不可用 ({wiki_path})，跳过知识库保存")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("⬅️ 返回修改确认", use_container_width=True):
            st.session_state["phase"] = 3
            st.rerun()
    with col_b:
        if st.button("🔄 开始新评审", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            init_state()
            st.rerun()

    # Token 用量
    usage = st.session_state["review_result"].get("usage", {})
    if usage:
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        st.caption(f"Token: input={inp:,} output={out:,} total={inp+out:,}")


# ============================================================
# 主流程
# ============================================================

def main():
    with st.sidebar:
        st.markdown("### ⚙️ 配置")
        wiki_path = st.text_input("Wiki 知识库路径", value=st.session_state["wiki_path"],
                                   help="Obsidian 知识库目录路径")
        if wiki_path != st.session_state["wiki_path"]:
            st.session_state["wiki_path"] = wiki_path

        if os.path.isdir(st.session_state["wiki_path"]):
            wiki_files = [f for f in os.listdir(st.session_state["wiki_path"]) if f.endswith(".md")]
            st.caption(f"📚 知识库: {len(wiki_files)} 个页面")
        else:
            st.warning("Wiki 路径不存在")

    render_header()
    render_phase_bar(st.session_state["phase"])
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    phase = st.session_state["phase"]
    if phase == 0:
        render_phase0_upload()
    elif phase == 1:
        render_phase1_precheck()
    elif phase == 2:
        render_phase2_review()
    elif phase == 3:
        render_phase3_confirm()
    elif phase == 4:
        render_phase4_report()

    st.markdown('<div class="footer-text">啄木鸟 v1.0.0 · 「让每一份 PRD 都经得起啄」</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
