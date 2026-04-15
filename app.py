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

def _list_workspaces():
    """扫项目根目录下的 workspace-* 目录,返回名字列表。"""
    base = os.path.dirname(os.path.abspath(__file__))
    out = []
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if name.startswith("workspace-") and os.path.isdir(full):
            out.append(name)
    return out


# ============================================================
# Step 2: 多用户稳定化辅助 — 并发限制 / 审计日志 / 飞书分发 / query params 记忆
# ============================================================

@st.cache_resource
def _review_semaphore():
    """全局进程级信号量,限制同时跑的评审数量 <= PECKER_MAX_CONCURRENT(默认 2)。

    用 @st.cache_resource 保证在一个 Streamlit 进程内所有 session 共享同一实例。
    公共账号 rate limit 是团队共用的,同时跑 5 个评审会直接撞墙,限到 2 个
    比较安全。队列外的 session 会阻塞在 acquire(),UI 会转圈。
    """
    import threading
    max_concurrent = int(os.environ.get("PECKER_MAX_CONCURRENT", "2"))
    return threading.Semaphore(max_concurrent)


def _audit_log(event: str, reviewer: str, **kwargs):
    """追加审计事件到 logs/user_actions.jsonl。

    用于追踪"谁什么时候跑了什么",出故障时按 reviewer 回放,防公共账号背锅。
    格式: {ts, event, reviewer, workspace, prd_name, ...extra}
    """
    try:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "user_actions.jsonl")
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "reviewer": reviewer or "unknown",
            "workspace": st.session_state.get("workspace", ""),
            "prd_name": st.session_state.get("prd_name", ""),
            **kwargs,
        }
        # append 模式,单次 write JSON 行 < 4KB 是原子的,无需文件锁
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 审计日志失败绝不能阻塞主流程


def _count_today_reviews(reviewer: str) -> int:
    """数某个 reviewer 今天的 review_started 次数,用于顶部 banner。"""
    try:
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "logs", "user_actions.jsonl",
        )
        if not os.path.isfile(log_path):
            return 0
        today = time.strftime("%Y-%m-%d")
        count = 0
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if (rec.get("event") == "review_started"
                            and rec.get("reviewer") == reviewer
                            and rec.get("ts", "").startswith(today)):
                        count += 1
                except json.JSONDecodeError:
                    continue
        return count
    except Exception:
        return 0


# ============================================================
# Step 3: 生产级 — 崩溃恢复 / Basic auth / READONLY / 草稿管理
# ============================================================

_DRAFT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pecker_drafts")
_DRAFT_TTL_DAYS = 3  # 草稿保留 3 天


def _draft_path(reviewer: str) -> str:
    """每个 reviewer 一个 draft 文件,防止互相覆盖。"""
    safe = re.sub(r'[\\/:*?"<>|\s]+', '_', (reviewer or "unknown").strip())[:20]
    return os.path.join(_DRAFT_DIR, f"{safe}_draft.json")


def _save_draft(reviewer: str):
    """把当前 session_state 的关键字段快照到 draft 文件。

    只存 JSON 可序列化的小字段。失败静默(不能阻塞评审)。
    """
    if not reviewer:
        return
    try:
        os.makedirs(_DRAFT_DIR, exist_ok=True)
        draft = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "reviewer": reviewer,
            "phase": st.session_state.get("phase", 0),
            "prd_name": st.session_state.get("prd_name", ""),
            "prd_content": st.session_state.get("prd_content", ""),
            "raw_materials": st.session_state.get("raw_materials", []),
            "user_notes": st.session_state.get("user_notes", ""),
            "review_result": st.session_state.get("review_result"),
            "item_decisions": st.session_state.get("item_decisions", {}),
            "workspace": st.session_state.get("workspace", ""),
        }
        # 原子写
        path = _draft_path(reviewer)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _load_draft(reviewer: str):
    """加载 reviewer 的 draft,不存在或过期返回 None。"""
    if not reviewer:
        return None
    path = _draft_path(reviewer)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            draft = json.load(f)
        # 过期检查: 3 天前的 draft 视作过期,自动删除
        ts = draft.get("ts", "")
        if ts:
            from datetime import datetime as _dt
            age = (_dt.now() - _dt.strptime(ts, "%Y-%m-%dT%H:%M:%S")).total_seconds()
            if age > _DRAFT_TTL_DAYS * 86400:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                return None
        return draft
    except Exception:
        return None


