"""
百灵测试 Agent - W2.2 编译修复阶段

借鉴快手单测 3.2.2:"编译错误大多是类型不匹配、方法不存在、import 缺失,
可通过调用代码查看工具快速解决"

当前降级实现(无 javac):
  1. 工程化修复(javalang 解析 + 正则)
     - import 按 simple name 去重 (冲突时选真实 FQN)
     - 删除错误的 static import 语法 (如 `import org.mockito.Mockito.atLeastOnce`)
     - 合并真实 imports 到 Mockito/JUnit 基础 imports
     - 过滤空/无效的 import
  2. javalang parse check
     - 全文件能否被 javalang 成功 parse
  3. LLM 兜底修复(可选)
     - parse 失败 → 调 Sonnet 做一次修复

未来有 JDK 时扩展:
  - javac 真编译反馈
  - 错误按 type 分组(import 缺失 / 符号未定义 / 类型不匹配)
  - 每轮只修一类, 已修成功的不再参与
"""

import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

import javalang

from logger import get_logger

log = get_logger("fixer")


@dataclass
class FixReport:
    """修复报告"""
    parse_ok: bool = False
    issues: list = field(default_factory=list)
    fixes_applied: list = field(default_factory=list)
    final_imports: list = field(default_factory=list)


# ============================================================
# 1. Import 清洗 & 去重
# ============================================================

# 不应出现在 import 位置的 static 成员(必须用 import static)
STATIC_MEMBERS_BLACKLIST = {
    "org.mockito.Mockito.atLeastOnce",
    "org.mockito.Mockito.atLeast",
    "org.mockito.Mockito.atMost",
    "org.mockito.Mockito.atMostOnce",
    "org.mockito.Mockito.times",
    "org.mockito.Mockito.never",
    "org.mockito.Mockito.verify",
    "org.mockito.Mockito.when",
    "org.mockito.Mockito.mock",
    "org.mockito.Mockito.spy",
    "org.mockito.Mockito.doReturn",
    "org.mockito.Mockito.doThrow",
    "org.mockito.Mockito.doNothing",
    "org.mockito.ArgumentMatchers.any",
    "org.mockito.ArgumentMatchers.anyString",
    "org.mockito.ArgumentMatchers.anyLong",
    "org.mockito.ArgumentMatchers.eq",
    "org.mockito.ArgumentMatchers.isNull",
    "org.junit.Assert.assertEquals",
    "org.junit.Assert.assertNotNull",
    "org.junit.Assert.assertNull",
    "org.junit.Assert.assertTrue",
    "org.junit.Assert.assertFalse",
    "org.junit.Assert.fail",
}


def _extract_imports(content):
    """从 .java 文件内容里抽 import 行和剩余代码

    Returns:
        (imports_raw: list[str], package_line: str, code_body: str)
    """
    lines = content.split("\n")
    imports = []
    package_line = ""
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("package "):
            package_line = stripped
        elif stripped.startswith("import "):
            imports.append(stripped)
        elif stripped.startswith("/**") or stripped.startswith("*") or stripped.startswith("//") or stripped == "":
            continue
        elif stripped.startswith("@") or stripped.startswith("public ") or stripped.startswith("class "):
            body_start = i
            break

    body = "\n".join(lines[body_start:])
    return imports, package_line, body


def _parse_import_line(import_line):
    """解析 'import [static] com.xxx.Yyy;' → (is_static, fqn, simple_name)

    Bug fix: 兼容 LLM 在 extra_imports 返回的 'import static ...' 带前缀
    (被 assemble 又加一次 'import' 导致变成 'import import static ...')
    """
    s = import_line.strip()
    # 剥离重复的 "import " 前缀
    while s.startswith("import "):
        rest = s[len("import "):].strip()
        if rest.startswith("import ") or rest.startswith("static "):
            s = rest if rest.startswith("import ") else f"import {rest}"
            if s == import_line.strip():
                break
        else:
            s = f"import {rest}"
            break
    s = s.rstrip(";").strip()  # 去末尾分号和空白
    # 再加一次末尾的 ; 做正则
    candidate = s + ";"
    m = re.match(r"import\s+(static\s+)?([\w.]+?)(\*)?;", candidate)
    if not m:
        return None
    is_static = bool(m.group(1))
    fqn = m.group(2).rstrip(".")
    wildcard = m.group(3) == "*"
    simple = fqn.split(".")[-1] if not wildcard else "*"
    return {
        "is_static": is_static,
        "fqn": fqn,
        "simple": simple,
        "wildcard": wildcard,
        "raw": candidate,
    }


