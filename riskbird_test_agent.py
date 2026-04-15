"""
风鸟后端测试 Agent - 百灵 (Lark/Skylark)

借鉴:
  - 胶水编程: 让 AI 抄 Mock 模板,不从零写
  - 快手单测 3.0: 场景分组 + 多轮反馈修复
  - Claude Code: 工具契约 + api_adapter 复用

阶段:
  1. 加载知识库(backend_call_graph.json)查被测类
  2. 召回 Mock 模板(index.json)
  3. 按 (被测方法 x 场景类型) 分组
  4. 并行 LLM 生成 per-group
  5. 组装成完整测试文件(JUnit 4 + Mockito)
  6. 可选: 编译修复阶段(W2.2 加)

用法:
    python riskbird_test_agent.py --target-class AiRobotChatServiceImpl
    python riskbird_test_agent.py --target-class AdvanceServiceImpl --no-fix
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# Windows 终端 UTF-8
import io
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from logger import setup_logging, log_agent_call, get_logger
setup_logging()
log = get_logger("skylark")

from api_adapter import create_client
from agent_config import MODEL_TIERS
from riskbird_test_fixer import fix_test_file

# 默认路径
DEFAULT_KNOWLEDGE = "workspace-风鸟-backend-test/knowledge/backend_call_graph.json"
DEFAULT_TEMPLATES_DIR = "workspace-风鸟-backend-test/knowledge/mock_templates"
DEFAULT_OUTPUT_DIR = "workspace-风鸟-backend-test/output/generated_tests"

# 场景分组(对齐快手 3.2.1)
# (id, name, desc, requires_nature) — requires_nature=None 表示全部 nature 都跑
# 条件激活(借鉴 Hermes Skill fallback_for_toolsets / requires_tools):
# 异常场景只对 write/transactional/async 方法有意义,纯 read 方法的异常测试
# 通常只是"Mock 抛异常→assertThrows",水测试,跳过能省 ~30% LLM 调用成本
SCENARIO_GROUPS = [
    ("normal",    "正常场景", "输入合法,所有 Mock 按预期返回,验证 happy path 返回值和关键 verify", None),
    ("boundary",  "边界场景", "空集合/空字符串/null 输入/单元素/最大值/0 值,验证边界行为", None),
    ("exception", "异常场景", "Mock 依赖抛异常(DB 连接失败/主键冲突/参数非法),验证异常传播或兜底",
     frozenset({"write", "transactional", "async"})),
]


# ============================================================
# 数据结构
# ============================================================

@dataclass
class GenerationJob:
    """一个生成任务 = 一个被测方法 × 一个场景组"""
    klass_entry: dict
    method: dict
    scenario_id: str
    scenario_name: str
    scenario_desc: str
    templates: list  # 命中的 mock 模板条目
    template_contents: dict  # template_id -> .tmpl 文件内容
    real_imports: list = field(default_factory=list)  # 被测类的真实 import 清单(防止瞎猜 FQN)


@dataclass
class GenerationResult:
    job: GenerationJob
    test_methods: list  # 生成的 @Test 方法 java 代码片段列表
    extra_imports: list
    error: Optional[str] = None


# ============================================================
# 知识库 & 模板检索
# ============================================================

def load_knowledge(path):
    """加载 backend_call_graph.json"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_class_by_name(knowledge, class_name):
    """按 class_name 查类,返回 entry(可能多个同名 → 选第一个)"""
    for fqn, entry in knowledge["classes"].items():
        if entry["class_name"] == class_name:
            return entry
    # 兜底: 模糊匹配
    for fqn, entry in knowledge["classes"].items():
        if class_name in fqn:
            return entry
    return None


