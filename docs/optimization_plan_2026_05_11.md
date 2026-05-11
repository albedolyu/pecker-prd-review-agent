# 啄木鸟团队 Beta 后 2 周优化计划 (for Codex)

> 起草时间: 2026-05-11
> 适用阶段: 团队 Beta 上线后 Week 1 → Week 3 扩大决策
> 执行者: Codex (可按任务独立拉分支, 每个任务一个 PR)
> 验收口径: 每个任务有 "Acceptance" 段, 必须通过其中列出的测试 / 命令才能合并
>
> 基线(必须守住, 不能退):
> - `python -m pytest tests -q` 1436+ passed
> - `cd web && npx.cmd tsc --noEmit` 0 error
> - `npm.cmd --prefix web test` 全量绿
> - `npm.cmd --prefix web run build` 通过
> - 有效一致性 ≥ 60% (STATUS.md 门禁)

## 执行顺序建议

```
P0 (本周必须做, 数据合规 + 稳定性)
  └─ T1 PRD 脱敏契约测试
  └─ T2 苍鹰失败率专项治理
  └─ T3 双远程推送防泄漏 hook

P1 (Week 2 扩到 5-6 人前做)
  └─ T4 持久化 TTL + 清理脚本
  └─ T5 PM 返工减少样本收集
  └─ T6 规则调权 A/B 证据链

P2 (Week 3 扩大决策前做)
  └─ T7 workspace-* 拆出主仓
  └─ T8 根目录散文件收进子包
  └─ T9 Streamlit legacy 退役
  └─ T10 docs/ 归档治理
```

每个任务都是**独立 PR**,不要合并。任务之间的依赖在下文显式标注。T1 允许拆成两个独立 PR: 先补契约测试, 再补出口点强制脱敏。

---

## T1 · PRD 脱敏契约测试 【P0 · 数据合规】

### 背景
5/10-5/11 连续 5 条 redact fix (`195582f` / `2cfbab7` / `abd9b82` / `4ab64c6` / `1115be7`) 说明 PRD 正文会以各种形式泄漏到可被非 admin 角色看到的地方。目前是**每爆一个修一个**, 需要上一层防御: 契约测试 + sanitize 集中点。

### Acceptance
- 新增 `tests/test_redaction_contract.py`, 覆盖以下断言(全部 PASS):
  - `event_store.jsonl` 事件 payload 中不含 PRD 正文子串(用 `_assert_no_prd_leak(event, prd_text)` 断言)
  - `finding_outcomes.db` 的 `evidence_content` 字段长度 ≤ 500 字符, 不含 PRD 前 2KB 任意 200 字连续子串
  - `.pecker_drafts/*.json` 对非 admin reviewer 不暴露 `supplemental_materials_raw` 和 `prd_body`
  - `/api/admin/usage_summary` 返回体中 `reviews[*].prd_name` 保留, 但 `reviews[*].prd_preview` 必须 ≤ 80 字符且掐头去尾加 `…`
  - `/api/review/jobs/{id}` 对非 reviewer 本人返回 404, 不是 200 空结果
  - `eval_reports/**/*.json` 中 `prd_source` 字段是路径引用, 不是 PRD 内联正文
- 所有断言用同一个 `prd_fixture` (长度 ≥ 4KB, 含 10 个罕见 token 锚点), 任意锚点命中视为泄漏。

### 实现步骤
1. 在 `api/sanitize.py` 新增 `redact_prd_content(obj: dict, prd_body: str) -> dict`, 对 `dict/list` 递归遍历字符串字段, 替换 PRD 子串为 `<prd-redacted len=N>`。
2. 在 **5 个出口点** 强制调用:
   - `api/stream.py` 的 `emit()` 前置钩子
   - `review/finding_outcomes_store.py` 的 `save()` 前置钩子
   - `api/routes/review_jobs.py` 的 `GET /jobs/{id}` 响应序列化
   - `api/routes/drafts.py` 的 `GET /drafts` 列表响应
   - `api/feedback_summary.py` / `api/usage_summary.py` 的聚合响应
3. 每个出口点加一条 `contract: NoPRDBody` 注释, 方便后续 code review 搜索。
4. 补 `tests/test_redaction_contract.py`, 对上述 5 个出口点跑真实请求 + fixture PRD。
5. 加 pre-commit 检查: `scripts/check_redaction_contract.py`, 搜索新增的 `emit(` / `store.save(` / `JSONResponse(` 调用是否在 5 个白名单出口, 不在就 warn。

