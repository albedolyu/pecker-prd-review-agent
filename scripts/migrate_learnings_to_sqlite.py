"""一次性迁移: workspace/learnings/*.yaml + index.json → workspace/learnings.db.

用法:
    python scripts/migrate_learnings_to_sqlite.py --workspace workspace
    python scripts/migrate_learnings_to_sqlite.py --workspace workspace --overwrite

迁移策略:
  - 扫 workspace/learnings/ 下所有 *.yaml
  - 调 LearningsStore.import_yaml() (默认不覆盖已存在记录)
  - 迁移完打印导入条数 + sqlite 总条数
  - 旧 yaml + index.json 保留, 不删 (回滚保险)
"""
from __future__ import annotations

import argparse
import os
import sys

# 让脚本从 prd review/ 根目录跑
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from review.learnings_store import LearningsStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 yaml learnings → sqlite")
    parser.add_argument("--workspace", required=True, help="workspace 目录路径")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="同 id 已存在时覆盖 (默认跳过)",
    )
    parser.add_argument(
        "--src-dir",
        default=None,
        help="yaml 源目录, 默认 <workspace>/learnings",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.workspace):
        print(f"[ERROR] workspace 不存在: {args.workspace}", file=sys.stderr)
        return 1

    store = LearningsStore(args.workspace)
    src = args.src_dir or os.path.join(args.workspace, "learnings")
    if not os.path.isdir(src):
        print(f"[INFO] yaml 目录不存在 ({src}), 无需迁移")
        return 0

    yaml_count = sum(1 for fn in os.listdir(src) if fn.endswith(".yaml"))
    print(f"[INFO] 扫描 {src}: {yaml_count} 个 yaml 文件")
    imported = store.import_yaml(src, overwrite=args.overwrite)
    total = len(store.list_all())
    print(f"[OK] 导入成功 {imported} / {yaml_count}, sqlite 当前共 {total} 条")
    print(f"[OK] sqlite 路径: {store.db_path}")
    print("[INFO] 旧 yaml + index.json 保留, 验证无误后可手动删除")
    return 0


if __name__ == "__main__":
    sys.exit(main())