def load_real_imports(knowledge, klass_entry, src_root=None):
    """读被测类的 .java 源文件,提取真实 import 清单

    这是防止 LLM 瞎猜 package 路径的关键 — 真实 FQN 注入 prompt 后,
    Sonnet 就不会从 entity/domain/vo 三个错误 package 中各 import 一份同名类。

    Returns: list of full imports(不含 'import ' 关键字和末尾分号)
    """
    if src_root is None:
        src_root = knowledge.get("src_root", "")
    file_rel = klass_entry.get("file", "")
    if not file_rel:
        return []
    full_path = os.path.join(src_root, file_rel.replace("/", os.sep))
    if not os.path.isfile(full_path):
        return []
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
    except UnicodeDecodeError:
        with open(full_path, "r", encoding="gbk", errors="replace") as f:
            source = f.read()

    imports = []
    for line in source.split("\n"):
        line = line.strip()
        if line.startswith("import ") and line.endswith(";"):
            fqn = line[len("import "):-1].strip()
            if fqn.startswith("static "):
                continue  # 测试里一般不复用业务代码的 static import
            imports.append(fqn)
        elif line.startswith("package ") or line.startswith("public class") or line.startswith("public abstract"):
            if line.startswith("public") and "class" in line:
                break  # 类声明开始后不再有 import
    return imports


def load_mock_templates(templates_dir):
    """加载所有 mock 模板 + 索引"""
    index_path = os.path.join(templates_dir, "index.json")
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    contents = {}
    for t in index["templates"]:
        tmpl_path = os.path.join(templates_dir, t["file"])
        with open(tmpl_path, "r", encoding="utf-8") as f:
            contents[t["id"]] = f.read()

    return index, contents


def select_templates_for_method(klass_entry, method, templates_index):
    """规则召回: 根据方法的 mock_deps + calls 命中的模板

    返回命中的 template_id 列表,按优先级排序
    """
    mock_deps = method.get("mock_deps", []) + klass_entry.get("class_mock_deps", [])
    calls_text = " ".join(c["target"] for c in method.get("calls", []))
    extends = klass_entry.get("extends", "")

    hits = []
    for t in templates_index["templates"]:
        rules = t.get("match_rules", {})
        matched = False

        # mock_deps_regex
        dep_regex = rules.get("mock_deps_regex")
        if dep_regex:
            for dep in mock_deps:
                if re.match(dep_regex, dep):
                    matched = True
                    break

        # mock_deps_contains
        if not matched:
            for needle in rules.get("mock_deps_contains", []):
                if any(needle in dep for dep in mock_deps):
                    matched = True
                    break

        # extends_contains
        if not matched:
            for needle in rules.get("extends_contains", []):
                if needle in extends:
                    matched = True
                    break

        # calls_pattern
        if not matched:
            for pat in rules.get("calls_pattern", []):
                if re.search(pat, calls_text):
                    matched = True
                    break

        if matched:
            hits.append(t["id"])

    # 按预设优先级排序
    priority = {"jpa_repository": 1, "shiro_auth": 2, "redis_cache": 3}
    hits.sort(key=lambda x: priority.get(x, 99))
    return hits


# ============================================================
# Prompt 组装
# ============================================================

SYSTEM_PROMPT = """你是风鸟后端(RiskBird Spring Boot 2.1.1)的单元测试生成专家,代号"百灵"。

核心原则:
1. **抄模板不写代码**: 优先命中 Mock 模板并按其结构写测试,只在业务差异点改字段和断言
2. **场景分组**: 每次生成针对一个具体场景组(normal/boundary/exception),产出独立的 @Test 方法
3. **零幻觉**: 所有 Mock 方法签名、实体字段、依赖类型必须与提供的知识库条目完全一致
4. **可编译**: 产出的代码必须能通过 javac 编译,不允许:
   - 虚构不存在的方法签名
   - import 不存在的类
   - 使用知识库未声明的字段
5. **JUnit 版本**: 使用 JUnit 4 + Mockito 2.23 + Spring Boot 2.1.1 内置版本
   - 禁止用 mockStatic / MockedStatic (需要 Mockito 3.4+)
   - 禁止用 @ExtendWith (JUnit 5 专属)
   - 用 @RunWith(MockitoJUnitRunner.class) 或 MockitoAnnotations.initMocks()
6. **按命中模板的 pitfalls 工作**: 风鸟特有的约束(BaseService dao 注入/Shiro ThreadContext/RedisTemplate NPE 等)
   不再写死在本 prompt 里,而是通过 user message 的"## 命中模板的常见陷阱"段动态注入,
   只命中对应模板才注入对应约束(借鉴 Hermes Skill Progressive Disclosure)。

必须通过 submit_test_methods 工具提交产出,禁止用文本回复。
"""


