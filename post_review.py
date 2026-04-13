"""
评审后处理链 -- 鸮鹦整理 → 杜鹃验证 → 伯劳门禁 → 成就 → wiki push → 飞书通知
从 run_session.py 中抽出，保持主流程清晰
"""

import os
import subprocess


def wiki_push(wiki_path, prd_name, reviewer):
    """评审结束后推送知识库变更（需用户确认）"""
    if not os.path.isdir(os.path.join(wiki_path, ".git")):
        return
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=wiki_path,
    )
    if not status.stdout.strip():
        print("[wiki] 无变更，跳过推送")
        return
    subprocess.run(["git", "add", "."], cwd=wiki_path)
    subprocess.run(
        ["git", "commit", "-m", f"review: {prd_name} by {reviewer}"],
        cwd=wiki_path,
    )
    # 推送前需要用户确认（与 security.py CONFIRM_REQUIRED 策略一致）
    print(f"\n⚠ 即将推送知识库到远程仓库: {wiki_path}")
    answer = input("  是否继续 git push？(y/n): ").strip().lower()
    if answer != "y":
        print("[wiki] 用户取消推送，变更已 commit 但未 push")
        return
    result = subprocess.run(
        ["git", "push"], capture_output=True, text=True, cwd=wiki_path,
    )
    if result.returncode == 0:
        print(f"[wiki] 知识库已推送到 GitHub")
    else:
        print(f"[wiki] push 失败: {result.stderr.strip()[:80]}")


def run_post_review(workspace, wiki_path, prd_name, reviewer, model_tier, parallel_result=None, feishu_webhook=""):
    """
    评审结束后的后处理链，按顺序执行：
    1. 鸮鹦知识库健康检查 + 自动修复
    2. 杜鹃依据验证
    3. 伯劳质量门禁
    4. 成就检查
    5. 更新知识森林
    6. Wiki push
    7. 飞书通知
    """
    # 1. 鸮鹦自动整理 wiki
    from kakapo_dream import scan_wiki_health, auto_fix, generate_diff_report, rebuild_index, format_health_report
    from wiki_lock import wiki_write_lock
    print("\n" + "=" * 60)
    print("鸮鹦夜间巡逻 — 知识库健康检查")
    print("=" * 60)
    health = scan_wiki_health(wiki_path)
    total_issues, health_text = format_health_report(health)
    if total_issues > 0:
        print(health_text)
        with wiki_write_lock(wiki_path):
            changes = auto_fix(wiki_path, health, dry_run=False)
            if changes:
                generate_diff_report(wiki_path, changes)
            rebuild_index(wiki_path)
        print(f"  鸮鹦：整理完毕，修复 {len(changes)} 处")
    else:
        print("  鸮鹦：森林状态良好，无需整理")

    # 2. 杜鹃依据验证
    output_dir = os.path.join(workspace, "output")
    report_files = [f for f in os.listdir(output_dir) if f.startswith("PRD_改动报告_") and f.endswith(".md")] if os.path.isdir(output_dir) else []
    if report_files:
        latest_report = os.path.join(output_dir, sorted(report_files)[-1])
        from cuckoo_parser import parse_review_report
        from cuckoo_scorer import verify_evidence as cuckoo_verify
        print("\n" + "=" * 60)
        print("杜鹃依据验证")
        print("=" * 60)
        cuckoo_items = parse_review_report(latest_report)
        if cuckoo_items:
            verified, failed, _ = cuckoo_verify(cuckoo_items, workspace)
            total = verified + failed
            reliability = verified / total if total > 0 else 0
            print(f"  杜鹃：依据验证 {verified}/{total} 通过 ({reliability:.0%})")
        else:
            print("  杜鹃：未在报告中找到改进项，跳过验证")

    # 3. 伯劳质量门禁
    from shrike_review import shrike_review, format_shrike_report
    from easter_eggs import get_phase_line
    phase_line = get_phase_line("phase4")
    if phase_line:
        print(f"\n  {phase_line}")
    print("\n" + "=" * 60)
    print("伯劳质量门禁 — 评审产出检查")
    print("=" * 60)
    shrike_result = shrike_review(workspace, wiki_path)
    shrike_report = format_shrike_report(shrike_result)
    print(shrike_report)
    if shrike_result["verdict"] == "FAIL":
        print("  伯劳：产出质量未达标，建议修正后再推送。")

    # 4. 成就检查
    from easter_eggs import check_achievements, format_achievement_unlock, update_forest_in_index
    review_items = parallel_result["items"] if parallel_result else None
    new_achievements = check_achievements(wiki_path, review_items=review_items)
    unlock_msg = format_achievement_unlock(new_achievements)
    if unlock_msg:
        print(unlock_msg)

    # 5. 更新知识森林
    with wiki_write_lock(wiki_path):
        update_forest_in_index(wiki_path)

    # 6. 推送 wiki
    with wiki_write_lock(wiki_path):
        wiki_push(wiki_path, prd_name, reviewer)

    # 7. 飞书通知
    if feishu_webhook:
        from security import notify_feishu
        notify_feishu(
            feishu_webhook,
            f"啄木鸟评审完成: {prd_name}",
            f"**PRD**: {prd_name}\n**评审人**: {reviewer}\n**模型**: {model_tier}",
        )
