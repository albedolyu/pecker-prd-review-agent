# Wiki Frontmatter v2 规范

> **设计目标**: 把 wiki 从"信息集合"升级为"证据系统"
>
> 每页 wiki 明确回答 3 个问题:
> 1. 谁能对内容负责 (owner)
> 2. 可信到什么程度 (authority)
> 3. 最近一次人工核对是什么时候 (last_verified + verified_by)
>
> **铁律**: `sources: 0` 的页面和 pecker 自生成的页面**永远**不进 A 类强依据池。

**立项日期**: 2026-04-24
**承接**: commit `e3ea5c3`(`_is_pecker_generated` 二值筛) 升级为四级 tier
**Sprint 关联**: [sprint-real-prd-calibration-evidence-governance.md](sprint-real-prd-calibration-evidence-governance.md) 主线 B

---

## 一、完整 schema

```yaml
---
# === v1 已有,保留 ===
title: 侵权软件                                   # 页面名,与文件名对应
source: prd/侵权软件需求文档-v1.0-原始.md         # 来源 PRD(单数),可选
created: 2026-04-12
updated: 2026-04-24
tags: [domain/经营风险]                           # 业务分类,不再承载 authority
scope: workspace                                  # workspace | global
category: concept | constraint | scene | decision | entity | competitor

# === v2 新增 ===
authority: canonical | trusted | contextual | generated   # 必填,默认 generated
owner: albedolyu                                  # 必填,who takes responsibility
sources: 2                                        # 外部权威来源数,已存在但规则收紧
last_verified: 2026-04-24                         # 必填 (trusted/canonical 时)
verified_by: PM | 研发 | 数据                     # 可选,但 trusted/canonical 建议有
---
```

**废弃字段**: `tags` 里的 `status/已验证` 不再作 authority 信号,改由 `authority` + `last_verified` 承载。迁移期保留读取但不生效。

---

## 二、Authority 四级定义

| 等级 | 定义 | 典型来源 | A 类强依据? | Evidence verify 行为 |
|---|---|---|---|---|
| `canonical` | 业务真相的权威出处 | 官方文档 / 法规条文 / 生产库 DDL / 正式标准 | ✓ 强 | confidence × 1.0 |
| `trusted` | 可信但需结合 PRD 验证 | PM 确认的业务定义 / 研发确认的接口契约 | ✓ (弱) | confidence × 0.85 |
| `contextual` | 帮助理解业务背景 | 竞品调研 / 场景描述 / 历史决策 | ✗ (仅 B 类) | 转 B 类,不参与 A 类验证 |
| `generated` | pecker 自动生成的推测性页面 | post_review 的 C 类回写 / kakapo_dream 整理 | ✗ | 不进 wiki_index,不参与任何 A/B 类验证 |

**升级门槛** (PM 手工 promote 的条件):
- `generated` → `contextual`: PM 读过 + 确认业务正确
- `contextual` → `trusted`: 有 verified_by 且 last_verified 在 90 天内 + sources >= 1
- `trusted` → `canonical`: 有权威外部出处 (法规/官方/生产 DDL) + sources >= 2 + last_verified 在 180 天内

**降级触发** (自动化):
- 任何 tier 的 `last_verified` 超过有效期自动降级一档 (canonical > 180d → trusted, trusted > 90d → contextual)
- `sources == 0` 强制降到 `generated` (即使 authority 字段写了 canonical,evidence_verify 也拒绝)

---

## 三、冷启动默认映射 (无需逐页人工打标)

当 wiki 页面没有显式 `authority` 字段时,按现有字段推导:

| 条件 | 默认 authority |
|---|---|
| **显式** `sources: 0` | `generated` (硬性约束, 即使写了 `authority: canonical` 也降到 generated) |
| `sources` 字段缺失 / 非整数 (如 list) | 走下面默认映射 (不强制 generated, 保留老 `_is_pecker_generated` 正则 `^sources:\s*0\s*$` 行为等价) |
| `sources >= 1` 且 `verified_by` 字段空 | `contextual` |
| `sources >= 1` 且 `verified_by` 有值 且 `last_verified` 在 90 天内 | `trusted` |
| 全部其他情况 | `contextual` (安全默认) |

**`canonical` 必须显式声明**,不会从默认映射自动升级 — 避免误判生产数据源。

**现有 workspace 实测** (2026-04-24 快照):
- `workspace-侵权软件/wiki/` 11 个页面全部 `sources: 0` → 全部 `generated`
- `workspace-对外投资/wiki/` 待 migration 脚本跑一遍统计
- `workspace-sample/wiki/` 空目录,不受影响

---

## 四、验证规则 (scripts/wiki_lint.py)

