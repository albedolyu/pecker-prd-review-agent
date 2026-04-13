"""
并行评审启动器 — 4 个 PRD 同时跑，测试 wiki 冲突
"""
import subprocess
import os
import sys
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
WIKI = os.path.join(BASE, "shared-wiki")
LOGS = os.path.join(BASE, "logs")
os.makedirs(LOGS, exist_ok=True)

# 环境变量（从 .env 读取，不硬编码）
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, ".env"), override=True)

env = os.environ.copy()
env["WIKI_PATH"] = WIKI
env.pop("ANTHROPIC_AUTH_TOKEN", None)

# 4 个评审任务
tasks = [
    ("纳税人资质", "workspace-纳税人资质", "洪荣棕"),
    ("对外投资", "workspace-对外投资", "许大伟"),
    ("产品召回", "workspace-产品召回", "潘驰"),
    ("侵权软件", "workspace-侵权软件", "潘驰"),
]

# 清理旧 session
for _, ws, _ in tasks:
    sessions_dir = os.path.join(BASE, ws, "output", ".sessions")
    if os.path.isdir(sessions_dir):
        for f in os.listdir(sessions_dir):
            os.remove(os.path.join(sessions_dir, f))

# 模拟用户输入：50 行"继续" + "exit"
fake_input = ("继续\n" * 50 + "exit\n").encode("utf-8")

# 启动 4 个子进程
procs = []
for name, ws, reviewer in tasks:
    log_path = os.path.join(LOGS, f"{name}.log")
    log_file = open(log_path, "w", encoding="utf-8")
    cmd = [
        sys.executable, "run_session.py", name,
        "--workspace", os.path.join(BASE, ws),
        "--reviewer", reviewer,
        "--no-parallel",
    ]
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT,
        cwd=BASE, env=env,
    )
    p.stdin.write(fake_input)
    p.stdin.close()
    procs.append((name, p, log_file, log_path))
    print(f"  启动: {name} (PID {p.pid})")

print(f"\n4 个评审已启动，日志在 {LOGS}/")
print("等待完成...\n")

# 轮询等待
while True:
    alive = [(name, p) for name, p, _, _ in procs if p.poll() is None]
    if not alive:
        break
    status = []
    for name, p, _, lp in procs:
        lines = 0
        try:
            with open(lp, "r", encoding="utf-8", errors="replace") as f:
                lines = sum(1 for _ in f)
        except:
            pass
        state = "RUNNING" if p.poll() is None else f"DONE({p.returncode})"
        status.append(f"[{name} {lines}L {state}]")
    print(" ".join(status))
    time.sleep(15)

# 最终结果
print("\n" + "=" * 60)
print("全部完成！")
print("=" * 60)
for name, p, log_file, lp in procs:
    log_file.close()
    lines = 0
    has_error = False
    with open(lp, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
        lines = len(content.splitlines())
        has_error = "Traceback" in content or "Error" in content
    print(f"  {name}: {lines}L | exit={p.returncode} | errors={'YES' if has_error else 'no'}")

# Wiki 冲突检查
print(f"\nWiki 文件数: {len(os.listdir(WIKI))}")
print("Wiki 文件列表:")
for f in sorted(os.listdir(WIKI)):
    print(f"  {f}")
