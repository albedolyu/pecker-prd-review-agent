"""
风鸟后端 Service 层代码分析器 — 百灵测试 Agent 阶段 1

目标:用 javalang 扫 RiskBirdApi/riskbird-core/service/ 下所有 Service 类,
构建结构化代码知识库,为后续测试生成提供上下文。

输出:workspace-风鸟-backend-test/knowledge/backend_call_graph.json

知识条目结构:
{
  "classes": {
      "com.xinshucredit.riskbird.service.ai.impl.AiRobotChatServiceImpl": {
          "file": "service/ai/impl/AiRobotChatServiceImpl.java",
          "package": "com.xinshucredit.riskbird.service.ai.impl",
          "extends": "BaseService<AiRobotChat, Long, AiRobotChatRepository>",
          "implements": ["IAiRobotChatService"],
          "annotations": ["@Service"],
          "fields": [
              {"name": "xxxService", "type": "IXxxService", "inject": "autowired"},
              ...
          ],
          "methods": [
              {
                  "name": "save",
                  "signature": "String save(RobotChatVoReq robotChatVoReq)",
                  "params": [{"name": "robotChatVoReq", "type": "RobotChatVoReq"}],
                  "return_type": "String",
                  "throws": [],
                  "annotations": ["@Override"],
                  "calls": [
                      {"target": "getDao().save", "kind": "this"},
                      {"target": "UUID.randomUUID", "kind": "static"},
                      ...
                  ],
                  "mock_deps": ["AiRobotChatRepository"],
                  "nature": "write"  // read/write/transactional/async
              },
              ...
          ]
      }
  },
  "stats": {
      "total_files": 87,
      "total_classes": 87,
      "total_methods": 600+,
      "by_nature": {"read": ..., "write": ..., "transactional": ..., "async": ...}
  }
}

用法:
    python riskbird_backend_analyzer.py \
        --src "C:/Users/20834/Desktop/RiskBirdApi/riskbird-core/src/main/java" \
        --pkg com.xinshucredit.riskbird.service \
        --output "workspace-风鸟-backend-test/knowledge/backend_call_graph.json"

    # 最小:只扫一个类
    python riskbird_backend_analyzer.py --single-class AiRobotChatServiceImpl
"""

import argparse
import json
import os
import sys
import traceback
from collections import defaultdict
from datetime import datetime

import javalang


# ============================================================
# 方法性质判定规则
# ============================================================

# 写操作的方法名前缀
WRITE_PREFIXES = ("save", "insert", "add", "create", "update", "modify",
                  "delete", "remove", "set", "clear", "reset", "bind", "unbind")

# 读操作的方法名前缀
READ_PREFIXES = ("get", "find", "query", "list", "search", "select",
                 "count", "exists", "has", "is", "check", "load", "fetch")

# 异步任务的注解
ASYNC_ANNOTATIONS = ("Async", "Scheduled")

# 事务注解
TRANSACTIONAL_ANNOTATIONS = ("Transactional",)


def classify_method_nature(method):
    """判定方法性质:read/write/transactional/async/other

    优先级:async > transactional > write > read > other
    """
    ann_names = [a.name for a in (method.annotations or [])]

    # async 最高优先级
    if any(a in ASYNC_ANNOTATIONS for a in ann_names):
        return "async"

    # transactional
    if any(a in TRANSACTIONAL_ANNOTATIONS for a in ann_names):
        return "transactional"

    name = (method.name or "").lower()
    if name.startswith(WRITE_PREFIXES):
        return "write"
    if name.startswith(READ_PREFIXES):
        return "read"
    return "other"


# ============================================================
# AST 解析辅助
# ============================================================

def _type_to_str(t):
    """把 javalang 的类型节点转成字符串,如 'List<String>'"""
    if t is None:
        return "void"
    if isinstance(t, str):
        return t
    # BasicType / ReferenceType
    name = getattr(t, "name", "") or ""
    args = getattr(t, "arguments", None)
    if args:
        inner = ", ".join(
            _type_to_str(a.type) if a and a.type else "?"
            for a in args
        )
        return f"{name}<{inner}>"
    sub = getattr(t, "sub_type", None)
    if sub:
        return f"{name}.{_type_to_str(sub)}"
    dims = getattr(t, "dimensions", None) or []
    suffix = "[]" * len(dims)
    return name + suffix


def _ann_names(annotations):
    """抽注解名列表,如 ['Service', 'Transactional']"""
    if not annotations:
        return []
    return [a.name for a in annotations if hasattr(a, "name")]