**必须通过的断言** (error):

1. 每页必须有 `title` / `authority` / `owner` / `sources` 四个字段 (过渡期: 只 warn)
2. `authority: canonical` 时,`sources >= 2` 且 `last_verified` 在 180 天内
3. `authority: trusted` 时,`sources >= 1` 且 `last_verified` 在 90 天内
4. `sources: 0` + `authority: canonical/trusted` → error (矛盾)
5. `authority` 值必须是 4 级枚举之一

**建议修复** (warn):
- `authority: contextual/trusted/canonical` 但 `verified_by` 空 → 提示补人工核对签名
- `tags` 里有 `status/已验证` 但没 `authority` → 提示显式声明
- 超过 90 天未 updated 的 canonical/trusted → 提示重新 verify

---

## 五、Enforcement — evidence_verify.py 改造

**替换 `_is_pecker_generated` 为 `_wiki_authority_tier`**:

```python
# review/evidence_verify.py

_VALID_AUTHORITY = frozenset({"canonical", "trusted", "contextual", "generated"})

def _parse_wiki_frontmatter(wiki_file_path):
    """读 frontmatter,返回 dict,失败返回空 dict"""
    try:
        with open(wiki_file_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(1500)
    except OSError:
        return {}
    m = re.match(r'^\s*---\s*\n(.*?)\n---', head, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).split("\n"):
        kv = line.split(":", 1)
        if len(kv) == 2:
            fm[kv[0].strip()] = kv[1].strip()
    return fm


def _wiki_authority_tier(wiki_file_path):
    """返回 'canonical' | 'trusted' | 'contextual' | 'generated'。

    优先读显式 `authority` 字段;不存在时按冷启动默认映射推导。
    不信任声明矛盾(如 sources:0 但 authority:canonical),按现实降级。
    """
    fm = _parse_wiki_frontmatter(wiki_file_path)

    # IOError / 无 frontmatter 兜底: 保留老 `_is_pecker_generated` 返回 False 语义 —
    # 文件仍进 wiki_index (兼容), 只是不做强依据. 不用 "generated" 避免把读错的文件挡掉
    if not fm:
        return "contextual"

    explicit = fm.get("authority", "").strip()
    try:
        sources_n = int(fm.get("sources", "0"))
    except ValueError:
        sources_n = 0
    verified_by = fm.get("verified_by", "").strip()

    # 硬性约束: sources:0 强制 generated (不信任矛盾声明)
    if sources_n == 0:
        return "generated"

    # 有显式 authority 且合法 → 信任 (前提是不违反 sources 底线)
    if explicit in _VALID_AUTHORITY:
        return explicit

    # 冷启动默认映射
    if verified_by:
        return "trusted"
    return "contextual"


def _is_pecker_generated(wiki_file_path):
    """向后兼容 — 内部走 tier 判断"""
    return _wiki_authority_tier(wiki_file_path) == "generated"
```

**影响的调用点**:
- `_is_wiki_sparse` (L61-90): 改过滤 `tier == "generated"` 的同时也可以过滤 `contextual`? **不要**。保持行为: 仅过滤 generated,让 contextual 仍然参与 sparse 判定 (有上下文总比没有好)。
- `_build_wiki_index` (L93-108): 仅剔除 generated,contextual/trusted/canonical 都进 index
- `_find_wiki_page` (L111-142): 返回页面 basename 时附带 tier,让上游判断
- 新增的 A 类 evidence verify 入口(cuckoo/苍鹰): 按 tier 分支:
  - canonical → 原逻辑
  - trusted → `confidence *= 0.85`
  - contextual → 降成 B 类 evidence,不再要求 wiki 引用
  - generated → 不参与验证 (上游已过滤)

---

## 六、Migration 策略

**Phase 0 — 本 commit (spec only)**:
- 写入本 spec + sprint 文档
- 不改代码,不改 wiki 文件
- 通知 team schema 定稿

**Phase 1 — 落地 lint + evidence_verify (第一周)**:
1. `scripts/wiki_lint.py` 新增 (只 warn,不 error,不阻塞)
2. `review/evidence_verify.py` 加 `_wiki_authority_tier`,逐步替换 `_is_pecker_generated` 调用点
3. 单测补一套: 4 个 tier × 5 个冷启动条件 = 覆盖 default mapping
4. **此时不改任何 wiki 文件** — 现有 `sources: 0` 文件自动算 generated,行为等价于今天

