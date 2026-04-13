"""
啄木鸟彩蛋系统 -- 让评审多一点乐趣
"""

import os
import random
import datetime
import json
import glob as glob_module


# ============================================================
# 1. 启动 ASCII Art
# ============================================================

ASCII_ARTS = {
    "opus": (
        "渡鸦",
        r"""
      ___
     (o o)      渡鸦已就位
     ( V )      "如果 AI 看不懂你的 PRD，那人也看不懂"
    /|   |\
   / |   | \
    """,
    ),
    "sonnet": (
        "织布鸟",
        r"""
       ._.
      (o.o)     织布鸟已就位
      |\_/|     "结构不好的 PRD 就像乱搭的鸟巢"
     _/   \_
    (_     _)
    """,
    ),
    "haiku": (
        "鸬鹚",
        r"""
       __
      (  )>     鸬鹚已就位
       ||       "每个字段我都要逐条过目"
       ||
      _/\_
    """,
    ),
    "default": (
        "啄木鸟",
        r"""
        /|
       / |
      /  |.     啄木鸟已上线
     |  (o>     "让每一份 PRD 都经得起啄"
     |   |
     |  / \
    """,
    ),
}

# 额外的随机出场
BONUS_ARTS = [
    (
        "猫头鹰",
        r"""
      ,___,
      (O,O)     猫头鹰深夜上线
      /)_)      "嗯，正是我审视的时候"
       ""
    """,
    ),
    (
        "信鸽",
        r"""
         _
       >(.)__    信鸽待命中
        (___/    "等 AI Coding 做完再来收信"
    """,
    ),
    (
        "伯劳",
        r"""
       \   /
        \ /
        (o)>    伯劳在 PR 上等你
         |      "报告不完整别想合进来"
        / \
    """,
    ),
    (
        "杜鹃",
        r"""
       .-.
      (o o)     杜鹃出没
      /| |\     "让我看看这只啄木鸟靠不靠谱"
     / | | \
    """,
    ),
    (
        "鸮鹦",
        r"""
       (o_o)
      /(   )\   鸮鹦夜间巡逻中
       " " "    "让我整理一下这片森林"
    """,
    ),
    (
        "苍鹰",
        r"""
        _V_
       (o o)    苍鹰俯瞰全局
       /|=|\    "所有鸟的结论，我再看一遍"
      / | | \
    """,
    ),
]


def show_startup_art(model_tier="sonnet"):
    """显示启动画面，根据模型选对应角色"""
    # 10% 概率显示 bonus 角色
    if random.random() < 0.1 and BONUS_ARTS:
        name, art = random.choice(BONUS_ARTS)
    else:
        name, art = ASCII_ARTS.get(model_tier, ASCII_ARTS["default"])
    print(art)
    return name


# ============================================================
# 2. Phase 切换台词
# ============================================================

PHASE_LINES = {
    "phase0": [
        '织布鸟："让我先看看这棵树的结构..."',
        '啄木鸟："先检查地基，再看上层建筑。"',
    ],
    "phase0.5": [
        '啄木鸟："发现了几个树洞，得先补上再啄。"',
        '猫头鹰："先摸清自己知道什么，不知道什么。"',
    ],
    "phase1": [
        '啄木鸟："新资料入库中，知识库又厚了一点。"',
        '织布鸟："好材料才能编出好巢。"',
    ],
    "phase2": [
        '猫头鹰："夜深了，正是我审视的时候。"',
        '渡鸦："让我看看这份 PRD 够不够聪明。"',
        '鸬鹚："每个字段我都要逐条过目。"',
        '啄木鸟："鸟群出击，各就各位！"',
    ],
    "phase2.5": [
        '苍鹰："让我从高处再看一遍这些结论。"',
        '苍鹰："哪些是过度解读？哪些被遗漏了？"',
    ],
    "phase3": [
        '啄木鸟："该您过目了，每个洞都标了标签。"',
        '啄木鸟："驳回请给依据，我们讲证据。"',
    ],
    "phase4": [
        '伯劳："我在 PR 上等着，谁的报告不完整别想合进来。"',
        '信鸽："我先飞了，等 AI Coding 做完再来收信。"',
        '啄木鸟："又多了一圈年轮。"',
        '鸮鹦："评审结束了，我去巡一圈森林。"',
    ],
    "eval": [
        '杜鹃："让我看看这只啄木鸟到底靠不靠谱。"',
        '杜鹃："每条结论，我都要验一遍。"',
    ],
    "dream": [
        '鸮鹦："夜深了，是整理森林的时候。"',
        '鸮鹦："断链、孤岛、矛盾……一个都别想跑。"',
    ],
}


