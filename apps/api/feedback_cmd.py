"""生成"一键信鸽反馈"命令的 markdown 块,嵌入到 PRD 开发任务报告末尾。

不依赖 registry,所有参数从 workspace 上下文推断,只留 --code-dir 让 PM 填。
后续 Plan 6 的 registry 跑通后,PM 直接用 scan 模式会更省事,但这个块作为
"提示+文档"永远有用。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _infer_scope(workspace: str) -> str:
    """从 workspace 目录名提取 scope: workspace-sample -> sample module"""
    name = os.path.basename(os.path.normpath(workspace))
    if name.startswith("workspace-"):
        return name[len("workspace-"):]
    return ""


def _latest_prd_file(workspace: str) -> Optional[str]:
    """从 workspace/prd/ 目录找最新 mtime 的 .md 文件"""
    prd_dir = Path(workspace) / "prd"
    if not prd_dir.is_dir():
        return None
    mds = [p for p in prd_dir.glob("*.md") if p.is_file()]
    if not mds:
        return None
    latest = max(mds, key=lambda p: p.stat().st_mtime)
    return str(latest)


def build_feedback_command_block(
    workspace: str,
    prd_name: str,
    report_path: str,
) -> str:
    """生成 markdown 块,贴到 PRD_开发任务_*.md 末尾。

    用户后续工作流:
      1. AI Coding 完成后,记下本地仓库路径
      2. copy 下面的命令到终端,替换 <AI_Coding_本地仓库路径>
      3. 回车执行
    """
    scope = _infer_scope(workspace)
    prd_file = _latest_prd_file(workspace) or f"{workspace}/prd/{prd_name}.md"

    # 相对路径更 portable(从项目根跑)
    try:
        project_root = Path(__file__).parent
        report_rel = os.path.relpath(report_path, project_root)
        prd_rel = os.path.relpath(prd_file, project_root)
    except ValueError:
        # Windows 跨盘符 relpath 会抛 ValueError,降级用绝对路径
        report_rel = report_path
        prd_rel = prd_file

    # Windows 反斜杠在 bash 里是转义字符,统一转正斜杠保证 copy-paste 能用
    report_rel = report_rel.replace("\\", "/")
    prd_rel = prd_rel.replace("\\", "/")

    scope_arg = f" \\\n      --scope {scope}" if scope else ""
    scope_display = scope if scope else "(无)"

    return f"""
---

## 🐦 下一步: 信鸽反馈 (可选,但强烈推荐)

AI Coding 完成并合并代码后,把下面这行复制到终端执行,信鸽会自动采集反馈信号更新规则权重:

```bash
cd "C:/Users/20834/Desktop/agent/prd review" && python feedback.py \\
      --code-dir <AI_Coding_本地仓库路径> \\
      --report {report_rel} \\
      --prd {prd_rel} \\
      --prd-name {prd_name}{scope_arg}
```

**参数说明:**
- `--code-dir`: AI Coding 项目的本地 git 仓库路径(必填)
- `--report`: 已预填当前报告路径
- `--prd`: 已预填 workspace 下最新 PRD 文件
- `--scope`: 已预填 `{scope_display}`,从 workspace 名推断

**更轻的方式(推荐):** 如果你已经用 `register_repo.py` 注册过这个仓库,直接跑 `python feedback.py --scan-registered-repos` 即可,启动评审时也会自动提醒。
"""