**Phase 2 — 批量迁移 (第一周末)**:
1. `scripts/wiki_migrate_v2.py` — 对每个 workspace 的 wiki/*.md:
   - 读现有 frontmatter
   - 按默认映射算 authority
   - 加 authority / owner=albedolyu / last_verified=今天
   - 不改正文
2. Dry-run 先跑一遍,输出 authority 分布统计
3. 确认分布合理后 `--apply` 写回文件
4. 提 commit: "chore(wiki): frontmatter v2 backfill (authority 冷启动默认映射)"

**Phase 3 — PM 人工 promote (第二周 onwards)**:
- PM 识别 3-5 个业务核心概念,手工升 canonical/trusted
- owner 改真实人,verified_by 签字,sources 补到 >= 2
- Wiki 页面内容纠错(如侵权软件 wiki 里 `{侵权软件}` / `【侵权软件】` 语义搞反那种)

**Phase 4 — 生命周期自动化 (第三周)**:
- `scripts/wiki_lifecycle.py` 定时跑 (cron / 手动),检查 `last_verified` 过期,自动降级
- 产 `docs/wiki-lifecycle-YYYY-WW.md` 周报

---

## 七、示例

### 例 1: canonical (生产 DDL 出处)
```yaml
---
title: ds_risk_software_infringement_data 表结构
source: prd/侵权软件需求文档-v1.0-原始.md
tags: [domain/数据契约]
sources: 3                          # DDL文件 + PRD原文 + 研发确认邮件
category: constraint
authority: canonical
owner: albedolyu
last_verified: 2026-04-24
verified_by: 数据
---

## 表基本信息
(DDL 正文,与生产库 `mysql://106.75.3.103:12572/ds_risk` schema 一致)
```

### 例 2: trusted (PM 确认的业务定义)
```yaml
---
title: riskbird_status 枚举
source: prd/侵权软件需求文档-v1.0-原始.md
tags: [domain/经营风险]
sources: 1                          # 仅有 PRD 出处
category: concept
authority: trusted
owner: albedolyu
last_verified: 2026-04-20
verified_by: PM
---
```

### 例 3: contextual (业务背景)
```yaml
---
title: 竞品-企查查-侵权软件
source: prd/侵权软件需求文档-v1.0-原始.md
tags: [domain/竞品]
sources: 1
category: competitor
authority: contextual
owner: albedolyu
last_verified: 2026-04-12
---
```

### 例 4: generated (pecker 自动回写)
```yaml
---
title: 场景-风险扫描侵权软件
source: prd/侵权软件需求文档-v1.0-原始.md
tags: [domain/经营风险]
sources: 0                          # 0 表示纯 pecker 推测,无外部来源
category: scene
authority: generated
owner: pecker-auto
created: 2026-04-12
---
```

---

## 八、API / 向后兼容

- `_is_pecker_generated()` 保留为便捷函数,内部走 `_wiki_authority_tier() == "generated"` — 现有 3 个调用点 (`evidence_verify.py:88, 104` 以及 tests) 不用改
- 所有 v1 frontmatter 字段保留读取,无字段清理
- 新字段缺失时 `_parse_wiki_frontmatter` 返回空,`_wiki_authority_tier` 走默认映射
- `wiki_consolidation.py` / `wiki_lock.py` / `wiki_log.py` 不受影响 (它们不读 authority)

---

## 九、Open questions (待定)

1. **canonical 的 sources 门槛**: 当前定 >=2。如果某 wiki 本质上只有一个权威出处 (如"工信部官方通报 URL"),强行要 sources=2 会误挡。→ 暂按 >=2 走,发现具体反例再改成 >=1 + `authority_override` 标注
2. **owner 能是 shared tag 吗?** 如 `owner: [albedolyu, researcher]`。暂定不允许 — 一条 wiki 只能一个 owner (负责人),co-authors 写正文不写 frontmatter
3. **generated 永久封存还是可升?** 定"PM 改过正文 + 显式改 authority"就升。migration 脚本不自动升,防止误判

---

## 十、首批落地 checklist

- [ ] spec 本身 commit (本 PR)
- [ ] `scripts/wiki_lint.py` warn 模式上线
- [ ] `review/evidence_verify.py` 加 `_wiki_authority_tier` + 单测
- [ ] `scripts/wiki_migrate_v2.py` dry-run 跑一次,贴分布统计
- [ ] 确认分布合理后 `--apply`
- [ ] evidence_verify 行为回归测: 跑一次 pecker on `workspace-侵权软件/未准入境需求文档`,确认 items 输出不劣化 (不低于 P0-1 的 10 条)
- [ ] PM 选 2-3 个业务核心 wiki 手工 promote 到 trusted/canonical,commit 示例

---

**一句话**: v1 的 `sources: 0` 是"刹车",v2 的四级 authority 是"仪表盘 + 刹车 + 油门"。
