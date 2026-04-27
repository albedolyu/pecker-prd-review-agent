# Pecker 污染漂移审查 (2026-04-26 Day4)

> 审查范围: 5 大污染源 (docs / wiki / 规则 / tests / sessions) + 2 顺手项 (dead code / memory 引用)
> 审查方式: 只读, 每条结论给 file:line 或 grep 证据
> 审查者: 默认怀疑文档, 用代码事实对账
> 审查耗时: ~25 min

---

## TL;DR

- 严重 (P0): **5** 处
- 中等 (P1): **8** 处
- 轻微 (P2): **6** 处
- 总建议处置工量: **~6 小时** (P0 修 + P1 batch 处理 + P2 收尾)

**最严重 3 条** (TL;DR 重复, 具体见报告):
1. **RC-014 删除未级联**: review/dimensions.py 硬编码 dict + 6 个 workspace/review-rules/review-checklist.yaml 都还活着 (含已删的 RC-014)
2. **wiki authority schema 实施率 0%**: 7 workspace × 99 wiki 文件无任何 `authority:` 字段, 但 docs/wiki-frontmatter-v2.md / sprint 文档把它写成现状
3. **STATUS.md 老快照入库**: 04-22 14:17 自动生成版本仍存在仓库 (.gitignore 写了排除但已 tracked), 内容引用 490 单测/74 commits 已严重过时

---

## 1. docs/ 漂移

| 文件 | 漂移类型 | 证据 | 严重度 | 建议 |
|---|---|---|---|---|
| `docs/RULE_PERF_CLEANUP.md` | 全文档过时 | L48 `## 三、清洗脚本规格（未实施）` 但 `scripts/cleanup_rule_perf.py` 04-17 已落地 (`commit 3083646`); 文中 RC-014 表格 (L30) 引用的规则已被 commit 7bd15b7 删除; L1 数据日期 2026-04-16 距今 10 天经过 4 轮 sprint | P0 | 加快照注记 + 标 archived, 移到 `docs/archive/` |
| `docs/STABILITY_DIAGNOSIS.md` | 数据快照过时 (已加注记) | L1-13 已自标"04-16 时点诊断", 4 个 P0 已标 落地 commit, 但文档其余部分(L17-L80+)仍以"现状"语气描述 22 run consistency=17% / 18% 0-items | P1 | 已有快照注记, OK; 但建议加"勿引用本文当前数据"显著标记 |
| `docs/SPLIT_PLAN.md` | 已声明为完成快照 + 函数行号过时 | L1-9 已注 `已完成 2026-04-19`, 但 L75-79 仍写"`verify_evidence` 在 1428 行 / `_find_wiki_page` 在 1646" — 实际 `evidence_verify.py:424` / `evidence_verify.py:303` (parallel_review 已被拆) | P2 | 文档头已说是历史方案, 行号是历史快照; 不影响使用, 留作 archive |
| `docs/ACTION_PLAN.md` | P0 全完成, 未关闭 | P0-1~P0-5 都已 commit (在 doc 内已勾✅), 但 P1-1 ("rule_performance_history 污染清洗") 仍标"待做", 实际 `scripts/cleanup_rule_perf.py` 04-17 已存在 | P1 | 把 P1-1 标 ✅ done, 把已闭环条目移到 changelog 末尾 |
| `docs/RC-009_NEW_RULE_EFFECT.md` | 单点报告 OK, 但 RC-009 内容已第二次升级 | L19-29 描述的 RC-009 升级到"物理表定义一致性"是 04-23 改动, 后又有 sprint Day3 改动 (L188 yaml 注释) — 文档未跟进 Day3 的二轮升级 | P2 | 加 04-26 update 行 |
| `docs/sprint-real-prd-calibration-evidence-governance.md` | 主线 B/C 落地与文档不符 | L21 `每条规则有 status + precision_7d + reject_rate_7d + last_reviewed,每周 slim 一次` — 实际 `review-dimensions.yaml` 21 条规则只有 1 条 (EV-01) 有 `status`, 0 条有 precision_7d/reject_rate_7d/last_reviewed | P0 | 改成 "已落地 1 条 experimental, 其余 20 条待补" |
| `docs/sprint-real-prd-calibration-evidence-governance.md` | 主线 B 与 wiki 实际不符 | L92-95 描述冷启动 authority 默认映射, 但 7 workspace 的 99 wiki 没有 1 个有 `authority:` 字段 (见 §2 数据), 100% 走 fallback | P0 | 加"实施进度: 0/99, 风鸟外挂 wiki 51 文件 dry-run 完成"现状段 |
| `docs/wiki-frontmatter-v2.md` | spec 描述与实际差距大 | L19-37 schema 描述 `authority` 必填, 但 `grep ^authority: workspace-*/wiki/*.md = 0 命中`; L78-80 已部分自标"workspace-侵权软件 11 全 sources:0 → generated", 但漏标其它 6 workspace | P1 | 补"实施进度": 7 workspace authority 字段填充率 0%, 风鸟外挂 wiki 51 文件已通过 fengniao_wiki_frontmatter_batch dry-run |
| `docs/review-funnel-schema.md` | spec 与 emit 不符 (待验证) | L72-78 描述新 6 个 stage event, 但 timing_profile_2026_04_26.md L5 自承认 "tool_call_done / goshawk_advice_done 事件未启用" — 部分 funnel event 实际未 emit | P1 | 加 emit 实施清单, 标记哪些 event 已落地 / 哪些未启用 |
| `docs/HARNESS_RULES.md` | 内容良好, 但 R15 "STATUS 自动生成"与现状冲突 | L22 称"R15 STATUS 自动生成,删手写自评" — 但根目录 `STATUS.md` 实际是 04-22 14:17 老快照, 显然没自动重生 | P2 | 加注 "STATUS.md 实际靠 CI 重生; 本地 git 库残留 04-22 老版应清理" (见 §6) |
| `docs/STABILITY_REGRESSION_TESTS.md` | 未读, 抽查 OK | git log 04-23 过 | P3 | - |
| `docs/timing_profile_2026_04_26.md` | 数据正确 | 04-26 自产, 无漂移 | - | - |
| `docs/research_2026_04_26_day4.md` | 04-26 调研, 无漂移 | - | - | - |