def _clear_draft(reviewer: str):
    """评审完成后清理 draft。"""
    path = _draft_path(reviewer)
    if os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _cleanup_expired_drafts():
    """启动时扫一次,清掉过期的 draft。"""
    if not os.path.isdir(_DRAFT_DIR):
        return
    cutoff = time.time() - _DRAFT_TTL_DAYS * 86400
    for name in os.listdir(_DRAFT_DIR):
        if not name.endswith("_draft.json"):
            continue
        path = os.path.join(_DRAFT_DIR, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except OSError:
            pass


def _check_web_auth() -> bool:
    """Basic auth: 如果 PECKER_WEB_PASSWORD 设置了,要求用户先输密码才能用。

    密码以明文存在 env var(内网部署,简单够用)。通过后写入 session_state,
    同 tab 内不重复要求。
    """
    expected = os.environ.get("PECKER_WEB_PASSWORD", "")
    if not expected:
        return True  # 未配置密码,直接通过

    if st.session_state.get("_auth_passed"):
        return True

    st.markdown("## 🔒 啄木鸟 Web 需要访问口令")
    st.caption("部署在共享机器上,仅限团队内部使用。口令找管理员获取。")
    pw = st.text_input("访问口令", type="password", key="_auth_pw_input")
    if st.button("进入", type="primary"):
        if pw == expected:
            st.session_state["_auth_passed"] = True
            st.rerun()
        else:
            st.error("口令错误")
    return False


def _is_readonly(reviewer: str) -> bool:
    """PECKER_READONLY_USERS 逗号分隔的 reviewer 列表,命中即为只读。

    只读模式: 可以评审和下载,但不能保存到 wiki / 推送飞书 / 写审计日志。
    适合: 允许轮岗 PM 或外部顾问查看评审但不污染团队知识库。
    """
    if not reviewer:
        return False
    readonly_list = os.environ.get("PECKER_READONLY_USERS", "")
    if not readonly_list:
        return False
    users = {u.strip() for u in readonly_list.split(",") if u.strip()}
    return reviewer.strip() in users


def _send_report_to_feishu(report_md: str, prd_name: str, reviewer: str) -> tuple[bool, str]:
    """把评审报告推送到飞书群。需要 env var: FEISHU_APP_ID/SECRET 和 FEISHU_REPORT_CHAT_ID。

    返回 (成功?, 错误或成功信息)。
    """
    chat_id = os.environ.get("FEISHU_REPORT_CHAT_ID", "")
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not (chat_id and app_id and app_secret):
        return False, "未配置 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_REPORT_CHAT_ID"
    try:
        from feishu_client import FeishuClient
        client = FeishuClient(app_id=app_id, app_secret=app_secret)
        # 截断到 3500 字符(飞书卡片 plaintext 上限)
        snippet = report_md[:3500]
        if len(report_md) > 3500:
            snippet += "\n\n...(报告已截断,完整报告见附件或 wiki)"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🪶 PRD 评审报告 - {prd_name}"},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**评审人**: {reviewer}"}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": snippet}},
            ],
        }
        msg_id = client.send_card(chat_id, card)
        if msg_id:
            return True, f"已推送到飞书群 (msg_id={msg_id[:12]}...)"
        return False, "飞书 send_card 返回空"
    except Exception as e:
        return False, f"推送失败: {str(e)[:100]}"