### 涉及文件
- 新增: `tests/test_redaction_contract.py`, `scripts/check_redaction_contract.py`
- 修改: `api/sanitize.py`, `api/stream.py`, `api/feedback_summary.py`, `api/usage_summary.py`, `api/routes/review_jobs.py`, `api/routes/drafts.py`, `review/finding_outcomes_store.py`

### 风险 / 回滚
- 误伤风险: PRD 中的**常见短词**(如"用户", "订单")可能被误判为泄漏 → fixture 必须用罕见 token 锚点。
- 回滚: 契约测试独立, 失败不 block 其他模块; `redact_prd_content` 出问题时可用 env `PECKER_REDACT_STRICT=0` 降级为 log-only。

---

## T2 · 苍鹰失败率专项治理 【P0 · 稳定性】

### 背景
STATUS.md 上线前报告 **苍鹰终审失败率 20%** (`final_reviewer_done with error` / `final_reviewer_done` = 20%)。上线后 `374dbbe` / `4674d40` / `2effaff` 可能间接缓解, 但**没有数据证明**。需要先量化再治理。

### Acceptance
- 新增 `scripts/goshawk_failure_triage.py`, 从 `event_store.jsonl` 拉取最近 50 个 session 的 `final_reviewer_done` 事件, 输出:
  - 失败计数 / 总计数 / 失败率
  - 按 `error.type` 聚类 (timeout / json_parse / auth_401 / empty_output / other), 每类含 top 3 原始错误字符串
  - 按 `model` 聚类 (gpt55 / 其他降级路径)
- 根据聚类结果, 只治理真实 top 2 失败类型。若 top 2 包含以下类型, 在 `goshawk_advisor.py` 分别加:
  - timeout 类: 把 `_sanity_check_false_positives` 的 `route: advisor.goshawk.recheck` timeout 从 10s 提到 20s, 且加 `@retry(max=2, backoff=exponential)`
  - empty_output 类: `goshawk_empty_retry` 从默认关闭改为 1 次, 失败保留原 worker items (而非整个 session 失败)
- 新增 `tests/test_goshawk_failure_recovery.py`:
  - mock 上游 timeout, 验证 retry 生效且最终有 items
  - mock 空输出, 验证 fallback 到 worker items 而非 500
- STATUS.md 下次生成后, 苍鹰失败率 ≤ 10% (新指标写入 `stability_metrics.py` 并在 `generate_status.py` 输出, 不再是"已埋点 session 8"这种粗口径)

### 实现步骤
1. 先写 `scripts/goshawk_failure_triage.py` 跑真实数据, 把 top 2 错误类型写进 PR description。
2. 根据分类结果实施治理, 不要盲目加 retry。
3. 在 `scripts/generate_status.py` 新增 section "苍鹰失败类型分布", 显式展示 timeout / empty / parse / other 百分比。
4. 更新 `STATUS.md` 门禁: 新增 `[PASS] 苍鹰失败率 X% ≤ 15%` (灰度阈值, 稳定后提到 10%)。

### 涉及文件
- 新增: `scripts/goshawk_failure_triage.py`, `tests/test_goshawk_failure_recovery.py`
- 修改: `goshawk_advisor.py`, `scripts/stability_metrics.py`, `scripts/generate_status.py`, `tests/test_generate_status.py`

### 风险 / 回滚
- 加 retry 会拉长单次评审总耗时, 需要同步观察 `PECKER_MODEL_CALL_QUEUE_TIMEOUT=480` 够不够。
- 回滚: retry 逻辑用 env `PECKER_GOSHAWK_RETRY_ENABLED=0` 一键关闭。

---

## T3 · 双远程推送防泄漏 hook 【P0 · 数据合规】

### 背景
目前有两个 remote: `company-gitlab` (内网业务) + `origin` (GitHub 公开)。未来 `workspace-*/prd/*` / `eval_reports/*_pm_revision.md` / `finding_outcomes.db` / `shared-wiki/` 这类内容不能推到 GitHub。

目前仅靠 `.gitignore` 和人脑记忆, **不够**。

### Acceptance
- 新增 `scripts/check_push_target.py`, 作为 pre-push hook:
  - 检测目标 remote URL 是否包含 `github.com` / `gitlab.com` (非公司内网)
  - 若是公网 remote, 扫描 `git diff origin/main...HEAD` 的文件列表, 若命中以下路径模式则 block:
    - `workspace-*/prd/**`, `workspace-*/raw/**`, `workspace-*/output/**`
    - `eval_reports/**/*_pm_revision.md`, `eval_reports/**/*_zhiqu_handoff.md`
    - `**/finding_outcomes.db*`
    - `.pecker_drafts/**`
    - `.env*` (除 `.env.example`)
    - `shared-wiki/**` (待业务方确认后是否豁免)
  - 若命中, 打印具体文件列表 + bypass 指令 `git push --no-verify`