---

## 2. workspace-*/wiki 污染

每 workspace 一行小结 (frontmatter 字段实施率):

| workspace | wiki 数 | authority | sources | verified_by | 备注 |
|---|---:|---:|---:|---:|---|
| `workspace-fengniao-mediation` | 8 | **0** | 5 | 0 | 全 generated, 5 个有 `sources: 1`, 3 个 (achievements/index/log) 无 frontmatter |
| `workspace-points-payment` | 3 | 0 | 0 | 0 | 仅 index/log/achievements, 无业务 wiki |
| `workspace-劳动仲裁` | 3 | 0 | 0 | 0 | 同上 |
| `workspace-产品召回` | 10 | **0** | 0 | 0 | 7 个业务 wiki 全无任何 v2 字段 |
| `workspace-侵权软件` | 14 | **0** | 11 | 0 | 11 个 `sources: 0` (硬性 generated), 含 4 个 `已废弃` 标记但未删 |
| `workspace-对外投资` | 49 | **0** | 46 | 0 | 最大 wiki, 全 generated |
| `workspace-纳税人资质` | 12 | **0** | 0 | 0 | 9 个业务 wiki 全无 v2 字段 |
| 合计 | 99 | **0** | 62 | **0** | spec 必填的 authority/verified_by 实施率 0% |

**高优清理建议**:

| # | 类型 | 证据 | 严重度 |
|---|---|---|---|
| 2.1 | wiki frontmatter v2 schema 落地率 0% | `grep -l "^authority:" workspace-*/wiki/*.md` 返回 0 文件 | **P0** |
| 2.2 | 已废弃 wiki 未清 | `workspace-侵权软件/wiki/场景-企业主页侵权软件模块.md` L4-5 写 `status: 已废弃 / 内容已合并至 [[场景-企业主页侵权软件]]`; 同 dir 的 `决策-侵权软件PRD评审发现.md` / `约束-ds_risk_software_infringement_data表结构.md` 同样 deprecated | P1 |
| 2.3 | 文件名重复语义 | `场景-企业主页侵权软件.md` vs `场景-企业主页侵权软件模块.md` (同 workspace, 仅"模块"后缀差) → 后者已 deprecated 但未删; 同样 `约束-ds_risk_software_infringement_data.md` vs `约束-ds_risk_software_infringement_data表结构.md` (后者 deprecated) | P1 |
| 2.4 | 全 `sources: 0` 自生成 wiki 进 wiki_index | 侵权 11 个、对外投资 46 个 sources:0 → 按 `_wiki_authority_tier` (review/evidence_verify.py:117) 全部 → `generated`, 不进强依据池. 现状 OK 但 wiki 总量 vs 真有用 wiki 数严重失配 | P1 |
| 2.5 | fengniao-mediation wiki 与 sprint 文档不一致 | sprint 主线 B 提到外挂风鸟代码库 wiki 是 canonical, 但 `workspace-fengniao-mediation/wiki/` 仍有 5 个 `sources: 1` 自生成 wiki, 没有显式标外挂引用 | P2 |
| 2.6 | wiki 量在小 workspace 偏少 | points-payment / 劳动仲裁 仅 3 个 (index/log/achievements 无业务 wiki) → 真业务 wiki = 0; 跑 review 时 wiki 池为空, A/B 类 evidence 无法验 | P1 — PM 决定 |

---

## 3. 规则系统污染

### 3.1 RC-014 删除未级联 (P0 最严重)

`commit 7bd15b7` 标题"删 RC-014" 实际只改了根 `review-dimensions.yaml`。其它地方 RC-014 都还活着:

| 位置 | RC-014 状态 | 证据 |
|---|---|---|
| `review-dimensions.yaml` | ✅ 已删 | yaml 21 条规则, 无 RC-014 |
| `review/dimensions.py` 硬编码 dict | ❌ **仍含** | L100/L108/L117 定义 RC-014 (yaml fallback 路径) |
| `workspace/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 `- id: RC-014` |
| `workspace-产品召回/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 同上 |
| `workspace-侵权软件/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 同上 |
| `workspace-劳动仲裁/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 同上 |
| `workspace-纳税人资质/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 同上 |
| `workspace-对外投资/review-rules/review-checklist.yaml` | ❌ 仍含 | L53 同上 |
| `workspace-对外投资/output/rule_performance_history.json` | ❌ 仍含 | RC-014 仍是 EMA 历史规则之一 |

**影响范围分析**:
- 顶层 yaml 加载是优先逻辑 (`review/dimensions.py:228` `load_review_dimensions`), workspace yaml 优先 → 顶层 fallback. **但 `review/dimensions.py:53` 的 `_DEFAULT_REVIEW_DIMENSIONS` 硬编码 dict 仍含 RC-014, 所有顶层 yaml 加载失败时 fallback 会触发**.
- 6 个 workspace `review-rules/review-checklist.yaml` 是**完全不同的 schema** (`rules:` 数组而非 `dimensions:` map), 用于 cuckoo_scorer / feedback / review_fixer 的 B 类依据验证 (见 cuckoo_scorer.py:159, feedback.py:1294, review_fixer.py:44). RC-014 在这套规则集仍被 evidence verify 视为合法.
- 结果: **新 worker 不会被 prompt 提到 RC-014 (顶层 yaml 已删), 但 review_fixer / cuckoo_scorer 在验证 evidence 时仍能匹配到 RC-014 字符串**, 形成"模型不再生成, 但旧 review_items.json 引用仍能通过验证"的半残状态.

**建议处置**:
- 6 个 workspace yaml `delete -id: RC-014` block (L53-L57)
- review/dimensions.py:117 删 hardcoded entry  
- review-dimensions.yaml L100/L108 检查 prompt 文本
- rule_performance_history.json 跑 `scripts/rule_perf_hygiene.py` 自动归类 zombie

### 3.2 RC-009 文案两套不一致 (P0)

- `review-dimensions.yaml`: "物理表定义一致性" (5 条子检查 a-e)
- 6 个 `workspace-*/review-rules/review-checklist.yaml`: "字段映射一致性" (老文案)

证据:
```
workspace-对外投资/review-rules/review-checklist.yaml:35-39
  - id: RC-009
    name: 字段映射一致性          # 老文案
    description: 字段映射表中字段名与物理表 DDL 一致