def _extract_calls(method_node):
    """从方法体里抽所有方法调用(MethodInvocation),返回 [{target, kind}]

    kind:
      - "this":     this.xxx() 或 xxx()(同类内)
      - "field":    fieldName.xxx()(通过成员字段)
      - "static":   ClassName.xxx()(静态调用)
      - "chained":  something.xxx().yyy()(链式)
    """
    calls = []
    if method_node.body is None:
        return calls
    try:
        for _, node in method_node.filter(javalang.tree.MethodInvocation):
            qualifier = node.qualifier or ""
            member = node.member or ""
            if not qualifier:
                target = member
                kind = "this"
            else:
                target = f"{qualifier}.{member}"
                # 判定 qualifier 首字母大写 → 大概率是类名 → static
                first = qualifier.split(".")[0]
                if first and first[0].isupper():
                    kind = "static"
                elif "." in qualifier:
                    kind = "chained"
                else:
                    kind = "field"
            calls.append({"target": target, "kind": kind})
    except Exception:
        pass
    return calls


def _guess_mock_deps(klass, method_node):
    """根据字段注入声明 + 方法体调用,推断本方法需要 Mock 哪些依赖

    策略:
      1. 从类字段中收集所有 @Autowired / @Resource 字段名 → 类型
      2. 从方法体的 MethodInvocation 中找以"字段名."开头的调用
      3. 命中的字段类型 = 这个方法需要 mock 的依赖
      4. 额外规则:getDao() / this.getDao() 调用 → 看 class extends BaseService<?,?,RepoType> 提取 RepoType
    """
    # 收集字段类型
    field_types = {}
    for f in klass.fields:
        for d in f.declarators:
            field_types[d.name] = _type_to_str(f.type)

    # 从 method 调用里提取字段调用
    mock_deps = set()
    if method_node.body:
        try:
            for _, node in method_node.filter(javalang.tree.MethodInvocation):
                q = node.qualifier or ""
                if not q or "." in q:
                    continue
                if q in field_types:
                    mock_deps.add(field_types[q])
        except Exception:
            pass

    # BaseService<Entity, Id, Repo> 的 Repo 类型
    ext = klass.extends
    if ext is not None:
        ext_name = getattr(ext, "name", "") or ""
        if "BaseService" in ext_name or "CrudService" in ext_name:
            args = getattr(ext, "arguments", None) or []
            if len(args) >= 3:
                repo_type = _type_to_str(args[2].type) if args[2].type else ""
                if repo_type:
                    mock_deps.add(repo_type)

    return sorted(mock_deps)


def _class_mock_deps(klass):
    """类级别的 mock 依赖清单(所有字段的类型,去重)"""
    deps = set()
    for f in klass.fields:
        ann = _ann_names(f.annotations)
        if not ann:
            continue
        if any(a in ("Autowired", "Resource", "Inject") for a in ann):
            deps.add(_type_to_str(f.type))
    return sorted(deps)


# ============================================================
# 单文件解析
# ============================================================