- 更新 `scripts/install_git_hooks.py` / `.ps1` / `.sh`, 把 pre-push 加进去(不是替换现有 hook, 是追加)。
- 新增 `tests/test_push_target_guard.py`, mock remote URL + diff, 覆盖 4 个场景:
  - push to gitlab + 敏感文件 → pass
  - push to github + 敏感文件 → block
  - push to github + 无敏感文件 → pass
  - push to github + `--no-verify` → pass (不跑 hook)

### 涉及文件
- 新增: `scripts/check_push_target.py`, `tests/test_push_target_guard.py`
- 修改: `scripts/install_git_hooks.py`, `scripts/install_git_hooks.sh`, `scripts/install_git_hooks.ps1`

### 风险 / 回滚
- 误伤风险: 路径模式可能误伤合法公开文件 → 推公司 GitLab pass, 推公网 remote 命中敏感路径直接 block, 由 `git push --no-verify` 作为人工兜底。
- 回滚: env `PECKER_PUSH_GUARD=0` 禁用, 或 `--no-verify`。

---

## T4 · 持久化 TTL + 清理脚本 【P1 · 数据合规】

### 背景
未脱敏 PRD 同时存在 6 个位置: `workspace-*/`, `.pecker_drafts/`, `finding_outcomes.db`, `event_store.jsonl`, `eval_reports/`, `logs/`。**没有过期策略**, 内网机器磁盘会被塞爆, 且"数据只放内网"的合规边界会随时间劣化。

### Acceptance
- 新增 `scripts/retention_sweep.py`, 支持 `--dry-run` / `--apply`:
  - `.pecker_drafts/*.json` mtime > 30 天 → 删除
  - `event_store.jsonl` > 500MB 时归档到 `event_store.YYYYMMDD.jsonl.gz` 并清空
  - `eval_reports/*.json` mtime > 90 天 → 压缩到 `eval_reports/archive/YYYY-MM.tar.gz`
  - `logs/*.log` mtime > 14 天 → 压缩归档
  - `finding_outcomes.db` 的 `findings` 表中 `created_at` > 180 天的行 → VACUUM 前迁到 `findings_archive` 表
- 可配置 TTL, 通过 env: `PECKER_RETENTION_DRAFT_DAYS=30` 等。
- 新增 `scripts/retention_report.py`, 输出各类数据当前占用 / 预计回收量, 不改数据。
- 新增 systemd timer 配置示例写入 `docs/internal_network_deployment_request.md`, 部署文档更新(加第 12 节 "数据过期清理")。
- 新增 `tests/test_retention_sweep.py`, 用 tmpdir 构造 fixture 验证 dry-run / apply 语义。

### 涉及文件
- 新增: `scripts/retention_sweep.py`, `scripts/retention_report.py`, `tests/test_retention_sweep.py`
- 修改: `docs/internal_network_deployment_request.md`, `.env.example`

### 风险 / 回滚
- 误删正在调试的数据 → 所有操作默认 `--dry-run`, 显式 `--apply` 才真删; 真删前备份到 `.trash/` 保留 7 天。

---

## T5 · PM 返工减少样本收集 【P1 · 反馈闭环】

### 背景
Week 3 扩大决策的**关键验收标准**是: "PM 能明确说出至少 2 类被减少的返工问题" (`@C:/Users/20834/Desktop/agent/prd review/docs/meetings/2026-05-07-team-beta-sync/02_decisions_and_rollout.md:82-87`)。

当前没有结构化收集机制, 靠周会口述会漏。

### Acceptance
- 在 `/review` Phase 4 (Report) 页面, 新增一个 "本次评审帮你避免了什么" 小卡片(非必填):
  - 3 个单选: "避免了字段口径返工" / "避免了体验流程返工" / "避免了实现风险返工" / "暂未看到" (多选)
  - 1 个短文本(≤ 100 字): "具体是哪条建议?" (可选)
- 提交后写入 `api/feedback_summary.py` 下游的 `pm_rework_avoidance` 表 (新增 `review/feedback_store.py` 的 sqlite table)。
- 在 `/system/usage` (admin dashboard) 新增 section "返工避免样本", 按周聚合, 显示:
  - 本周提交样本数 / Productive session 占比 (≥ 60% 算达标)
  - 按类别聚合(字段 / 体验 / 实现)
  - 最近 10 条短文本原文列表