# 强制结构化输出的 tool schema(借鉴啄木鸟 submit_review_items 的做法)
SUBMIT_TEST_METHODS_TOOL = {
    "name": "submit_test_methods",
    "description": "提交为某个 (被测方法 × 场景组) 生成的单元测试方法列表。每次调用对应一个场景组。",
    "input_schema": {
        "type": "object",
        "properties": {
            "test_methods": {
                "type": "array",
                "description": "本场景组下的 @Test 方法 Java 源码片段列表,每个元素是一个完整的 @Test 注解的方法",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "extra_imports": {
                "type": "array",
                "description": "本场景组需要的额外 import 全限定名列表(不含 java.lang.*),模板里已有的 import 不要重复",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["test_methods"],
    },
}


def _camel_case(name):
    """AiRobotChatServiceImpl -> aiRobotChatServiceImpl"""
    if not name:
        return name
    return name[0].lower() + name[1:]


def build_user_message(job: GenerationJob):
    """为一个生成任务组装 user message"""
    klass = job.klass_entry
    m = job.method

    # 只取当前方法的 calls 前 15 条,避免 prompt 过长
    calls = m.get("calls", [])[:15]
    calls_str = "\n".join(f"  - {c['target']} ({c['kind']})" for c in calls)

    # 所有字段
    fields_str = "\n".join(
        f"  - {f['type']} {f['name']}" + (f" [{f['inject']}]" if f.get('inject') else "")
        for f in klass.get("fields", [])
    )

    # 模板内容 + 命中模板的常见陷阱 (借鉴 Hermes Skill frontmatter 的 pitfalls 字段)
    # Progressive Disclosure: 只注入命中模板的 pitfalls,不命中的约束不污染 prompt
    tmpl_section = ""
    tmpl_pitfalls = []
    if job.template_contents:
        for tid, content in job.template_contents.items():
            tmpl_section += f"\n### 命中 Mock 模板: {tid}\n```java\n{content}\n```\n"
        # 从 job.templates 收集命中模板的 notes(对应 Hermes Skill 的 pitfalls 字段)
        for t in (job.templates or []):
            notes = t.get("notes") or []
            if notes:
                tmpl_pitfalls.append((t["id"], notes))
    else:
        tmpl_section = "\n(本方法未命中任何 Mock 模板,需要自行判断 Mock 策略)\n"

    pitfalls_section = ""
    if tmpl_pitfalls:
        pitfalls_section = "\n## 命中模板的常见陷阱(严格遵守)\n"
        pitfalls_section += "这些约束原本写在 SYSTEM_PROMPT 里,现在按命中模板动态注入,只看你真正用到的模板。\n"
        for tid, notes in tmpl_pitfalls:
            pitfalls_section += f"\n### {tid}\n"
            for n in notes:
                pitfalls_section += f"- {n}\n"

    # 真实 imports(防止 LLM 瞎猜 FQN — 胶水编程核心:抄,不写)
    real_imports_section = ""
    if job.real_imports:
        real_imports_str = "\n".join(f"  - {imp}" for imp in job.real_imports)
        real_imports_section = f"""
## 被测类的真实 import 清单(强制复用)

以下是被测类 .java 源文件中的真实 import。**如果你需要使用这些类,必须按这里的 FQN 引用,
禁止自行推断包路径**。常见陷阱:实体类 `AiRobotChat` 的真实包不是 `entity/domain/vo`,而是下面列的路径。

{real_imports_str}
"""

    return f"""## 被测类

**FQN**: `{klass['fqn']}`
**Package**: `{klass['package']}`
**Extends**: `{klass.get('extends', '(none)')}`
**Implements**: {klass.get('implements', [])}
**Class Mock Deps**: {klass.get('class_mock_deps', [])}

### 成员字段
{fields_str or '  (无字段)'}

## 被测方法

**Signature**: `{m['signature']}`
**Nature**: {m['nature']}
**Annotations**: {m.get('annotations', [])}
**Mock Deps(本方法相关)**: {m.get('mock_deps', [])}

### 方法内调用(前 15 条)
{calls_str or '  (无调用)'}

## 本次生成目标

**场景组**: {job.scenario_name} ({job.scenario_id})
**场景描述**: {job.scenario_desc}

请为被测方法 `{m['name']}` 生成 2-3 个针对**{job.scenario_name}**的 @Test 方法。

命名约定: `should_xxx_when_yyy`(例如 `should_return_uid_when_save_valid_chat`)

{tmpl_section}
{pitfalls_section}
{real_imports_section}

## 要求
1. 每个 @Test 方法必须包含 Given/When/Then 三段注释
2. 断言用 assertEquals / assertNull / assertNotNull / assertTrue 等 JUnit 4 风格
3. 如果模板已给出 setUp 结构,假定它已存在,只产出 @Test 方法体
4. extra_imports 只列上面"真实 import 清单"外的额外 import(如 Mockito/JUnit/测试工具类)
5. 禁止生成 pass-through 测试(只调用方法不断言)
6. 禁止使用 `import org.mockito.Mockito.xxx;` 这种语法 — 必须用 `import static org.mockito.Mockito.*;`
   或直接写全限定名,不要在 extra_imports 里放 static member

调用 submit_test_methods 工具返回结果。
"""


# ============================================================
# LLM 调用
# ============================================================

def generate_for_job(client, model, job: GenerationJob) -> GenerationResult:
    """单次 LLM 调用生成一个 job 的测试方法(强制 tool_choice)"""
    try:
        user_msg = build_user_message(job)
        response = client.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=[SUBMIT_TEST_METHODS_TOOL],
            tool_choice={"type": "any"},
        )

        # 从 tool_use block 抽取结构化数据
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_test_methods":
                data = block.input or {}
                return GenerationResult(
                    job=job,
                    test_methods=data.get("test_methods", []) or [],
                    extra_imports=data.get("extra_imports", []) or [],
                )

        # 兜底: 没拿到 tool_use (应该很少见,因为 tool_choice=any)
        text = "".join(b.text for b in response.content if b.type == "text")
        log.warning(f"[{job.method['name']}/{job.scenario_id}] 无 tool_use block, 文本长度 {len(text)}")
        return GenerationResult(job=job, test_methods=[], extra_imports=[], error="no tool_use block")
    except Exception as e:
        log.error(f"[{job.method['name']}/{job.scenario_id}] 生成失败: {type(e).__name__}: {e}")
        return GenerationResult(job=job, test_methods=[], extra_imports=[], error=str(e))


async def generate_all(client, model, jobs):
    """并行生成所有 job(线程池包装同步 client.create)"""
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, generate_for_job, client, model, job)
        for job in jobs
    ]
    return await asyncio.gather(*tasks)