def _normalize_imports(imports_raw, real_imports, cut_package, issues):
    """合并 + 去重 import

    策略:
    1. 过滤 STATIC_MEMBERS_BLACKLIST(错误的 static 写成了普通 import)
    2. 合并 real_imports 到总集合
    3. 按 simple name 分组,冲突时:
       - 优先保留和被测类 package 最接近的 FQN
       - 次优先保留 real_imports 中出现的 FQN
    4. static import 不参与 simple name 去重(它们是成员而非类)
    """
    parsed = []

    # 解析原始
    for raw in imports_raw:
        p = _parse_import_line(raw)
        if not p:
            issues.append(f"无法解析的 import: {raw}")
            continue
        if not p["is_static"] and p["fqn"] in STATIC_MEMBERS_BLACKLIST:
            issues.append(f"删除错误的非 static import: {p['fqn']} (应为 static)")
            continue
        # 非法的 static import: 最后一段是大写开头的类名(无 member 且非 wildcard)
        # 例: `import static org.junit.Assert;` → 补齐为 `import static org.junit.Assert.*;`
        if p["is_static"] and not p["wildcard"]:
            last_seg = p["fqn"].split(".")[-1]
            if last_seg and last_seg[0].isupper():
                old_raw = p["raw"]
                p["wildcard"] = True
                p["raw"] = f"import static {p['fqn']}.*;"
                p["simple"] = "*"
                issues.append(f"static import 缺 member,补齐为通配符: {old_raw} → {p['raw']}")
        parsed.append(p)

    # 合并真实 imports(默认非 static)
    existing_fqns = {p["fqn"] for p in parsed if not p["wildcard"]}
    for fqn in real_imports or []:
        if fqn in existing_fqns:
            continue
        parsed.append({
            "is_static": False,
            "fqn": fqn,
            "simple": fqn.split(".")[-1],
            "wildcard": False,
            "raw": f"import {fqn};",
            "from_real": True,
        })
        existing_fqns.add(fqn)

    # 按 (is_static, simple) 分组去重
    # Bug fix: wildcard 按 fqn 去重(而非按 simple="*"),不同包的 .* 互不冲突
    kept = []
    seen_fqn_wildcard = set()  # 按 fqn 去重 wildcard
    seen_static_fqn = set()  # 按 fqn 去重 static(同一个类或方法只 import 一次)
    by_simple = defaultdict(list)

    for p in parsed:
        if p["wildcard"]:
            # wildcard 按 fqn 去重 — "java.util.*" 和 "com.xx.utils.*" 是两回事
            if p["fqn"] in seen_fqn_wildcard:
                issues.append(f"wildcard 重复丢弃: {p['raw']}")
                continue
            seen_fqn_wildcard.add(p["fqn"])
            kept.append(p)
            continue
        if p["is_static"]:
            if p["fqn"] in seen_static_fqn:
                continue
            seen_static_fqn.add(p["fqn"])
            kept.append(p)
            continue
        by_simple[p["simple"]].append(p)

    # 冲突时选真实 import(from_real=True 优先)或和 cut_package 最近的
    cut_pkg_parts = cut_package.split(".")
    for simple, group in by_simple.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # 冲突 — 选择规则(优先级: from_real > 新版 Mockito > 和 CUT package 最近)
        DEPRECATED_PACKAGES = ("org.mockito.runners",)  # 已废弃,优先级最低

        def score(p):
            if p.get("from_real"):
                return (0, 0)  # 最高优先级
            # 废弃包最低优先级
            for dep in DEPRECATED_PACKAGES:
                if p["fqn"].startswith(dep):
                    return (2, 0)
            fqn_parts = p["fqn"].split(".")
            common = 0
            for a, b in zip(fqn_parts, cut_pkg_parts):
                if a == b:
                    common += 1
                else:
                    break
            return (1, -common)
        group.sort(key=score)
        winner = group[0]
        losers = group[1:]
        for l in losers:
            issues.append(f"import 冲突去重: {simple} 保留 {winner['fqn']},丢弃 {l['fqn']}")
        kept.append(winner)

    # 排序:非 static 在前,按 FQN 字典序
    non_static = sorted([p for p in kept if not p["is_static"]], key=lambda x: x["fqn"])
    static_imports = sorted([p for p in kept if p["is_static"]], key=lambda x: x["fqn"])
    return non_static + static_imports