def get_phase_line(phase):
    """获取 Phase 切换时的随机台词"""
    lines = PHASE_LINES.get(phase, [])
    if lines:
        return random.choice(lines)
    return None


# ============================================================
# 3. 啄伤度评分
# ============================================================

SEVERITY_LABELS = [
    (0, 15, "皮毛之伤", "这份 PRD 让啄木鸟无从下嘴"),
    (16, 35, "轻伤", "几处瘀青，贴个创可贴就好"),
    (36, 60, "中伤", "需要认真治疗，建议复查一轮"),
    (61, 80, "重伤", "建议住院观察一个迭代周期"),
    (81, 100, "危重", "建议回炉重写，这不是修修补补能解决的"),
]

# 各维度的吐槽模板
DIMENSION_COMMENTS = {
    "structure": [
        '织布鸟："这个巢的承重墙有点歪。"',
        '织布鸟："格式还行，但少了几根关键的梁。"',
    ],
    "quality": [
        '猫头鹰："半夜审到这里我清醒了——因为被吓醒了。"',
        '猫头鹰："逻辑链断了两处，需要接骨。"',
    ],
    "ai_coding": [
        '渡鸦："这份 PRD 扔给 AI，AI 会回一句\'你确定？\'"',
        '渡鸦："四态 UI 缺失让我的智商受到了侮辱。"',
        '渡鸦："字段来源写了\'或\'，薛定谔的数据表。"',
    ],
    "data_quality": [
        '鸬鹚："字段映射表里的\'或\'字让我很不安。"',
        '鸬鹚："DDL 和 PRD 打架了，我选 DDL。"',
    ],
}


def calculate_peck_score(review_items):
    """
    计算啄伤度
    review_items: [{"severity": "must"|"should", "dimension": "...", ...}]
    """
    must_count = sum(1 for i in review_items if i.get("severity") == "must")
    should_count = sum(1 for i in review_items if i.get("severity") == "should")

    score = min(100, must_count * 8 + should_count * 3)

    # 找到对应评级
    label = "未知"
    description = ""
    for low, high, lbl, desc in SEVERITY_LABELS:
        if low <= score <= high:
            label = lbl
            description = desc
            break

    # 各维度吐槽（如果有改进项）
    dim_comments = []
    seen_dims = set()
    for item in review_items:
        dim = item.get("dimension", "")
        dim_key = ""
        if "结构" in dim:
            dim_key = "structure"
        elif "质量" in dim:
            dim_key = "quality"
        elif "AI" in dim or "Coding" in dim:
            dim_key = "ai_coding"
        elif "数据" in dim:
            dim_key = "data_quality"

        if dim_key and dim_key not in seen_dims:
            seen_dims.add(dim_key)
            comments = DIMENSION_COMMENTS.get(dim_key, [])
            if comments:
                dim_comments.append(random.choice(comments))

    # 进度条
    filled = int(score / 10)
    bar = "#" * filled + "." * (10 - filled)

    return {
        "score": score,
        "bar": bar,
        "label": label,
        "description": description,
        "must_count": must_count,
        "should_count": should_count,
        "dim_comments": dim_comments,
    }


def format_peck_score(peck):
    """格式化啄伤度为 Markdown"""
    lines = [
        "",
        "---",
        "",
        "## 啄伤度评估",
        "",
        f"啄伤度：[{peck['bar']}] {peck['score']}/100",
        "",
        f"评级：{peck['label']}",
        f"诊断：{peck['description']}",
        f"（must {peck['must_count']} 条 + should {peck['should_count']} 条）",
    ]

    if peck["dim_comments"]:
        lines.append("")
        for c in peck["dim_comments"]:
            lines.append(f"  {c}")

    # 鸟群共识
    if peck["score"] <= 15:
        lines.append("\n鸟群共识：这份 PRD 质量上乘，啄木鸟们集体鼓掌。")
    elif peck["score"] <= 35:
        lines.append("\n鸟群共识：小修小补即可出院，恢复良好。")
    elif peck["score"] <= 60:
        lines.append("\n鸟群共识：需要一轮认真的修订，建议复查。")
    elif peck["score"] <= 80:
        lines.append("\n鸟群共识：经过治疗可以康复，建议住院观察一个迭代周期。")
    else:
        lines.append("\n鸟群共识：这棵树的虫太多了，建议砍了重种。")

    return "\n".join(lines)


# ============================================================
# 4. 金句库
# ============================================================