```

`commit 4684ade` (RC-009 升级到物理表定义) 漏改 6 workspace yamls。两套文案对 cuckoo_scorer 验证看起来都行(都是 RC-009 字符串), 但 PM 看 review_items.json 时会被两套文案分别误导。

### 3.3 review-dimensions.yaml status 字段实施率 5%

| 指标 | 现状 | spec 要求 |
|---|---|---|
| total rules | 21 | - |
| with `status` | 1 (EV-01=experimental) | 全部 (active/experimental/noisy/deprecated) |
| with `precision_7d` | 0 | 全部 |
| with `reject_rate_7d` | 0 | 全部 |
| with `last_reviewed` | 0 | 全部 |

证据: `python yaml.safe_load(open('review-dimensions.yaml'))` + 遍历, 见 §1 表中 sprint 文档漂移项.

### 3.4 rule_perf 数据 vs 当前规则集对照

`workspace-对外投资/output/rule_performance_history.json` 包含的 rule_ids:
```
['RC-015', 'V-08', 'V-09', 'V-07', 'V-10', 'RC-008', 'RC-013', 'V-05', 'V-04', 'RC-004', 'V-03', 'RC-014', 'RC-010', 'RC-009', 'V-06']
```

- 含已删的 **RC-014** (zombie 规则) 
- 缺新加的 **EV-01**, **V-02**, **V-11**, **V-12**, **RC-005**, **RC-006**, **RC-007** (cold 规则) 

建议跑 `scripts/rule_perf_hygiene.py` 标 zombie + cold; 或直接 `scripts/cleanup_rule_perf.py --workspace workspace-对外投资 --confirm`.

---

## 4. tests/ 污染

| 检查项 | 结果 | 严重度 |
|---|---|---|
| 命名重复/old/v1/deprecated 文件 | **0** 个 (全 64 个 test 文件命名规范) | OK |
| skipif/xfail markers 累积 | 仅 1 处 `tests/test_package_discovery.py: @pytest.mark.skipif(not _pip_available())` | OK |
| dead test (mock 函数已不存在) | 抽查 `_is_pecker_generated` 仍在 `review/evidence_verify.py:164` 存在, 测试有效 | OK |
| `_is_pecker_generated` legacy 函数残留 | review/evidence_verify.py 同时有 `_wiki_authority_tier` (新) + `_is_pecker_generated` (老, L164) 两套, L203/L241 两处仍调用老函数 | **P1** |

`tests/` 整体很干净。无需清理。

唯一发现 (P1, 实际是代码层): `_is_pecker_generated` 在 sprint Day3+ 引入 `_wiki_authority_tier` 之后理论上应被替换, 但 `review/evidence_verify.py:203` 和 `:241` 还在调用. 不是 dead code, 是双轨在跑 — 需 PM 决定何时收口.

---

## 5. session 输出累积

| workspace | sessions/ | .sessions/ | 旧 archive | 总大小 | 备注 |
|---|---:|---:|---:|---|---|
| `workspace-fengniao-mediation` | 0 | n/a | - | 332K | 新 workspace, output 干净 |
| `workspace-points-payment` | 1 | 1 | - | 208K | 4-26 single run |
| `workspace-劳动仲裁` | 2 | 2 | - | 344K | 含 `*_PRE_yaml_fix.*` (32K + 56K) + `.bak` 文件 — 可清 |
| `workspace-产品召回` | 0 | n/a | - | 84K | 4-12 数据 |
| `workspace-侵权软件` | 1 | 4 | - | 408K | 1 个 `.sessions/` 04-12 旧 (56K), 余下 04-24~04-26 |
| `workspace-对外投资` | 0 (`_archive/` 1) | **19** | `output_archive_20260426/` 228K | 968K | **最大累积**, .sessions 19 个 (04-17~04-26 shadow_0 ~ shadow_10 + baseline v7/v8) |
| `workspace-纳税人资质` | 0 | n/a | - | 128K | - |

**严重项**:

| # | 问题 | 证据 | 严重度 |
|---|---|---|---|
| 5.1 | `output_archive_20260426/` 进入仓库 git tracking | `git status` 第 38 行: `?? "workspace-对外投资/output_archive_20260426/"` (untracked, 但 .gitignore 第 39 行 `workspace*/output/` 应排除. 实际是 `output_archive_20260426/` 不匹配 `output/` 通配, 已逃出) | **P0** — 应加 `workspace*/output_archive_*/` 到 .gitignore |
| 5.2 | 劳动仲裁 PRE_yaml_fix backup 残留 | `workspace-劳动仲裁/output/PRD_开发任务_20260426_default_PRE_yaml_fix.md` (32K) + 同名 review_items_*.json (56K) — sprint Day3 yaml 修前快照, 已无引用价值 | P1 |
| 5.3 | 对外投资 .sessions 累积 19 个 | shadow_0~shadow_10 + 基线 v7/v8 + 命名带人名 (`许大伟_对外投资.jsonl`) — 旧 shadow run 数据可归档 | P1 |
| 5.4 | 部分 .bak 后缀残留 | `workspace-对外投资/output/rule_performance_history.json.bak_1776358443` (04-15 旧 EMA backup) | P2 |

---

## 6. 代码 dead code (sample 10)

抽查规则: 私有函数 (`_xxx`) + 顶层 .py / review/ 目录, grep 调用方为 0 (允许 reflection 假阳).

| # | file:line | 函数 | 状态 | 备注 |
|---|---|---|---|---|
| 6.1 | review/evidence_verify.py:164 | `_is_pecker_generated` | **Live, 但应被 `_wiki_authority_tier` 替代** | sprint Day3+ 引入新函数, 但 L203/L241 仍调用老的; 双轨跑 |
| 6.2 | review/dimensions.py:53 | `_DEFAULT_REVIEW_DIMENSIONS` (硬编码 dict) | Live (作为 yaml 失败 fallback) | 含已删的 RC-014, 漂移. fallback 路径 RC-014 残留 |
| 6.3 | parallel_review.py | facade | Live | 78 行 facade, 拆分后保留对外兼容 import; 不是 dead — 至少 `models.py / api/routes/review.py / tests/test_core.py` 仍 import |
| 6.4 | (root) `STATUS.md` | 老快照 04-22 | tracked but stale | .gitignore 规则:`STATUS.md` 在 `.gitignore` 中 (line 41 region) 但已 git tracked (无 git rm --cached), `git ls-files | grep STATUS` 命中 → 老版本会一直被 commit |
| 6.5 | 啄木鸟_产品介绍.md | 鸟类家族段 | Live, 已对齐当前 7 鸟 | 抽查 OK, 苍鹰 Sonnet 标注一致 |
| 6.6 | pecker-release/* | legacy mirror | 用于发布 | 64 个 git ls-files 命中, 整目录是 release snapshot, 非 dead. 但同一文件存两份 (root vs pecker-release/) 会让 grep 误命中 |
| 6.7 | scripts/cleanup_rule_perf.py | Live (04-17 落地, 7K) | 文档说"未实施" | docs/RULE_PERF_CLEANUP.md L48 漂移, 需更新 |
| 6.8 | api/api_adapter.py legacy `_empty_tool_fallback` | Live? | STABILITY_DIAGNOSIS L74-L77 说应抛 APIError, P0-2 已修 — 旧字符串可能仍残留, 未深查 | P2 |
| 6.9 | review/evidence_verify.py:241 | `if _is_pecker_generated(wiki_file)` 判断 | Live | 见 6.1, 与 `_wiki_authority_tier` 的 `generated` 等价, 双查 |
| 6.10 | docs/archive/ITERATION_REPORT_2026_04_16.md / SHADOW_*.md | 历史报告 | Live (在 archive/) | 仅 `docs/HARNESS_RULES.md` 1 处引用, 已 archive 化, OK |

---

## 7. memory 引用一致性

按 prompt 要求"代码里看到 `memory/xxx.md` 字符串引用"——

```
Grep memory/[a-z_]+\.md *.py = 0 命中
```

无代码层 memory 引用, 无需对账。 OK.

---

## 8. 处置优先级

### P0 (本周必做, ~2.5h)

| ID | 事项 | 预估工时 |
|---|---|---|
| P0-A | RC-014 6 workspace yaml 级联清理 (id+RC-014 块删除) | 30 min |
| P0-B | review/dimensions.py:108 / :117 hardcoded fallback dict 删 RC-014 | 10 min |
| P0-C | docs/sprint-real-prd-calibration-evidence-governance.md L21 / L92-95 加"实施进度: 0/N" 段, 改"已落地"声明 | 30 min |
| P0-D | docs/wiki-frontmatter-v2.md 加"实施进度 0%, fallback 行为兜底"段 | 20 min |
| P0-E | `STATUS.md` 老快照 git rm --cached 或重新 generate 一次 | 10 min |
| P0-F | .gitignore 加 `workspace*/output_archive_*/` (避免 archive 进 git) | 5 min |

### P1 (两周内, ~3h)

| ID | 事项 | 预估工时 |
|---|---|---|
| P1-A | RC-009 6 workspace yaml 文案对齐顶层 ("字段映射一致性" → "物理表定义一致性") | 30 min |
| P1-B | scripts/rule_perf_hygiene.py 跑一次, 标 zombie (RC-014) + cold (EV-01/V-02/RC-005~7) | 15 min |
| P1-C | scripts/cleanup_rule_perf.py --workspace workspace-对外投资 dry-run + confirm | 30 min |
| P1-D | docs/RULE_PERF_CLEANUP.md 加 "已实施 04-17" 注 | 10 min |
| P1-E | docs/ACTION_PLAN.md 把 P1-1 标 ✅ + 全 P0 段做 archive section | 20 min |
| P1-F | wiki frontmatter batch 脚本: 已有 `scripts/fengniao_wiki_frontmatter_batch.py`, 拓展到 7 业务 workspace 默认补 generated 等级 | 1 h |
| P1-G | workspace-侵权软件 deprecated wiki 处置 (3 文件) — 有 `已废弃` marker 但未删 | 20 min |
| P1-H | 劳动仲裁 PRE_yaml_fix backup + .bak 清理 (3 文件 ~96K) | 5 min |

### P2 (一个月内, 收尾, ~30min)

| ID | 事项 |
|---|---|
| P2-A | review/evidence_verify.py `_is_pecker_generated` 收口 (L203/L241 改调 `_wiki_authority_tier`) — 等 `_wiki_authority_tier` 稳定后 |
| P2-B | docs/SPLIT_PLAN.md 移 archive/ |
| P2-C | docs/RC-009_NEW_RULE_EFFECT.md 加 04-26 二轮升级 update 段 |
| P2-D | review_items_*.bak rule_perf .bak 老备份清理 |
| P2-E | docs/HARNESS_RULES.md R15 段加注 "STATUS.md 老快照需手动重生" |
| P2-F | parallel_review.py facade 是否仍有外部 import — 抽测正确, 留 1 个 sprint 后看是否能彻底删 |

---

## 9. 不能下结论的项 (需要 PM 决定)

| # | 项 | PM 需决定 |
|---|---|---|
| Q1 | 6 个 workspace 的 `review-rules/review-checklist.yaml` 用的是与顶层 review-dimensions.yaml **完全不同的 schema** (rules 数组 vs dimensions map)。这套是 cuckoo_scorer / feedback / review_fixer 的 B 类依据验证用的"老规则集", 文档没明确两套关系 | 是否合并成一套 schema? 或显式文档化两套并行? |
| Q2 | wiki authority schema 落地策略: 7 workspace × 99 wiki 全部默认 generated, 是否值得花时间逐个 promote? 还是只对真有人用过的 wiki 处理 | PM 决定 promote 路径 |
| Q3 | `pecker-release/` 目录是 release snapshot 但和 root 同步度未知 (e.g. parallel_review.py root 78 行 facade vs pecker-release/parallel_review.py 仍是老 1223 行版?). 不在审查范围, 但发现重复 | PM 决定 release 策略 |
| Q4 | `workspace-points-payment` / `workspace-劳动仲裁` / `workspace-纳税人资质` 业务 wiki 数 = 0 (仅 index/log/achievements), 是否这些 workspace 应被认为"未投入使用"? rule_perf 是否应该对它们 reset? | PM 判断 |
| Q5 | RC-014 删除是否应该追溯改 `workspace-对外投资/output/rule_performance_history.json` 历史? Day3 commit 注释说"老 review_items 引用 RC-014 仍能解析, 后处理不会破" — 是否真验证过? | PM 决定是否做"保留 zombie history 仅 mark, 不真删" vs "完整清洗" |

---

## 附录: 审查方式自我标注

**confidence 标注**:

- **直接可处置 (高 confidence)**: §3.1 RC-014 漂移 / §3.2 RC-009 文案不一致 / §1 RULE_PERF_CLEANUP 已实施未更新 / §5.1 output_archive_ git status 漂出 / §6.4 STATUS.md 残留. 这些都有 `grep + file:line` 双证据, 直接修不会漏。
- **需要 PM 二次确认**: §3.3 status 字段全表落地是否 sprint Day4 工期内必须做 / §2.6 业务 wiki 为 0 的小 workspace 处置 / Q1 两套 yaml schema 是否合并 / Q5 zombie history 处置策略。
- **未深查**:
  - `pecker-release/` 镜像目录与 root 同步度 (在审查范围外, 但发现可能有重复影响 grep 准确性)
  - `eval/` 目录的 ground truth 数据未抽查 (可能有 RC-014 残留, sample_claude-test 已 grep 命中)
  - api/ 目录端到端 review.py 流程未深查 funnel event emit 实际是否到 6 个新 stage event (review-funnel-schema.md 描述的)

**未撞边界**: 用时约 25 分钟, 在 30 min 边界内输出完所有发现。

---

**报告路径**: `docs/audit_drift_pollution_2026_04_26.md`
**生成日期**: 2026-04-26 Day4
**审查者**: Pecker 自审 (只读模式)

---

## 2026-04-27 update — schema_registry 修法落地

Day5 PM 选择长期修法 schema_registry 单点 SoT. 8 substep 全完成 (commit 待 squash 提交, 当前 working tree).
本审查报告里**已修复**的漂移项:

- ✅ §3.1 / §6.2 RC-014 zombie 6 workspace — step 3.6 anti-corruption layer 端到端 0 复活, e2e 测试覆盖
- ✅ §6.2 `_DEFAULT_REVIEW_DIMENSIONS` (review/dimensions.py:53) — step 3.2 已删除内部硬编码 fallback dict, dimensions.py 现仅从 SchemaRegistry 拉
- ✅ §6.2 `_DEFAULT_DIMENSION_WIKI_KEYWORDS` — step 3.2 同步删除, wiki keyword 由 registry 统一暴露
- ✅ §3.4 SUBMIT_REVIEW_ITEMS_TOOL 隐式 rule_id 无 enum 约束 — step 3.3 已加动态 enum (来源于 registry.valid_rule_ids())
- ✅ §3.1 散落 regex `(RC|V|EV|FN)-\d+` — step 3.4-3.5 evidence_verify / prompting / review_fixer / cuckoo_scorer 全部 SoT 化, 改用 `registry.rule_id_pattern()`
- ✅ §6.2 5 workspace 老 yaml schema 不兼容 (rules 数组 vs dimensions map) — step 3.6 anti-corruption layer 转译 100%, 端到端不污染主链路
- ✅ P0-B (§8 P0 列表) `review/dimensions.py:108/:117` hardcoded fallback 删 RC-014 — 上层级 step 3.2 整体废除 fallback dict 一并解决

未修但 schema_registry 已挡住的:
- §2.2 老 yaml zombie 字段 — anti-corruption layer fail-safe, 老 yaml 仍存但 production 端不见 zombie
- §3.5 prompting 错误提示文本手列 prefix — step 3.5 改为动态 `valid_prefixes()` + `sample_rule_ids(3)`

未处置 (deferred):
- Q1 6 workspace `review-checklist.yaml` 是否合并到顶层 — anti-corruption 已挡住下游污染, 合并工作 backlog
- Q5 RC-014 历史 rule_performance_history.json 是否回溯清洗 — schema_registry 已挡住新数据, 历史档案保留作 audit 凭证

详见: `docs/schema_registry_design_2026_04_27.md` 末尾"实施回顾"段 + `tests/test_schema_registry_e2e.py` (28 测试, pytest 1073 全绿).