def _reassemble(imports_parsed, package_line, body):
    """把规范化的 imports 和 body 拼回"""
    lines = []
    if package_line:
        lines.append(package_line)
        lines.append("")
    # 去重(按最终生成的 import 行字符串)
    seen = set()
    for p in imports_parsed:
        if p["is_static"] and p["wildcard"]:
            import_line = f"import static {p['fqn']}.*;"
        elif p["is_static"]:
            import_line = f"import static {p['fqn']};"
        elif p["wildcard"]:
            import_line = f"import {p['fqn']}.*;"
        else:
            import_line = f"import {p['fqn']};"
        if import_line in seen:
            continue
        seen.add(import_line)
        lines.append(import_line)
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


# ============================================================
# 2. javalang parse check
# ============================================================

def _parse_check(content):
    """用 javalang 尝试整体 parse,返回 (ok, error_str)"""
    try:
        javalang.parse.parse(content)
        return True, None
    except javalang.parser.JavaSyntaxError as e:
        return False, f"JavaSyntaxError: {e.description} at {e.at}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============================================================
# 3. 主修复函数
# ============================================================

def fix_test_file(content, klass_entry, real_imports=None):
    """对生成的测试文件做工程化修复

    Returns: (fixed_content, FixReport)
    """
    report = FixReport()
    real_imports = real_imports or []
    cut_package = klass_entry.get("package", "")

    # 1. 抽 imports
    imports_raw, package_line, body = _extract_imports(content)

    # 2. 规范化 imports
    normalized = _normalize_imports(imports_raw, real_imports, cut_package, report.issues)
    report.final_imports = [p["fqn"] for p in normalized]
    report.fixes_applied.append(f"imports 规范化: {len(imports_raw)} → {len(normalized)}")

    # 3. 拼回
    fixed = _reassemble(normalized, package_line, body)

    # 4. javalang parse check
    ok, err = _parse_check(fixed)
    report.parse_ok = ok
    if not ok:
        report.issues.append(f"javalang parse 失败: {err}")
    else:
        report.fixes_applied.append("javalang parse 通过")

    return fixed, report


# ============================================================
# CLI(独立调用)
# ============================================================

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="百灵测试 Agent - 修复阶段")
    parser.add_argument("--input", required=True, help="待修复的 .java 测试文件")
    parser.add_argument("--knowledge", default="workspace-风鸟-backend-test/knowledge/backend_call_graph.json")
    parser.add_argument("--target-class", required=True, help="被测类名")
    parser.add_argument("--inplace", action="store_true", help="原地覆盖")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()

    with open(args.knowledge, "r", encoding="utf-8") as f:
        knowledge = json.load(f)

    from riskbird_test_agent import find_class_by_name, load_real_imports
    klass_entry = find_class_by_name(knowledge, args.target_class)
    if not klass_entry:
        print(f"[ERROR] 找不到类: {args.target_class}")
        return 1

    real_imports = load_real_imports(knowledge, klass_entry)
    print(f"真实 imports: {len(real_imports)} 条")

    fixed, report = fix_test_file(content, klass_entry, real_imports)

    print(f"\nparse_ok: {report.parse_ok}")
    print(f"最终 imports 数: {len(report.final_imports)}")
    print(f"\n修复记录:")
    for f in report.fixes_applied:
        print(f"  ✓ {f}")
    if report.issues:
        print(f"\n发现问题:")
        for i in report.issues:
            print(f"  ! {i}")

    out_path = args.input if args.inplace else args.input.replace(".java", ".fixed.java")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fixed)
    print(f"\n输出: {out_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
