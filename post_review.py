"""
评审后处理链 -- 鸮鹦整理 → 杜鹃验证 → 伯劳门禁 → 成就 → wiki push → 飞书通知
从 run_session.py 中抽出，保持主流程清晰
"""

import os
import subprocess
from contextlib import contextmanager

from logger import log_agent_call


def _is_noninteractive():
    """非交互模式检测(与 run_session._is_noninteractive 同步)"""
    return os.environ.get("PECKER_NONINTERACTIVE", "").lower() in ("1", "true", "yes")


@contextmanager
def _step(step_results, name, required=False):
    """后处理步骤执行器:捕获异常,汇总到 step_results

    - required=True: 步骤失败则中止整个后处理链(raise)
    - required=False: 步骤失败只告警,继续后续步骤

    用法:
        with _step(step_results, "鸮鹦整理", required=False):
            # 原来的阶段代码
    """
    try:
        yield
        step_results.append((name, "ok", ""))
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:100]}"
        if required:
            step_results.append((name, "failed", err))
            print(f"  [!] {name} 失败(required,中止链): {err}")
            raise
        else:
            step_results.append((name, "skipped", err))
            print(f"  [!] {name} 失败(non-required,继续): {err}")


def _print_step_summary(step_results):
    """打印后处理链执行概要"""
    if not step_results:
        return
    print("\n" + "=" * 60)
    print("后处理链执行概要")
    print("=" * 60)
    max_name = max(len(n) for n, _, _ in step_results)
    for name, status, detail in step_results:
        tag = {"ok": "✓", "skipped": "~", "failed": "✗"}.get(status, "?")
        line = f"  {tag} {name:<{max_name}}  {status}"
        if detail:
            line += f"  ({detail})"
        print(line)


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
    if _is_noninteractive():
        # 非交互模式:默认跳过 push(保守策略,避免未经确认的 git push 出问题)
        print("  [non-interactive] 跳过 git push,变更已 commit 但未 push")
        print("  如需自动 push,设置 PECKER_AUTO_PUSH=1")
        if os.environ.get("PECKER_AUTO_PUSH", "").lower() not in ("1", "true", "yes"):
            return
    else:
        try:
            answer = input("  是否继续 git push？(y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
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


@log_agent_call("后处理链")
def run_post_review(workspace, wiki_path, prd_name, reviewer, model_tier, parallel_result=None, feishu_webhook=""):
    """
    评审结束后的后处理链,按顺序执行:
    1. 鸮鹦知识库健康检查 + 自动修复  (non-required)
    2. 杜鹃依据验证                    (non-required)
    3. 伯劳质量门禁                    (non-required,产出 verdict 只告警)
    4. 成就检查                        (non-required)
    5. 更新知识森林                    (non-required)
    5.5 开发任务报告                   (non-required)
    6. Wiki push                       (non-required,失败不阻断记忆/dashboard)
    7. 评审记忆提取                    (non-required)
    8. Dashboard 生成                  (non-required)
    9. 飞书通知                        (non-required)

    注意:当前所有步骤都是 non-required —— 任何单步失败都只告警,不阻断后续。
    最终 _print_step_summary 打印完整状态表。
    """
    step_results = []

    # 1. 鸮鹦自动整理 wiki
    with _step(step_results, "鸮鹦知识库整理", required=False):
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
            print(f"  鸮鹦:整理完毕,修复 {len(changes)} 处")
        else:
            print("  鸮鹦:森林状态良好,无需整理")

    # 2. 杜鹃依据验证
    with _step(step_results, "杜鹃依据验证", required=False):
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
                print(f"  杜鹃:依据验证 {verified}/{total} 通过 ({reliability:.0%})")
            else:
                print("  杜鹃:未在报告中找到改进项,跳过验证")

    # 3. 伯劳质量门禁
    with _step(step_results, "伯劳质量门禁", required=False):
        from shrike_review import shrike_review, format_shrike_report
        from easter_eggs import get_phase_line
        phase_line = get_phase_line("phase4")
        if phase_line:
            print(f"\n  {phase_line}")
        print("\n" + "=" * 60)
        print("伯劳质量门禁 — 评审产出检查")
        print("=" * 60)
        # v1.2(B1): 传入 parallel_result 让 Gate 6 依据可靠性检查生效
        shrike_result = shrike_review(workspace, wiki_path, parallel_result=parallel_result)
        shrike_report = format_shrike_report(shrike_result)
        print(shrike_report)
        if shrike_result["verdict"] == "FAIL":
            print("  伯劳:产出质量未达标,建议修正后再推送。")

    # 4. 成就检查
    with _step(step_results, "成就检查", required=False):
        from easter_eggs import check_achievements, format_achievement_unlock, update_forest_in_index
        review_items = parallel_result["items"] if parallel_result else None
        new_achievements = check_achievements(wiki_path, review_items=review_items)
        unlock_msg = format_achievement_unlock(new_achievements)
        if unlock_msg:
            print(unlock_msg)

    # 5. 更新知识森林
    with _step(step_results, "知识森林更新", required=False):
        from easter_eggs import update_forest_in_index
        from wiki_lock import wiki_write_lock
        with wiki_write_lock(wiki_path):
            update_forest_in_index(wiki_path)

    # 5.5 生成开发任务报告(可执行化)
    with _step(step_results, "开发任务报告", required=False):
        from report_builder import build_actionable_report
        prd_content_for_report = None
        prd_dir = os.path.join(workspace, "prd")
        if os.path.isdir(prd_dir):
            prd_files_list = [f for f in os.listdir(prd_dir) if f.endswith(".md")]
            if prd_files_list:
                parts = []
                for pf in sorted(prd_files_list):
                    with open(os.path.join(prd_dir, pf), "r", encoding="utf-8") as f:
                        parts.append(f.read())
                prd_content_for_report = "\n\n".join(parts)

        items_for_report = parallel_result["items"] if parallel_result else []
        peck = parallel_result.get("peck_score") if parallel_result else None
        # 工程化修复层(借鉴百灵 riskbird_test_fixer): 补齐 evidence_type + 调 verify_evidence 回写 verification_status
        if items_for_report:
            try:
                from review_fixer import fix_review_items
                items_for_report, _fix_stats = fix_review_items(items_for_report, workspace)
                print(f"  [修复] items 已修复: 推断类型 {_fix_stats['inferred_type']}, "
                      f"验证通过 {_fix_stats['verified']}, 失败 {_fix_stats['failed']}, "
                      f"未验证 {_fix_stats['unchecked']}, A/B 降权 {_fix_stats['downgraded']}")
            except Exception as _e:
                print(f"  [修复] fix_review_items 失败: {_e}")

        # 缺失 ⑥ Phase 3 批量决策: 非交互模式下按 confidence 自动 Y/N
        _auto_decide = os.environ.get("PECKER_AUTO_DECIDE", "off")
        if _auto_decide != "off" and items_for_report:
            _auto_y = _auto_n = _auto_pending = 0
            for it in items_for_report:
                conf = it.get("confidence_score", 0.5)
                if _auto_decide == "accept-all":
                    it["status"] = "confirmed"
                    _auto_y += 1
                elif _auto_decide == "reject-all":
                    it["status"] = "rejected"
                    _auto_n += 1
                else:  # by-confidence
                    if conf >= 0.8:
                        it["status"] = "confirmed"
                        _auto_y += 1
                    elif conf < 0.5:
                        it["status"] = "rejected"
                        _auto_n += 1
                    else:
                        it["status"] = "pending"
                        _auto_pending += 1
            print(f"  [auto-decide={_auto_decide}] Y={_auto_y} N={_auto_n} pending={_auto_pending}")

        if items_for_report:
            try:
                from review.implement_convention import annotate_review_items
                items_for_report = annotate_review_items(items_for_report)
            except Exception as _e:
                print(f"  [警告] 标记实现约定失败(不阻断): {str(_e)[:60]}")

        if items_for_report and prd_content_for_report:
            # 步骤 3: profile (chill/strict) 从 env 读, session_setup 已设 PECKER_PROFILE
            _profile = os.environ.get("PECKER_PROFILE", "chill")
            report = build_actionable_report(
                items_for_report, prd_content_for_report,
                prd_name, reviewer, peck, profile=_profile,
            )
            if report:
                from datetime import datetime as _dt
                import json as _json
                import re as _re
                date_tag = _dt.now().strftime('%Y%m%d')
                # 文件名带 reviewer 后缀,防止多人同天评同名 PRD 互相覆盖
                _rev = (reviewer or "unknown").strip() or "unknown"
                _rev_safe = _re.sub(r'[\\/:*?"<>|\s]+', '_', _rev)[:20]
                report_path = os.path.join(workspace, "output", f"PRD_开发任务_{date_tag}_{_rev_safe}.md")
                # 生成一键信鸽命令块,追加到报告末尾(Plan 5)
                try:
                    from feedback_cmd import build_feedback_command_block
                    feedback_block = build_feedback_command_block(workspace, prd_name, report_path)
                except Exception as _e:
                    feedback_block = ""
                    print(f"  [警告] 生成信鸽命令块失败(不阻断): {str(_e)[:60]}")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)
                    if feedback_block:
                        f.write(feedback_block)
                print(f"  [报告] 开发任务清单已生成: {report_path}")
                # 结构化 items JSON 持久化,让 cuckoo_eval/dashboard/diff 可回放
                items_json_path = os.path.join(workspace, "output", f"review_items_{date_tag}_{_rev_safe}.json")
                with open(items_json_path, "w", encoding="utf-8") as f:
                    _json.dump(items_for_report, f, ensure_ascii=False, indent=2)
                print(f"  [报告] 结构化 items 已落盘: {items_json_path}")

    # 5.6 缺失 ③ C 类回写 wiki: 把 PM 已确认的 C 类升级为 wiki 决策页
    with _step(step_results, "C类回写wiki", required=False):
        try:
            from promote_c_to_wiki import promote
            from datetime import datetime as _dt2
            _date_tag = _dt2.now().strftime('%Y%m%d')
            # 只在 auto-decide 接受了 C 类的情况下执行(避免污染 wiki)
            if items_for_report and any(
                (it.get("evidence_type") or "").upper() == "C" and it.get("status") == "confirmed"
                for it in items_for_report
            ):
                items_json_path_for_promote = os.path.join(workspace, "output", f"review_items_{_date_tag}.json")
                if os.path.isfile(items_json_path_for_promote):
                    print(f"  [promote] 检测到 C 类已确认 item,升级为 wiki 决策页...")
                    promote(workspace, items_file=items_json_path_for_promote, dry_run=False)
            else:
                print(f"  [promote] 无 C 类已确认 item,跳过")
        except Exception as _e:
            print(f"  [promote] C 类回写失败: {_e}")

    # 6. 推送 wiki
    with _step(step_results, "Wiki push", required=False):
        from wiki_lock import wiki_write_lock
        with wiki_write_lock(wiki_path):
            wiki_push(wiki_path, prd_name, reviewer)

    # 7. 评审记忆提取(CC extractMemories 模式)
    # P1: 产出直接写入 wiki/ 而非 .review_memory/*.json,向 Obsidian llm-wiki 靠拢
    with _step(step_results, "评审记忆提取", required=False):
        from review_memory import extract_memories
        from api_adapter import create_client as _create_client
        from agent_config import MODEL_TIERS as _tiers
        _client = _create_client()
        # messages 不在 post_review 的参数中,从 session 文件恢复
        from security import resume_session
        resumed = resume_session(os.path.join(workspace, "output"), prd_name)
        if resumed:
            _msgs, _ = resumed
            extracted = extract_memories(_client, _msgs, workspace, _tiers, prd_name, reviewer, wiki_path=wiki_path)
            if extracted:
                print(f"  [记忆] 提取 {len(extracted)} 条评审记忆 → wiki/")
            else:
                print(f"  [记忆] 无可提取的新记忆")

    # 8. Dashboard 生成
    with _step(step_results, "Dashboard 生成", required=False):
        from dashboard import generate_dashboard
        dashboard_path = generate_dashboard(workspace, prd_name)
        if dashboard_path:
            import webbrowser
            webbrowser.open(f"file:///{dashboard_path}")
            print(f"  [仪表盘] 已生成: {dashboard_path}")

    # 9. 飞书通知
    with _step(step_results, "飞书通知", required=False):
        if feishu_webhook:
            from security import notify_feishu
            notify_feishu(
                feishu_webhook,
                f"啄木鸟评审完成: {prd_name}",
                f"**PRD**: {prd_name}\n**评审人**: {reviewer}\n**模型**: {model_tier}",
            )

    # 10. Wiki log.md 追记(v1.2 D2,风鸟方法论)
    with _step(step_results, "Wiki log.md 追记", required=False):
        from wiki_log import append_log_entry
        item_count = len(parallel_result.get("items", [])) if parallel_result else 0
        retracted_count = len(parallel_result.get("retracted", [])) if parallel_result else 0
        detail = f"reviewer={reviewer} prd={prd_name} items={item_count} retracted={retracted_count}"
        if append_log_entry(wiki_path, "review_done", detail):
            print(f"  [log] 已追记到 wiki/log.md")
        else:
            print(f"  [log] 今日 review_done 条目已存在,跳过")

    # 最终:打印所有步骤的执行概要
    _print_step_summary(step_results)