- 新增 `tests/test_pm_rework_avoidance.py` + `web/tests/rework-feedback.test.ts` 覆盖表单提交 + admin 汇总。

### 涉及文件
- 新增: `review/feedback_store.py` (或扩展现有), `web/components/ReworkFeedback.tsx`, `web/tests/rework-feedback.test.ts`, `tests/test_pm_rework_avoidance.py`
- 修改: `web/components/phases/Phase4Report.tsx`, `api/feedback_summary.py`, `api/routes/feedback.py`, `web/app/system/usage/page.tsx`

### 风险 / 回滚
- PM 可能不填 → 设计上就是可选, 不 block 报告下载。加 toast "感谢反馈, 会用于下周规则校准" 做轻推动。

---

## T6 · 规则调权 A/B 证据链 【P1 · 反馈闭环】

### 背景
`9f2745f fix: tune review rules from PM rejections` 证明了反馈能反哺规则, 但**没有证据**证明调权后评审质量真的提升了。EMA + 时间衰减是理论设计, 需要**上线后对比实验**兜底。

### Acceptance
- 新增 `scripts/rule_perf_impact_report.py`:
  - 输入: 两个时间窗口 (e.g. 上线后第 1 周 vs 第 2 周)
  - 输出: 每条规则的 `confirmed / rejected / missed` 计数 + impact_score 变化 + 平均用户驳回原因 (`reject_reason_category`)
- 新增 `eval/route_eval/rule_impact_golden.py`: 锁定一份 10 份 PRD 的 golden set, 每周固定跑两次:
  - 一次使用**当前 impact_score**
  - 一次使用**neutral baseline** (所有规则 0.5)
  - 对比两次的 items 数 / P/R / PM 接受率, 写入 `eval_reports/rule_impact_YYYY-WW.md`
- 新增 `tests/test_rule_impact_report.py` 保证 golden set 不腐烂。
- 把 `rule_impact_YYYY-WW.md` 接入 `/system/usage`, admin 可看最近 4 周趋势折线。

### 涉及文件
- 新增: `scripts/rule_perf_impact_report.py`, `eval/route_eval/rule_impact_golden.py`, `tests/test_rule_impact_report.py`
- 修改: `web/app/system/usage/page.tsx` (加 "规则调权效果" tab)

### 风险 / 回滚
- golden set 10 份 PRD 每周跑两次 = 每周 80 次 worker 调用 + 20 次苍鹰, 按 $3/次 = $240/周。**需要先确认预算**再实施。
- 降级方案: golden set 缩到 3 份 PRD, 每两周跑一次。

### 依赖
- T5 完成后, `reject_reason_category` 数据量更充足。

---

## T7 · workspace-* 拆出主仓 【P2 · 仓库治理】

### 背景
主仓根目录有 10+ `workspace-*` 目录 (`workspace-fengniao-mediation/`, `workspace-points-payment/`, `workspace-劳动仲裁/` ...), 混入了真实业务数据。 未来扩到 20 人时, 并发写入同一个 git 仓库会炸; 且这些数据**绝对不能推到 origin (GitHub)**。

### Acceptance
- 新增 `scripts/migrate_workspace_to_external.py`:
  - 把 `workspace-*/` 迁到内网共享存储路径 (可配置, 如 `/mnt/pecker-workspaces/`), 保留符号链接或通过 env `PECKER_WORKSPACE_ROOT` 指向新位置。
  - 原仓库里只保留 `workspace-sample/` 作为新人上手样本。
- 更新 `api/routes/workspaces.py` 的 workspace 发现逻辑, 支持从 `PECKER_WORKSPACE_ROOT` 读取。
- 更新 `.gitignore`, 显式 ignore `workspace-*` 除 `workspace-sample`。
- 更新 `docs/internal_network_deployment_request.md` 第 7 节, 把 workspace 挂盘路径写明。
- `tests/test_workspace_discovery.py` 覆盖: 默认路径 / env 指向外部路径 / 仅 sample 可见 / 迁移脚本 dry-run。

### 涉及文件
- 新增: `scripts/migrate_workspace_to_external.py`, `tests/test_workspace_discovery.py`
- 修改: `api/routes/workspaces.py`, `.gitignore`, `docs/internal_network_deployment_request.md`, `.env.example`