def analyze_java_file(path, rel_path):
    """解析一个 .java 文件,返回该文件中所有类的 knowledge entries

    Returns: list of class entries(一个 .java 可能有多个 class,但通常只有 1 个)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="gbk", errors="replace") as f:
            source = f.read()

    try:
        tree = javalang.parse.parse(source)
    except javalang.parser.JavaSyntaxError as e:
        return None, f"JavaSyntaxError: {e}"
    except Exception as e:
        return None, f"ParseError: {type(e).__name__}: {e}"

    pkg = tree.package.name if tree.package else ""
    entries = []

    for _, klass in tree.filter(javalang.tree.ClassDeclaration):
        fqn = f"{pkg}.{klass.name}" if pkg else klass.name

        # extends
        extends_str = ""
        if klass.extends is not None:
            extends_str = _type_to_str(klass.extends)

        # implements
        implements_list = []
        for impl in klass.implements or []:
            implements_list.append(_type_to_str(impl))

        # 类注解
        klass_annotations = _ann_names(klass.annotations)

        # 字段
        fields = []
        for f in klass.fields:
            f_ann = _ann_names(f.annotations)
            inject = None
            if "Autowired" in f_ann:
                inject = "autowired"
            elif "Resource" in f_ann:
                inject = "resource"
            elif "Inject" in f_ann:
                inject = "inject"
            for d in f.declarators:
                fields.append({
                    "name": d.name,
                    "type": _type_to_str(f.type),
                    "inject": inject,
                    "annotations": f_ann,
                })

        # 方法
        methods = []
        for m in klass.methods:
            params = []
            for p in m.parameters:
                params.append({"name": p.name, "type": _type_to_str(p.type)})
            ret_type = _type_to_str(m.return_type) if m.return_type else "void"
            signature_parts = [ret_type, m.name, "("]
            param_strs = [f"{p['type']} {p['name']}" for p in params]
            signature = f"{ret_type} {m.name}({', '.join(param_strs)})"

            throws_list = [t for t in (m.throws or [])]

            calls = _extract_calls(m)
            mock_deps = _guess_mock_deps(klass, m)
            nature = classify_method_nature(m)

            methods.append({
                "name": m.name,
                "signature": signature,
                "params": params,
                "return_type": ret_type,
                "throws": throws_list,
                "annotations": _ann_names(m.annotations),
                "calls": calls,
                "mock_deps": mock_deps,
                "nature": nature,
                "is_public": "public" in (m.modifiers or set()),
                "is_static": "static" in (m.modifiers or set()),
            })

        entries.append({
            "fqn": fqn,
            "class_name": klass.name,
            "package": pkg,
            "file": rel_path.replace("\\", "/"),
            "extends": extends_str,
            "implements": implements_list,
            "annotations": klass_annotations,
            "class_mock_deps": _class_mock_deps(klass),
            "fields": fields,
            "methods": methods,
            "method_count": len(methods),
        })

    return entries, None


# ============================================================
# 批量扫描
# ============================================================

def walk_service_dir(src_root, pkg_path):
    """遍历 Service 目录下所有 .java 文件"""
    service_dir = os.path.join(src_root, pkg_path.replace(".", os.sep))
    if not os.path.isdir(service_dir):
        raise FileNotFoundError(f"Service 目录不存在: {service_dir}")

    java_files = []
    for root, _, files in os.walk(service_dir):
        for fname in files:
            if fname.endswith(".java"):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, src_root)
                java_files.append((full, rel))
    return sorted(java_files)


def build_graph(src_root, pkg_path, single_class=None, verbose=False):
    """批量构建调用图"""
    print(f"扫描目录: {src_root}")
    print(f"包路径: {pkg_path}")

    java_files = walk_service_dir(src_root, pkg_path)
    print(f"发现 {len(java_files)} 个 .java 文件")

    if single_class:
        java_files = [(p, r) for p, r in java_files if single_class in p]
        print(f"单类模式 — 过滤到 {len(java_files)} 个文件(匹配 {single_class})")

    classes = {}
    parse_errors = []
    nature_counter = defaultdict(int)
    total_methods = 0

    for i, (full, rel) in enumerate(java_files, 1):
        if verbose or i % 50 == 0:
            print(f"  [{i}/{len(java_files)}] {rel}")
        entries, err = analyze_java_file(full, rel)
        if err:
            parse_errors.append({"file": rel, "error": err})
            continue
        for entry in entries or []:
            classes[entry["fqn"]] = entry
            total_methods += entry["method_count"]
            for m in entry["methods"]:
                nature_counter[m["nature"]] += 1

    stats = {
        "total_files": len(java_files),
        "total_classes": len(classes),
        "total_methods": total_methods,
        "parse_errors": len(parse_errors),
        "by_nature": dict(nature_counter),
    }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "src_root": src_root.replace("\\", "/"),
        "pkg_path": pkg_path,
        "stats": stats,
        "parse_errors": parse_errors[:20],  # 只保留前 20 条
        "classes": classes,
    }


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="风鸟后端 Service 层代码分析器 — 百灵测试 Agent 阶段 1"
    )
    parser.add_argument(
        "--src",
        default="C:/Users/20834/Desktop/RiskBirdApi/riskbird-core/src/main/java",
        help="Java 源码根目录",
    )
    parser.add_argument(
        "--pkg",
        default="com.xinshucredit.riskbird.service",
        help="要扫描的包路径",
    )
    parser.add_argument(
        "--output",
        default="workspace-风鸟-backend-test/knowledge/backend_call_graph.json",
        help="输出 JSON 路径",
    )
    parser.add_argument(
        "--single-class",
        default=None,
        help="只分析单个类名(用于调试)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="逐文件打印",
    )
    args = parser.parse_args()

    try:
        result = build_graph(args.src, args.pkg, args.single_class, args.verbose)
    except Exception as e:
        print(f"\nFATAL: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    stats = result["stats"]
    print()
    print("=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"总文件: {stats['total_files']}")
    print(f"总类: {stats['total_classes']}")
    print(f"总方法: {stats['total_methods']}")
    print(f"解析错误: {stats['parse_errors']}")
    print(f"方法性质分布: {stats['by_nature']}")
    print(f"输出: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