def init_state():
    ws_list = _list_workspaces()
    default_ws = ws_list[0] if ws_list else ""

    # 从 URL query params 读上次的 reviewer(浏览器刷新/书签不丢身份)
    try:
        qp = st.query_params
        qp_reviewer = qp.get("reviewer", "") or ""
        qp_workspace = qp.get("workspace", "") or ""
    except Exception:
        qp_reviewer = ""
        qp_workspace = ""

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
        "reviewer_name": qp_reviewer,   # 从 URL 恢复
        "workspace": qp_workspace if qp_workspace in ws_list else default_ws,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # 运行时把 WORKSPACE 注入 env var,后端 parallel_review 用延迟解析读
    if st.session_state.get("workspace"):
        os.environ["WORKSPACE"] = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            st.session_state["workspace"],
        )

init_state()


# ============================================================
# 核心逻辑
# ============================================================

def get_client():
    """创建 API client。

    api_adapter.create_client 实际只走本地 Claude Code CLI,不需要 api_key。
    这里只需要验证 claude CLI 存在 + 已登录即可(公共账号场景下,在共享机器上
    登录一次,所有 PM 通过浏览器共用同一个 CC 认证)。
    """
    from api_adapter import create_client
    import shutil
    if not shutil.which("claude"):
        st.error("❌ 本机找不到 claude CLI。请先安装 Claude Code 并执行 `claude login`。")
        st.caption("安装指引: https://docs.anthropic.com/claude/docs/claude-code")
        return None
    return create_client()


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

    # Step 3.1 崩溃恢复 UI: 如果当前 reviewer 有未完成 draft,提示恢复
    _rev_for_draft = st.session_state.get("reviewer_name", "").strip()
    if _rev_for_draft and not st.session_state.get("_draft_checked"):
        _draft = _load_draft(_rev_for_draft)
        if _draft and _draft.get("phase", 0) > 0:
            st.info(
                f"🔄 检测到 **{_rev_for_draft}** 有一份未完成的评审草稿"
                f"(阶段 {_draft['phase']}, PRD: {_draft.get('prd_name','?')}, "
                f"保存于 {_draft.get('ts','?')})"
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("🔄 恢复评审", type="primary", use_container_width=True):
                    for k in ("phase", "prd_content", "prd_name", "raw_materials",
                              "user_notes", "review_result", "item_decisions", "workspace"):
                        if k in _draft:
                            st.session_state[k] = _draft[k]
                    st.session_state["_draft_checked"] = True
                    _audit_log("draft_resumed", _rev_for_draft, phase=_draft.get("phase"))
                    st.rerun()
            with c2:
                if st.button("🗑️ 丢弃草稿", use_container_width=True):
                    _clear_draft(_rev_for_draft)
                    st.session_state["_draft_checked"] = True
                    st.rerun()
            with c3:
                if st.button("⏭️ 暂不处理", use_container_width=True):
                    st.session_state["_draft_checked"] = True
                    st.rerun()
            return  # 等 PM 决策

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
        reviewer = st.text_input(
            "评审人 *",
            value=st.session_state.get("reviewer_name", ""),
            key="reviewer_name",
            placeholder="填你的名字",
            help="必填,用于报告署名、审计追溯和防止同事评审结果互相覆盖",
        )

    if not st.session_state.get("reviewer_name", "").strip():
        st.warning("⚠️ 请先在右上方填写评审人姓名(必填,用于追溯和报告命名)")
        return  # block Phase 0 下一步按钮

    # 同步 reviewer 和 workspace 到 URL query params,下次刷新/分享链接能恢复
    try:
        st.query_params["reviewer"] = st.session_state["reviewer_name"].strip()
        if st.session_state.get("workspace"):
            st.query_params["workspace"] = st.session_state["workspace"]
    except Exception:
        pass

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
    reviewer = st.session_state.get("reviewer_name", "unknown")

    # Step 2.3 全局并发 semaphore — 限制同时跑的评审数量
    _sem = _review_semaphore()
    _max_concurrent = int(os.environ.get("PECKER_MAX_CONCURRENT", "2"))

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

        # 先尝试非阻塞拿锁,看当前是否有其他评审在跑
        if not _sem.acquire(blocking=False):
            st.write(f"⏳ 当前已有 {_max_concurrent} 个评审在跑(公共账号 rate limit 保护),正在排队...")
            _sem.acquire(blocking=True)  # 阻塞等待
            st.write("✅ 排队完成,开始评审")

        try:
            _audit_log("review_started", reviewer,
                       mode=mode, prd_length=len(st.session_state["prd_content"]))
            _save_draft(reviewer)  # 评审开始前快照,万一崩溃能恢复

            result = run_review(
                client, st.session_state["prd_content"],
                st.session_state["raw_materials"],
                st.session_state["user_notes"], mode,
            )
        finally:
            _sem.release()

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

    _audit_log("review_finished", reviewer,
               items_count=len(items),
               mode=mode,
               usage=result.get("usage", {}))

    st.session_state["review_result"] = result
    st.session_state["phase"] = 3
    _save_draft(reviewer)  # 进入确认阶段前再快照一次,防 phase3 中途崩溃
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

    _rev = st.session_state.get("reviewer_name", "unknown").strip() or "unknown"
    _rev_safe = re.sub(r'[\\/:*?"<>|\s]+', '_', _rev)[:20]
    _readonly = _is_readonly(_rev)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📥 改动报告", data=report,
            file_name=f"PRD_改动报告_{_rev_safe}_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)
    with col2:
        st.download_button("📥 交互记录", data=interaction_log,
            file_name=f"PRD_交互记录_{_rev_safe}_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)
    with col3:
        st.download_button("📥 差异报告", data=diff_report,
            file_name=f"PRD_差异报告_{_rev_safe}_{time.strftime('%Y%m%d')}.md", mime="text/markdown",
            use_container_width=True)

    # Step 2.4 飞书分发按钮 (readonly 模式下禁用)
    feishu_configured = bool(
        os.environ.get("FEISHU_APP_ID") and
        os.environ.get("FEISHU_APP_SECRET") and
        os.environ.get("FEISHU_REPORT_CHAT_ID")
    )
    if feishu_configured:
        if st.button("📨 推送报告到飞书群", use_container_width=True, disabled=_readonly,
                     help="🔒 只读模式禁用" if _readonly else "一键推送到飞书群"):
            with st.spinner("推送中..."):
                ok, msg = _send_report_to_feishu(
                    report_md=report,
                    prd_name=st.session_state.get("prd_name", "PRD"),
                    reviewer=_rev,
                )
            if ok:
                st.success(msg)
                _audit_log("feishu_pushed", _rev, msg=msg[:80])
            else:
                st.error(msg)
    else:
        st.caption("💡 配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_REPORT_CHAT_ID` 后可一键推送报告到飞书群")

    # 保存到知识库
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    wiki_path = st.session_state["wiki_path"]

    if os.path.isdir(wiki_path):
        st.markdown("**📚 保存到知识库**")
        peck = calculate_peck(items)

        if st.button(
            "💾 保存评审记录到 Wiki",
            type="primary",
            use_container_width=True,
            disabled=_readonly,
            help="🔒 只读模式禁用 — PECKER_READONLY_USERS 已包含你的名字" if _readonly else None,
        ):
            try:
                from wiki_lock import wiki_write_lock

                with wiki_write_lock(wiki_path):
                    # 1. 保存改动报告 — 文件名带 reviewer 防止多人同天评同名 PRD 互相覆盖
                    _rev = st.session_state.get("reviewer_name", "unknown").strip() or "unknown"
                    _rev_safe = re.sub(r'[\\/:*?"<>|\s]+', '_', _rev)[:20]
                    report_filename = f"评审记录-{st.session_state.get('prd_name','PRD')}-{_rev_safe}-{time.strftime('%Y%m%d')}.md"
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
                _audit_log("wiki_saved", _rev,
                           wiki_path=wiki_path,
                           report_filename=report_filename)

            except Exception as e:
                st.error(f"保存失败: {str(e)[:80]}")
                _audit_log("wiki_save_failed", _rev, error=str(e)[:200])
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
            # 清 draft + 保留 reviewer / workspace (省得重填)
            _keep_reviewer = st.session_state.get("reviewer_name", "")
            _keep_workspace = st.session_state.get("workspace", "")
            _keep_wiki = st.session_state.get("wiki_path", "")
            _clear_draft(_keep_reviewer)
            _audit_log("review_reset", _keep_reviewer)
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            init_state()
            # 恢复 reviewer 和 workspace
            if _keep_reviewer:
                st.session_state["reviewer_name"] = _keep_reviewer
            if _keep_workspace:
                st.session_state["workspace"] = _keep_workspace
            if _keep_wiki:
                st.session_state["wiki_path"] = _keep_wiki
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
    # Step 3.2 Basic auth 前置检查
    if not _check_web_auth():
        return

    # Step 3.1 启动时清理过期 draft
    _cleanup_expired_drafts()

    with st.sidebar:
        st.markdown("### ⚙️ 配置")

        # Workspace 切换器 — 所有已存在的 workspace-* 目录
        ws_list = _list_workspaces()
        if ws_list:
            current_ws = st.session_state.get("workspace", ws_list[0])
            if current_ws not in ws_list:
                current_ws = ws_list[0]
            selected_ws = st.selectbox(
                "Workspace",
                options=ws_list,
                index=ws_list.index(current_ws),
                help="切换评审项目。每个 workspace 有独立的 prd/ wiki/ output/ 目录",
            )
            if selected_ws != st.session_state.get("workspace"):
                st.session_state["workspace"] = selected_ws
                # 同步到 env var,后端 parallel_review 延迟解析会读
                os.environ["WORKSPACE"] = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    selected_ws,
                )
                # 自动切换到对应 workspace 的 wiki 路径
                ws_wiki = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    selected_ws, "wiki",
                )
                if os.path.isdir(ws_wiki):
                    st.session_state["wiki_path"] = ws_wiki
                st.rerun()
        else:
            st.warning("未发现任何 workspace-* 目录")

        wiki_path = st.text_input(
            "Wiki 知识库路径",
            value=st.session_state["wiki_path"],
            help="默认跟随 workspace 切换,也可手动覆盖",
        )
        if wiki_path != st.session_state["wiki_path"]:
            st.session_state["wiki_path"] = wiki_path

        if os.path.isdir(st.session_state["wiki_path"]):
            wiki_files = [f for f in os.listdir(st.session_state["wiki_path"]) if f.endswith(".md")]
            st.caption(f"📚 知识库: {len(wiki_files)} 个页面")
        else:
            st.warning("Wiki 路径不存在")

        # 当前评审人显示
        current_reviewer = st.session_state.get("reviewer_name", "")
        if current_reviewer:
            readonly = _is_readonly(current_reviewer)
            ro_tag = " 🔒 READONLY" if readonly else ""
            st.markdown(f"### 👤 当前评审人\n**{current_reviewer}**{ro_tag}")
            if readonly:
                st.caption("只读模式: 可评审和下载,不能写 wiki / 推飞书")
        else:
            st.markdown("### 👤 当前评审人\n_未填写_")

    render_header()

    # 顶部多用户 banner(Step 2.1): 当前评审人 / workspace / 今日跑了几次 / 并发窗口
    _reviewer = st.session_state.get("reviewer_name", "").strip()
    _workspace = st.session_state.get("workspace", "")
    if _reviewer:
        _today_count = _count_today_reviews(_reviewer)
        _max = int(os.environ.get("PECKER_MAX_CONCURRENT", "2"))
        banner = (
            f"<div style='background:#f0f7ff;padding:8px 16px;border-radius:6px;"
            f"margin-bottom:12px;font-size:13px;color:#333'>"
            f"👤 <b>{_reviewer}</b> &nbsp;·&nbsp; 📁 <code>{_workspace or '(未选)'}</code> "
            f"&nbsp;·&nbsp; 今日已跑 <b>{_today_count}</b> 次 "
            f"&nbsp;·&nbsp; 全局并发上限 {_max}"
            f"</div>"
        )
        st.markdown(banner, unsafe_allow_html=True)
    else:
        st.info("🔰 首次使用请在 Phase 0 填写你的名字(会自动写入 URL,下次刷新自动恢复)")

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