### 风险 / 回滚
- **这是破坏性操作**, 需要**运维先在测试环境做一次**, 且保留 2 周 dual-write 期(新旧路径同时可读)。
- git history 中 `workspace-*` 的文件不动(不做 filter-branch), 只是 working tree 迁走。

### 依赖
- T3 (push guard) 必须先落地, 防止迁移期间误推到 GitHub。

---

## T8 · 根目录散文件收进子包 【P2 · 架构治理】

### 背景
`pyproject.toml` 里 `py-modules` 列了 47 个顶层模块, 根目录 55 个 Python 文件 / 18.7k 行。 `goshawk_advisor.py` / `kakapo_dream.py` / `shrike_review.py` / `feedback.py` / `cuckoo_*` / `feishu_*` 这些应该是 `agents/` 或 `birds/` 子包。

### Acceptance
- 新建 `birds/` 子包, 迁入:
  - `birds/goshawk.py` ← `goshawk_advisor.py`
  - `birds/kakapo.py` ← `kakapo_dream.py`
  - `birds/shrike.py` ← `shrike_review.py`
  - `birds/cuckoo.py` ← `cuckoo_eval.py` + `cuckoo_parser.py` + `cuckoo_scorer.py` (合并到子包内部)
  - `birds/pigeon.py` ← `feedback.py` (信鸽)
- 原路径保留 **thin re-export shim** 1 年 (加 `DeprecationWarning`), 防止外部脚本 / 部署配置断链。
- `pyproject.toml` 的 `py-modules` 对应条目保留, 新增 `packages=["birds"]`。
- 全量 `grep -r "import goshawk_advisor\|from goshawk_advisor"` 结果确认只在 shim 里引用, 其他都走 `from birds.goshawk import ...`。
- `tests/test_package_discovery.py` 扩展, 验证 shim 能正常工作且触发 `DeprecationWarning`。

### 涉及文件
- 新增: `birds/__init__.py`, `birds/goshawk.py`, `birds/kakapo.py`, `birds/shrike.py`, `birds/cuckoo.py`, `birds/pigeon.py`
- 修改: `pyproject.toml`, `tests/test_package_discovery.py`, **所有 import 这几个模块的文件** (预计 30+ 个文件, 脚本化迁移)
- 保留 shim: `goshawk_advisor.py` / `kakapo_dream.py` / `shrike_review.py` / `feedback.py` / `cuckoo_*.py` 各 5-10 行

### 风险 / 回滚
- **大面积 import 变更, 风险高**, 建议分两个 PR:
  - PR1: 新增 `birds/` + shim, 旧路径仍可用, 跑全测 1436 passed
  - PR2: 把内部 imports 切到 `birds.*`, 触发 deprecation warning 但不报错
- 回滚: PR2 revert 即可, PR1 保留。

### 依赖
- 建议在 T7 完成后做 (workspace 拆出后根目录才干净)。

---

## T9 · Streamlit legacy 退役 【P2 · 架构治理】

### 背景
`legacy/app.py` (Streamlit) 仍在仓库 + DEV.md 提到可作 fallback。 Next.js 主线已稳定, legacy 双轨长期不一致, 是未来 bug 来源。

### Acceptance
- `legacy/README.md` 新增大字段声明: "已退役, 不再维护, 2026-06-01 删除, 使用 Next.js 版: http://pecker.xxx.internal"
- `legacy/app.py` 启动时打印红字警告 + `time.sleep(3)` 强制延迟, 推动 PM 迁移。
- `docs/MIGRATION_v1_to_v2.md` 补完, 覆盖当前 Streamlit 能用但 Next.js 没有的 5 个能力(若有), 确认每个都已在 Next.js 实现 或 已废弃。
- 更新 `DEV.md` 删除 "终端 3 — Streamlit" 段落。
- 更新 `requirements.txt` 把 `streamlit>=1.35.0` 标注为 `# deprecated, remove 2026-06-01`。
- 新建 issue / todo 文件 `docs/legacy_retirement_plan.md`, 写明 2026-06-01 删除计划。

### Acceptance (2026-06-01 删除 PR)
- `rm -rf legacy/`, `requirements.txt` 删除 streamlit, `pyproject.toml` 删除 `streamlit>=1.35.0`。
- 全测 1436 passed 不变。

### 涉及文件
- 修改: `legacy/app.py`, `legacy/README.md` (若无则新建), `docs/MIGRATION_v1_to_v2.md`, `DEV.md`, `requirements.txt`, `pyproject.toml`
- 新增: `docs/legacy_retirement_plan.md`