FORTUNE_QUOTES = [
    "好的 PRD 不需要评审，但好的评审能让 PRD 变得更好。—— 啄木鸟",
    "如果一个字段的来源写了'或'，那它就来自薛定谔的数据表。—— 鸬鹚",
    "四态 UI 就像鸟的四季——少了任何一个，生态就不完整。—— 渡鸦",
    "我不是在找茬，我是在找虫。—— 啄木鸟",
    "一份 PRD 的质量，取决于它经历了多少次「为什么没写清楚」。—— 猫头鹰",
    "结构不好的 PRD 就像乱搭的鸟巢——住进去迟早塌。—— 织布鸟",
    "代码里的每一行 TODO，都是 PRD 欠下的技术债。—— 信鸽",
    "我不审核代码，我审核你有没有认真对待啄木鸟的建议。—— 伯劳",
    "知识库就像年轮，每次评审都让它多长一圈。—— 啄木鸟",
    "PRD 写得好不好，让 AI 写一遍代码就知道了。—— 渡鸦",
    "你可以驳回我的建议，但你驳不回事实。—— 啄木鸟",
    "空值处理写了'其他'三遍，数据质量就'其他'了。—— 鸬鹚",
    "最好的 PRD 是让开发者读完后没有问题要问的那种。—— 猫头鹰",
    "每一次评审都是知识库的一次进化。—— 啄木鸟",
    "报告不完整就提 PR？让我在上面钉满评论。—— 伯劳",
    "我不信任何结论，除非我亲自验过。—— 杜鹃",
    "断链和孤岛是知识库的癌症，我是夜间手术刀。—— 鸮鹦",
    "所有鸟都没看到这个？让我从高处再看一眼。—— 苍鹰",
    "误报比漏报更危险——它会让人对评审失去信任。—— 苍鹰",
    "一片不整理的森林，最终会变成灌木丛。—— 鸮鹦",
    "评审的质量不是自己说了算，得有人验。—— 杜鹃",
]


def get_fortune():
    """随机一条金句"""
    return random.choice(FORTUNE_QUOTES)


# ============================================================
# 5. 成就系统
# ============================================================

ACHIEVEMENTS = {
    "first_peck": {
        "name": "初啄",
        "icon": "🥚",
        "desc": "完成第一次 PRD 评审",
        "quote": "每只鸟都要迈出第一步",
    },
    "iron_beak": {
        "name": "铁嘴",
        "icon": "🦷",
        "desc": "单次评审发现 15+ 条 must 级问题",
        "quote": "这份 PRD 被啄得千疮百孔",
    },
    "eagle_eye": {
        "name": "火眼金睛",
        "icon": "🔍",
        "desc": "发现字段类型不一致（DDL 层面）",
        "quote": "鸬鹚的荣耀",
    },
    "perfect_sync": {
        "name": "驯鸟不渡",
        "icon": "🤝",
        "desc": "所有改进项被用户全部接受（0 驳回）",
        "quote": "啄木鸟与 PM 心有灵犀",
    },
    "rebel": {
        "name": "逆鳞",
        "icon": "⚔️",
        "desc": "用户驳回了 5 条以上 must 级改进",
        "quote": "勇敢的 PM 挑战了啄木鸟的判断",
    },
    "rich_forest": {
        "name": "知识富矿",
        "icon": "🌳",
        "desc": "wiki 知识库累积超过 50 页",
        "quote": "这片森林够大了",
    },
    "pigeon_home": {
        "name": "信鸽归巢",
        "icon": "🕊️",
        "desc": "第一次跑 feedback.py 收集到反馈",
        "quote": "反馈的种子已播下",
    },
    "full_flock": {
        "name": "全家福",
        "icon": "🐦",
        "desc": "一次评审中 4 个 worker 全部输出了改进项",
        "quote": "鸟群出击，无一遗漏",
    },
    "typo_hunter": {
        "name": "笔误猎手",
        "icon": "🎯",
        "desc": "发现排序描述自相矛盾等笔误",
        "quote": "连打字错误都逃不过",
    },
    "blind_spot_pioneer": {
        "name": "盲区开拓者",
        "icon": "🗺️",
        "desc": "Phase 0.5 发现 3 个以上知识盲区并补充",
        "quote": "勇敢面对未知",
    },
    "cuckoo_first": {
        "name": "杜鹃初鸣",
        "icon": "🥏",
        "desc": "第一次跑杜鹃 Eval 验证",
        "quote": "信任需要被验证",
    },
    "cuckoo_pass": {
        "name": "经得起验",
        "icon": "✅",
        "desc": "杜鹃 Eval 结果为 PASS（≥80%）",
        "quote": "这只啄木鸟值得信赖",
    },
    "kakapo_clean": {
        "name": "森林整洁",
        "icon": "🧹",
        "desc": "鸮鹦整理后 wiki 零断链零孤岛",
        "quote": "每棵树都有归属，每条路都走得通",
    },
    "goshawk_catch": {
        "name": "鹰眼纠偏",
        "icon": "🦅",
        "desc": "苍鹰发现了其他鸟都遗漏的问题",
        "quote": "高处看得更远",
    },
    "ten_reviews": {
        "name": "十啄之功",
        "icon": "🏅",
        "desc": "累计完成 10 次评审",
        "quote": "量变引起质变",
    },
}