# ============================================================
# 测试文件组装
# ============================================================

# 基础 imports(JUnit 4 + Mockito 2.x)
BASE_IMPORTS = [
    "org.junit.Before",
    "org.junit.Test",
    "org.junit.runner.RunWith",
    "org.mockito.InjectMocks",
    "org.mockito.Mock",
    "org.mockito.MockitoAnnotations",
    "org.mockito.junit.MockitoJUnitRunner",
    "org.springframework.test.util.ReflectionTestUtils",
    "java.util.Optional",
    "java.util.Arrays",
    "java.util.Collections",
    "java.util.List",
    "static org.junit.Assert.*",
    "static org.mockito.ArgumentMatchers.*",
    "static org.mockito.Mockito.*",
]


def assemble_test_file(klass_entry, results):
    """把所有 (method, scenario) 的生成结果组装成完整的 .java 文件

    结构:
        package <same as CUT>;

        imports...

        @RunWith(MockitoJUnitRunner.class)
        public class XxxTest {
            @Mock private Repo repo;
            @InjectMocks private Xxx cut;

            @Before public void setUp() { ... }

            // --- 正常场景 ---
            @Test ...

            // --- 边界场景 ---
            @Test ...

            // --- 异常场景 ---
            @Test ...
        }
    """
    cut = klass_entry["class_name"]
    cut_field = _camel_case(cut)
    pkg = klass_entry["package"]

    # 收集 imports
    imports = set(BASE_IMPORTS)
    for r in results:
        for imp in r.extra_imports:
            imports.add(imp)
    # 被测类自己的 import
    imports.add(f"{klass_entry['fqn']}")
    # mock 依赖的 import (best effort)
    for dep in klass_entry.get("class_mock_deps", []):
        imports.add(dep)  # 只有类名不含包的话 import 会不完整,后续编译修复阶段兜底

    imports_lines = sorted(imp for imp in imports if "." in imp)
    imports_code = "\n".join(f"import {imp};" for imp in imports_lines)

    # @Mock 字段(从 class_mock_deps 抽)
    mock_fields = []
    inject_lines = []
    for dep in klass_entry.get("class_mock_deps", []):
        simple = dep.split(".")[-1].split("<")[0]
        f_name = _camel_case(simple)
        mock_fields.append(f"    @Mock\n    private {simple} {f_name};")
        # 如果看起来是 Repository 类型,加 ReflectionTestUtils 注入(BaseService 父类私有字段)
        if "Repository" in simple:
            inject_lines.append(f'        ReflectionTestUtils.setField({cut_field}, "dao", {f_name});')

    # 如果 class_mock_deps 为空但通过 BaseService 泛型提取了 repo,手动补
    extends = klass_entry.get("extends", "")
    m = re.match(r"BaseService<\s*\w+\s*,\s*\w+\s*,\s*(\w+)\s*>", extends)
    if m and not any("Repository" in d for d in klass_entry.get("class_mock_deps", [])):
        repo = m.group(1)
        f_name = _camel_case(repo)
        mock_fields.insert(0, f"    @Mock\n    private {repo} {f_name};")
        inject_lines.insert(0, f'        ReflectionTestUtils.setField({cut_field}, "dao", {f_name});')

    mock_fields_code = "\n\n".join(mock_fields) if mock_fields else "    // TODO: 声明 Mock 依赖"

    # @Before setUp
    setup_code = "    @Before\n    public void setUp() {\n"
    setup_code += "        MockitoAnnotations.initMocks(this);\n"
    for line in inject_lines:
        setup_code += line + "\n"
    setup_code += "    }"

    # 按场景顺序组装 test 方法
    test_methods_by_scenario = {sid: [] for sid, _, _ in SCENARIO_GROUPS}
    for r in results:
        if r.error or not r.test_methods:
            continue
        test_methods_by_scenario[r.job.scenario_id].extend(r.test_methods)

    tests_code = ""
    for sid, sname, _ in SCENARIO_GROUPS:
        methods = test_methods_by_scenario[sid]
        if not methods:
            continue
        tests_code += f"\n    // --- {sname} ---\n\n"
        for m_code in methods:
            m_code = m_code.strip()
            if not m_code.startswith("    "):
                m_code = "    " + m_code.replace("\n", "\n    ")
            tests_code += m_code + "\n\n"

    # 组装完整文件
    content = f"""package {pkg};

{imports_code}

/**
 * 风鸟后端测试 Agent(百灵)自动生成
 * 被测类: {klass_entry['fqn']}
 * 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
 */
@RunWith(MockitoJUnitRunner.class)
public class {cut}Test {{

{mock_fields_code}

    @InjectMocks
    private {cut} {cut_field};

{setup_code}
{tests_code}
}}
"""
    return content