### 风险 / 回滚
- 低风险。若 PM 反馈 Next.js 仍有硬缺陷, 退役日期顺延。

---

## T10 · docs/ 归档治理 【P2 · 文档治理】

### 背景
`docs/` 下 50+ markdown, 多数是 dated 复盘 (`*_2026_04_*`), 新人分不清 "现在生效" vs "历史决策"。 `docs/archive/` 已存在但没用起来。

### Acceptance
- 新增 `docs/README.md`, 分类索引:
  - **当前生效** (部署 / 开发 / 使用指南): 列 5-8 个核心文档
  - **本月工作** (`docs/sprints/2026-05/`): 当月 sprint / 复盘
  - **历史归档** (`docs/archive/`): 按 `YYYY-MM/` 分目录
- 迁移规则:
  - 文件名含日期戳且日期 < 当前月 → `docs/archive/YYYY-MM/`
  - 文件名不含日期但近 30 天无 commit 修改 → warn 列表, 人工 review
- 新增 `scripts/docs_archive_sweep.py --dry-run`, 自动输出迁移建议, 不自动执行。
- 新增 `docs/README.md` 后, 更新根 `README.md` 指向 `docs/README.md` 作为文档入口。

### 涉及文件
- 新增: `docs/README.md`, `scripts/docs_archive_sweep.py`, `docs/archive/2026-04/` 等归档目录
- 修改: 根 `README.md`(若存在)
- 迁移: ~30 个 dated markdown 文件 (由脚本输出清单, 人工确认后 `git mv`)

### 风险 / 回滚
- 低风险, 纯文档移动。确保不改内容、不丢文件。

---

## 跨任务通用约束 (给 Codex)

### 1. Commit message 规范
严格按仓库习惯:
```
<type>(<scope>): <subject>

<body>

Co-Authored-By: Codex <noreply@openai.com>
```
`type`: feat / fix / docs / test / chore / refactor
`scope`: api / web / birds / scripts / docs / ops / eval

### 2. 单 PR 原则
- 每个 Txx 任务 = 1 PR (T8 允许拆 2 PR)
- 单 PR diff < 800 行 (除 T8/T10 的大规模迁移, 那两个单独说明)
- 每个 PR 必须跑通 `make test` (若无 Makefile 就 `python -m pytest tests -q`)

### 3. 不能做的事
- **不要** 大范围重构 / 改变公共 API, 除非任务明确要求
- **不要** 升级依赖版本 (除非是安全补丁)
- **不要** 删除测试, 只能新增或增强
- **不要** 改 `shared-wiki/` 下的业务内容
- **不要** 把任何 PRD 正文写进代码、测试 fixture 或文档
- 默认**不要**直接 push 到 `company-gitlab/main` 或 `origin/main`, 必须走 MR / PR review; 只有用户在当前线程明确要求时, 才允许推 `company-gitlab/main`。`origin/main` 永远不直接推。

### 4. 每个 PR 必须在 description 包含
- 本次改动的**根因** (为什么做这件事)
- **验收命令** (copy-paste 可执行, 复现 Acceptance)
- **风险 / 回滚方案**
- **是否影响 `.env.example`** (若有, 明确列出新增 env vars)
- **是否需要运维配合** (T4 / T7 需要)

### 5. 卡住时
- 若任务卡住超过 2 小时, 把当前进度写进 PR description 的 "Blocked on" 段, 主动 @ 维护者。
- 不要为了推进而绕开 Acceptance, 宁可做一半 PR draft。

---

## 汇总时间线 (建议)

| 周 | 任务 | 产出 |
|----|------|------|
| W1 (本周) | T1 + T2 + T3 | 数据合规契约 + 苍鹰失败率量化 + push guard |
| W2 (扩到 5-6 人前) | T4 + T5 | TTL 清理 + PM 返工收集上线 |
| W2 末 | T6 | 规则调权 A/B 证据链 (依赖 T5 数据) |
| W3 (扩大决策前) | T7 + T9 + T10 | workspace 拆出 + legacy 退役 + docs 治理 |
| W4+ | T8 | 子包重构 (非阻塞, 可延后) |

---

## 给执行者的一句话

优先级的核心是**"数据合规守住 + 上线后真实指标可信"**, 技术债 (T7-T10) 可以慢慢做, 但 T1-T3 必须本周完成, 否则扩到 5-6 人后爆雷概率很高。每个任务的 Acceptance 就是合并门禁, 达不到不要合, 宁可拆小。