# 成就存储文件
ACHIEVEMENTS_FILE = "achievements.json"


def load_achievements(wiki_path):
    """加载已解锁的成就"""
    path = os.path.join(wiki_path, ACHIEVEMENTS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"unlocked": {}, "stats": {"total_reviews": 0, "total_items": 0}}


def save_achievements(wiki_path, data):
    """保存成就数据"""
    path = os.path.join(wiki_path, ACHIEVEMENTS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_achievements(wiki_path, review_items=None, rejected_count=0, knowledge_gaps=0):
    """
    检查并解锁成就，返回新解锁的成就列表
    """
    data = load_achievements(wiki_path)
    newly_unlocked = []

    # 更新统计
    data["stats"]["total_reviews"] = data["stats"].get("total_reviews", 0) + 1
    if review_items:
        data["stats"]["total_items"] = data["stats"].get("total_items", 0) + len(review_items)

    must_count = sum(1 for i in (review_items or []) if i.get("severity") == "must")
    total_items = len(review_items or [])

    def unlock(key):
        if key not in data["unlocked"]:
            data["unlocked"][key] = datetime.date.today().isoformat()
            newly_unlocked.append(key)

    # 初啄
    if data["stats"]["total_reviews"] == 1:
        unlock("first_peck")

    # 铁嘴
    if must_count >= 15:
        unlock("iron_beak")

    # 火眼金睛：检查是否有字段类型不一致的改进项
    if review_items:
        for item in review_items:
            text = item.get("issue", "") + item.get("suggestion", "")
            if "类型" in text and ("不一致" in text or "冲突" in text or "datetime" in text or "date" in text):
                unlock("eagle_eye")
                break

    # 驯鸟不渡
    if total_items > 0 and rejected_count == 0:
        unlock("perfect_sync")

    # 逆鳞
    if rejected_count >= 5:
        unlock("rebel")

    # 知识富矿
    wiki_pages = glob_module.glob(os.path.join(wiki_path, "*.md"))
    if len(wiki_pages) >= 50:
        unlock("rich_forest")

    # 盲区开拓者
    if knowledge_gaps >= 3:
        unlock("blind_spot_pioneer")

    # 笔误猎手
    if review_items:
        for item in review_items:
            text = item.get("issue", "")
            if "笔误" in text or "自相矛盾" in text or "方向相同" in text or "两端方向" in text:
                unlock("typo_hunter")
                break

    save_achievements(wiki_path, data)
    return newly_unlocked


def format_achievement_unlock(keys):
    """格式化新解锁的成就"""
    if not keys:
        return ""

    lines = ["\n--- 成就解锁 ---\n"]
    for key in keys:
        ach = ACHIEVEMENTS.get(key, {})
        lines.append(f'  {ach.get("icon", "?")} {ach.get("name", key)} — {ach.get("desc", "")}')
        lines.append(f'     "{ach.get("quote", "")}"')
        lines.append("")

    return "\n".join(lines)


def format_all_achievements(wiki_path):
    """显示所有成就状态"""
    data = load_achievements(wiki_path)
    unlocked = data.get("unlocked", {})
    stats = data.get("stats", {})

    lines = [
        "--- 成就列表 ---",
        f"评审次数：{stats.get('total_reviews', 0)} | 总改进项：{stats.get('total_items', 0)}",
        "",
    ]

    for key, ach in ACHIEVEMENTS.items():
        if key in unlocked:
            date = unlocked[key]
            lines.append(f'  {ach["icon"]} {ach["name"]} — {ach["desc"]} (解锁于 {date})')
        else:
            lines.append(f'  [ ] {ach["name"]} — {ach["desc"]}')

    return "\n".join(lines)


# ============================================================
# 6. 隐藏命令
# ============================================================

FLOCK_ART = r"""

    ===================== 啄木鸟评审团全家福 =====================

      /|         ___       ._.       __         _
     / |        (o o)     (o.o)     (  )>     >(.)__
    /  |.        ( V )    |\_/|      ||        (___/
   |  (o>       /| |\    _/  \_      ||
   |   |       / | | \  (_    _)    _/\_

   啄木鸟    渡鸦     织布鸟     鸬鹚     信鸽
   (主控)  (AI Coding) (结构)   (数据)   (反馈)

     ,___,       \  /       .-.      (o_o)       _V_
     (O,O)        \/       (o o)    /(   )\     (o o)
     /)_)        (o)>      /| |\    " " "       /|=|\
      ""          |       / | | \              / | | \

    猫头鹰      伯劳      杜鹃      鸮鹦      苍鹰
    (质量)    (PR审核)   (Eval)  (Wiki守护) (Advisor)

    ========================================================
"""


def handle_hidden_command(command, wiki_path):
    """
    处理隐藏命令
    返回 (handled: bool, output: str)
    """
    cmd = command.strip().lower()

    if cmd == "/flock":
        return True, FLOCK_ART

    elif cmd == "/fortune":
        return True, f"\n  {get_fortune()}\n"

    elif cmd == "/stats":
        return True, format_all_achievements(wiki_path)

    elif cmd == "/nest":
        return True, format_forest_status(wiki_path)

    elif cmd == "/blame":
        return True, get_last_blame(wiki_path)

    return False, ""


# ============================================================
# 7. Wiki 森林状态
# ============================================================

def format_forest_status(wiki_path):
    """生成知识森林状态"""
    if not os.path.isdir(wiki_path):
        return "知识森林尚未种下第一棵树。"

    # 统计页面数
    pages = glob_module.glob(os.path.join(wiki_path, "*.md"))
    page_count = len(pages)

    # 统计双向链接数
    link_count = 0
    for page in pages:
        try:
            with open(page, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            link_count += content.count("[[")
        except OSError:
            pass

    # 统计评审次数（从 log.md 解析）
    review_count = 0
    log_path = os.path.join(wiki_path, "log.md")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("## ["):
                        review_count += 1
        except OSError:
            pass

    # 覆盖率（基于页面前缀分类）
    categories = {"概念": 0, "场景": 0, "竞品": 0, "约束": 0, "决策": 0, "实体": 0}
    for page in pages:
        basename = os.path.basename(page)
        for cat in categories:
            if basename.startswith(f"{cat}-"):
                categories[cat] += 1
                break

    covered = sum(1 for v in categories.values() if v > 0)
    coverage = int(covered / max(len(categories), 1) * 100)

    # 生成森林状态
    lines = [
        "",
        "--- 知识森林状态 ---",
        "",
        f"  树木（页面）：{page_count} 棵",
        f"  枝干（双向链接）：{link_count} 条",
        f"  年轮（评审次数）：{review_count} 圈",
        f"  鸟巢占用率：{coverage}%",
        "",
    ]

    if categories:
        lines.append("  分类统计：")
        for cat, count in categories.items():
            bar = "#" * count + "." * max(0, 5 - count)
            lines.append(f"    {cat}页 [{bar}] {count}")

    return "\n".join(lines)


def get_last_blame(wiki_path):
    """获取最近的漏报信号（从 wiki 中的规则提案文件读取）"""
    proposals = glob_module.glob(os.path.join(wiki_path, "规则提案-*.md"))
    if not proposals:
        return "\n  信鸽还没带回任何消息。先跑一次 feedback.py 看看？\n"

    # 取最新的
    latest = sorted(proposals)[-1]
    try:
        with open(latest, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        basename = os.path.basename(latest)
        return f"\n--- 最近的漏网之虫 ({basename}) ---\n\n{content[:500]}\n"
    except OSError:
        return "\n  信鸽的信件读取失败。\n"


# ============================================================
# 8. 森林状态写入 index.md
# ============================================================

def update_forest_in_index(wiki_path):
    """在 index.md 末尾更新森林状态"""
    index_path = os.path.join(wiki_path, "index.md")
    if not os.path.exists(index_path):
        return

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    # 生成状态文本
    status = format_forest_status(wiki_path)
    # 把 "---" 前缀去掉，用 markdown 标题
    status_md = status.replace("--- 知识森林状态 ---", "## 知识森林状态")

    # 替换或追加
    marker = "## 知识森林状态"
    if marker in content:
        # 替换从 marker 到文件末尾
        idx = content.index(marker)
        content = content[:idx] + status_md.strip() + "\n"
    else:
        content = content.rstrip() + "\n\n" + status_md.strip() + "\n"

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)