# ============================================================
# 主流程
# ============================================================

@log_agent_call("百灵测试 Agent")
def run_test_agent(target_class, knowledge_path, templates_dir, output_dir, model_tier="sonnet", max_methods=None):
    """主入口"""
    log.info(f"目标: {target_class}")

    # 1. 加载知识库
    knowledge = load_knowledge(knowledge_path)
    klass_entry = find_class_by_name(knowledge, target_class)
    if not klass_entry:
        log.error(f"知识库中找不到类: {target_class}")
        return 1

    log.info(f"命中: {klass_entry['fqn']} ({klass_entry['method_count']} 方法)")

    # 2. 加载模板
    tmpl_index, tmpl_contents = load_mock_templates(templates_dir)

    # 3. 筛选值得测的方法(public 且非 static,不按 nature 过滤 — other 也可能是业务方法)
    methods = [
        m for m in klass_entry["methods"]
        if m["is_public"] and not m["is_static"]
    ]
    if max_methods and len(methods) > max_methods:
        # 优先保留事务类 > write > read > other(业务重要性排序)
        nature_priority = {"transactional": 0, "async": 1, "write": 2, "read": 3, "other": 4}
        methods.sort(key=lambda m: nature_priority.get(m["nature"], 9))
        methods = methods[:max_methods]
        log.info(f"max_methods={max_methods} 截取后: {[m['name'] for m in methods]}")
    else:
        log.info(f"待生成的方法: {[m['name'] for m in methods]}")

    # 4. 加载被测类的真实 imports(防止 LLM 瞎猜 FQN)
    real_imports = load_real_imports(knowledge, klass_entry)
    log.info(f"真实 imports 数: {len(real_imports)}")

    # 5. 为每个方法构建 jobs(方法 × 适用场景组)
    # 条件激活: requires_nature 不为空时,只对匹配 nature 的方法生成该场景组
    # (借鉴 Hermes Skill 的 requires_tools / fallback_for_toolsets 机制)
    jobs = []
    skipped_count = 0
    for m in methods:
        hit_ids = select_templates_for_method(klass_entry, m, tmpl_index)
        tmpl_ctns = {tid: tmpl_contents[tid] for tid in hit_ids}
        for group in SCENARIO_GROUPS:
            sid, sname, sdesc, req_nature = group
            # 条件激活: nature 不匹配则跳过(省 LLM 调用成本)
            if req_nature is not None and m.get("nature") not in req_nature:
                skipped_count += 1
                continue
            jobs.append(GenerationJob(
                klass_entry=klass_entry,
                method=m,
                scenario_id=sid,
                scenario_name=sname,
                scenario_desc=sdesc,
                templates=[t for t in tmpl_index["templates"] if t["id"] in hit_ids],
                template_contents=tmpl_ctns,
                real_imports=real_imports,
            ))
    log.info(f"生成任务数: {len(jobs)} ({len(methods)} 方法 × 适用场景,已跳过 {skipped_count} 个不适用组合)")

    # 5. 建 client + 并行生成
    client = create_client()
    model = MODEL_TIERS.get(model_tier, MODEL_TIERS["sonnet"])
    log.info(f"模型: {model}")
    log.info("开始并行生成...")

    t0 = time.time()
    results = asyncio.run(generate_all(client, model, jobs))
    elapsed = time.time() - t0

    ok = sum(1 for r in results if not r.error and r.test_methods)
    log.info(f"完成: {ok}/{len(jobs)} 成功 (耗时 {elapsed:.1f}s)")

    # 6. 组装 .java 文件
    content = assemble_test_file(klass_entry, results)

    # 7. W2.2: 编译修复阶段(import 规范化 + javalang parse check)
    log.info("执行 W2.2 修复阶段...")
    fixed_content, fix_report = fix_test_file(content, klass_entry, real_imports)
    log.info(f"修复: parse_ok={fix_report.parse_ok}, fixes={len(fix_report.fixes_applied)}, issues={len(fix_report.issues)}")
    for issue in fix_report.issues[:5]:
        log.info(f"  ! {issue}")
    if len(fix_report.issues) > 5:
        log.info(f"  ... 另有 {len(fix_report.issues) - 5} 条")

    # 8. 写出
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{target_class}Test.java")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fixed_content)
    log.info(f"输出: {out_path}")

    # 返回统计
    total_test_methods = sum(len(r.test_methods) for r in results if not r.error)
    log.info(f"共生成 {total_test_methods} 个 @Test 方法")
    return {
        "class": klass_entry["fqn"],
        "jobs": len(jobs),
        "ok_jobs": ok,
        "test_methods": total_test_methods,
        "elapsed_sec": round(elapsed, 1),
        "parse_ok": fix_report.parse_ok,
        "fix_issues": len(fix_report.issues),
        "output": out_path,
    }


def main():
    parser = argparse.ArgumentParser(description="风鸟后端测试 Agent(百灵)")
    parser.add_argument("--target-class", required=True, help="被测类名(如 AiRobotChatServiceImpl)")
    parser.add_argument("--knowledge", default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--templates", default=DEFAULT_TEMPLATES_DIR)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default="sonnet", choices=["opus", "sonnet", "haiku"])
    parser.add_argument("--max-methods", type=int, default=None,
                        help="最多测多少个方法(按 nature 优先级排序: transactional > write > read > other)")
    args = parser.parse_args()

    result = run_test_agent(
        target_class=args.target_class,
        knowledge_path=args.knowledge,
        templates_dir=args.templates,
        output_dir=args.output,
        model_tier=args.model,
        max_methods=args.max_methods,
    )
    if isinstance(result, int):
        return result
    print("\n" + "=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
