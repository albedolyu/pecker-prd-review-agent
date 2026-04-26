# 风鸟领域规则草案 (10 条) — 2026-04-27

> **状态更新 2026-04-27**: FN-01 / FN-03 / FN-09 已升 **experimental** 进 review-dimensions.yaml (commit feat(rules) 升 active 第一波). 其他 7 条仍为草稿.
>
> 状态: **草稿**, 不进 review-dimensions.yaml. 等 PM 审 → 升 active 再合并.
> 起源: Pecker 当前 21 条规则全是通用 PRD 评审, 0 条风鸟领域规则. 今天 implement 3 工况实验印证通用 V-02/D-01 (跨表字段类型一致性) 拉开 lineage_quality +2. 加深风鸟领域规则后预期 +5+.
> 沉淀来源: workspace-劳动仲裁/wiki + workspace-纳税人资质/wiki + workspace-fengniao-mediation/wiki + workspace-侵权软件/wiki + 风鸟代码库 wiki + workspace-劳动仲裁/output/review_items_20260427_default.json + CLAUDE.md.

---

## 总览

| rule_id | name | dimension | severity | trigger_when | 来源 |
|---|---|---|---|---|---|
| **FN-01** | ds_risk_* 三段过滤约定 | data_quality | must | PRD 引用 `ds_risk_*` 表 | workspace-侵权软件/wiki/约束-ds_risk_software_infringement_data.md (`WHERE entid > 0 AND data_status = 0 AND riskbird_status = 0`) |
| **FN-02** | 主表 / ent 表跨表字段精度对齐 | data_quality | must | PRD 同时引用 `ds_risk_*` 主表和 `ds_risk_*_ent` 表 | workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration{,_ent}.md + review_items_20260427/R-016 |
| **FN-03** | 风鸟鉴权与基础路径硬约定 | ai_coding | must | PRD 含「技术约定」「鉴权」「API 接口」章节 | 风鸟 wiki/concepts/JWT认证流程.md + architecture/后端架构.md + review_items_20260427/R-008 |
| **FN-04** | 风鸟错误码 401/405/503/8888/9999 四态映射 | ai_coding | must | PRD 含外部数据 / 接口调用 / 列表加载 | 风鸟 wiki/api/移动端API.md (错误码表) + workspace-劳动仲裁/wiki/决策-UI四态规范.md |
| **FN-05** | 行政区划三级码与字典源 | data_quality | must | PRD 含「按地区筛选」「area_code」「省/市/区」 | 风鸟 wiki/api/移动端API.md (level1/2/3AreaCode) + review_items_20260427/R-012 |
| **FN-06** | 自然人脱敏算法可执行 | ai_coding | must | PRD 含「脱敏」「姓+\*\*」「自然人」 | workspace-劳动仲裁/wiki/概念-脱敏规则.md + 决策-公告内容脱敏方式.md + review_items_20260427/R-004,R-007,R-011 |
| **FN-07** | 跨表实体跳转必给 URL 模板 | ai_coding | must | PRD 含「点击跳转企业主页」「entity_id」「关联企业」 | workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration_ent.md + review_items_20260427/R-010 |
| **FN-08** | 新增分类字段必给存量回填策略 | data_quality | must | PRD 提到向已有 `ds_risk_*` 表新增字段 | workspace-fengniao-mediation/wiki/概念-新增数据分类字段必须说明存量回填策略.md |
| **FN-09** | 移动端 (uni-app) 与 Web 端必显式对齐 | structure | must | PRD 同时含「移动端」+ Web 端页面 | 风鸟 wiki/architecture/前端架构.md + concepts/混合架构.md + workspace-fengniao-mediation/wiki/概念-隐式 UI 引用导致验收标准空白.md + review_items_20260427/R-018 |
| **FN-10** | 数据导出 SLA 三件套 | quality | must | PRD 含「导出」「Excel」「下载」 | workspace-纳税人资质/wiki/概念-数据导出规范.md + review_items_20260427/R-014 |

---

## FN-01 ds_risk_* 三段过滤约定 ✅ 已升 active (experimental, 2026-04-27)

**dimension**: data_quality
**severity**: must
**status**: experimental (在 review-dimensions.yaml 中)
**trigger_when**: PRD 引用任一 `ds_risk_*` 物理表 (即关键字 `ds_risk_` 出现且后接表名).
**description**: 风鸟所有 `ds_risk_*` 表对外查询必须三段过滤 `entid > 0 AND data_status = 0 AND riskbird_status = 0`, PRD 必须显式写出该 WHERE 条件或显式声明跳过原因.

**checklist** (5/5):
- a) PRD 中查询 SQL / 伪代码包含 `entid > 0` (或等价的 entid 非空过滤)
- b) PRD 中查询 SQL / 伪代码包含 `data_status = 0` (或显式声明本场景不需要 data_status 过滤并给出原因)
- c) PRD 中查询 SQL / 伪代码包含 `riskbird_status = 0` (或显式声明本场景不需要 riskbird_status 过滤并给出原因)
- d) `data_status` 和 `riskbird_status` 都给出完整枚举值表 (如 0/1/2/3 各代表什么)
- e) 默认排序字段在 DDL 里有索引 (PRD 文本提到该字段索引存在或 wiki 引用确认)

**sources**:
- workspace-侵权软件/wiki/约束-ds_risk_software_infringement_data.md L57-62 (查询过滤条件)
- workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration.md L33-36 (data_status/riskbird_status 取值)
- workspace-侵权软件/wiki/概念-riskbird_status枚举.md (枚举定义)

---

## FN-02 主表 / ent 表跨表字段精度对齐

**dimension**: data_quality
**severity**: must
**status**: experimental
**trigger_when**: PRD 同时引用主表 `ds_risk_<topic>` 和关联表 `ds_risk_<topic>_ent`.
**description**: 风鸟主表与 \_ent 表常含同名字段 (如 `open_time`, `publish_date`, `arbitration_org`), 类型/长度可能不同 (如主表 datetime / ent 表 date). PRD 必须显式说明取数与展示来源, 避免精度丢失或排序歧义.

**checklist** (5/5):
- a) PRD 列出主表与 ent 表所有同名字段 (字段名一致但归属不同表的清单)
- b) 每对同名字段, PRD 标注两表中的具体类型 (如 `datetime` vs `date`)
- c) 每对同名字段, PRD 显式指定查询/展示时的优先取数源 (如「展示取主表, 排序取主表」或者「优先 ent 表, 空值降级主表」)
- d) JOIN 键明示 (如 `ent.table_id = 主表.id`) 而非笼统说"通过 entid 关联"
- e) 类型不一致字段, PRD 给出修复方案二选一: (i) 统一类型修 DDL, (ii) 业务规则显式声明仅一侧用于排序/展示

**sources**:
- workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration.md L24-36 (主表 datetime)
- workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration_ent.md L26-37 (ent 表 date)
- workspace-劳动仲裁/wiki/决策-字段来源优先级.md (优先 ent 表降级主表)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-016 (open_time 精度差异 must)

---

## FN-03 风鸟鉴权与基础路径硬约定 ✅ 已升 active (experimental, 2026-04-27)

**dimension**: ai_coding
**severity**: must
**status**: experimental (在 review-dimensions.yaml 中)
**trigger_when**: PRD 含「技术约定」「鉴权」「Authorization」「API 接口」「base path」任一关键词章节.
**description**: 风鸟后端硬约定 Apache Shiro + JWT (Bearer Token) 鉴权, 移动端基础路径以模块前缀 (如 `/login/*`, `/query/*`, `/user/*`). PRD 不应再写 TBD/待技术确认, AI Coding 凭此一次性产出客户端调用与服务端路由.

**checklist** (5/5):
- a) PRD 鉴权方式明确写为「Authorization: Bearer {token}」或显式引用 wiki 页 `[[concepts/JWT认证流程]]`
- b) PRD 鉴权章节不含「TBD」「待技术确认」「待补充」字样
- c) PRD 列出每个接口的认证要求 (是 / 否 / 可选), 并与移动端硬约定一致 (`/login/*`, `/pay/wxNotify` 不需鉴权; 详情/查询类必须鉴权)
- d) PRD 接口路径以模块前缀开头 (如 `/api/v1/<module>/*` 或与 wiki 既有模块前缀一致), 不出现 `/xxx/*` 占位符
- e) 401/Token 过期处理方案与风鸟规范一致 (跳转登录 + Refresh Token 续期, 不另起方案)

**sources**:
- 风鸟 wiki/concepts/JWT认证流程.md (双 Token 机制 + 401 流程)
- 风鸟 wiki/architecture/后端架构.md L80-103 (Shiro + @RequiresPermissions)
- 风鸟 wiki/api/移动端API.md (每接口认证列)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-008 (鉴权 TBD must)

---

## FN-04 风鸟错误码 401/405/503/8888/9999 四态映射

**dimension**: ai_coding
**severity**: must
**status**: experimental
**trigger_when**: PRD 含外部数据 / 接口调用 / 列表加载 / 详情拉取等远程数据场景.
**description**: 风鸟前端有平台级错误码硬约定: 401(未登录跳转) / 405(系统限制) / 503(稍后重试) / 8888(业务错误) / 9999(系统错误). PRD 列出的「四态 UI」(加载中 / 失败 / 空筛选 / 空数据) 必须分别映射到这些错误码上, 不能仅写「请求失败」这种笼统状态.

**checklist** (5/5):
- a) PRD 列出加载中状态触发条件 (接口请求中) 与样式 (骨架屏 / spinner)
- b) PRD 列出请求失败状态对四个错误码 (401/405/503/8888 或 9999) 至少 3 个有具体处理 (跳登录 / 提示文案 / 重试按钮)
- c) PRD 区分「筛选无结果」与「企业无数据」两种空态, 文案不同
- d) 401 处理方案与风鸟既有约定一致 (跳转登录, 不弹自定义弹窗)
- e) 重试按钮在 5xx / 8888 / 9999 时启用, 在 401 / 405 时不启用 (PRD 文本可推断)

**sources**:
- 风鸟 wiki/api/移动端API.md L153-160 (错误码表 401/405/503/8888/9999)
- 风鸟 wiki/architecture/前端架构.md L108-113 (request.js 状态码拦截)
- workspace-劳动仲裁/wiki/决策-UI四态规范.md L13-24 (四态触发条件 + 展示规范)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-013 (统一响应包络 + 错误码枚举)

---

## FN-05 行政区划三级码与字典源

**dimension**: data_quality
**severity**: must
**status**: experimental
**trigger_when**: PRD 含「按地区筛选」「area_code」「省 / 市 / 区」「行政区划」任一表述.
**description**: 风鸟移动端硬约定三级地区码字段名 `level1AreaCode`(省) / `level2AreaCode`(市) / `level3AreaCode`(区), 区码优先级最高. PRD 写「按地区筛选」必须落到三级码 + 显式指明字典源 (国标 GB/T 2260 版本号 + 维护责任方), 不接受仅文字描述.

**checklist** (5/5):
- a) PRD 中地区筛选请求参数命名为 `level1AreaCode` / `level2AreaCode` / `level3AreaCode` 三件套 (或显式说明本场景仅用其中之一)
- b) PRD 标注 `area_code` 字典源为 GB/T 2260 + 具体版本号 (如 2007 / 2020 版)
- c) PRD 标注字典维护责任方 (谁更新 / 何时更新 / 失效如何处理)
- d) 移动端筛选按 `area_code` 升序排序的规则被显式写出 (省级三级 / 直辖市两级)
- e) 空值或字典外的 `area_code` 处理规则被显式写出 (归类「其他」/ 兜底处理)

**sources**:
- 风鸟 wiki/api/移动端API.md L60 (level1/2/3AreaCode 三级码 + region 由后端解析)
- workspace-劳动仲裁/wiki/概念-筛选规则.md L19-35 (送达公告省级三级 / 直辖市两级 / 空值归"其他")
- workspace-劳动仲裁/output/review_items_20260427_default.json R-012 (area_code 字典源 must)

---

## FN-06 自然人脱敏算法可执行

**dimension**: ai_coding
**severity**: must
**status**: experimental
**trigger_when**: PRD 含「脱敏」「姓+\*\*」「自然人」「打码」「隐私」任一表述.
**description**: 风鸟脱敏硬约定 (姓+\*\*, 复姓保留两字, 仲裁员/书记员不脱敏). PRD 不能仅给规则示例, 必须给出可执行算法 (复姓字典或长度规则) 让 AI Coding 生成稳定代码.

**checklist** (5/5):
- a) PRD 给出脱敏星号数量是「固定两星」还是「按名字字数」, 二选一明确, 不留歧义
- b) PRD 给出复姓识别方式: 提供复姓字典 (清单 ≥ 4 个常见复姓如欧阳/上官/司马/诸葛), 或给出明确算法 (如 `name[:2] in 复姓字典 ? name[:2] : name[:1]`)
- c) PRD 显式列出「不脱敏」白名单 (仲裁员 / 书记员 / 企业名 等公开角色)
- d) 公告内容 (非结构化文本) 中的人名识别方式被明示 (字符串精确匹配 / NER / 字典命中替换 等)
- e) 规则与示例完全自洽 (`张三` → `张**` 与 `欧阳修` → `欧阳**` 星号数量一致或规则明确说明差异)

**sources**:
- workspace-劳动仲裁/wiki/概念-脱敏规则.md L19-29 (脱敏规则表)
- workspace-劳动仲裁/wiki/决策-公告内容脱敏方式.md L17-25 (字符串精确匹配 ent 表)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-004 / R-007 / R-011 (脱敏歧义反复出现 must)

---

## FN-07 跨表实体跳转必给 URL 模板

**dimension**: ai_coding
**severity**: must
**status**: experimental
**trigger_when**: PRD 含「点击跳转企业主页」「entity_id」「entity_type=2」「关联企业」「关联人」任一表述.
**description**: 风鸟主表 + ent 表 (`entity_type` 1=人, 2=企业) 关联跳转是高频场景. PRD 写「点击跳转」必须给出 URL 模板 + entity_id 缺失兜底, 不接受「跳转对应数据表格」这种笼统说法.

**checklist** (5/5):
- a) PRD 列出每个跳转点的目标 URL 模板 (如 `/company/{entid}` 或 `/person/{personId}`)
- b) URL 模板的占位符与 ent 表字段名对齐 (如 `{entid}` 对应 `ent.entity_id` 且 `entity_type=2`)
- c) PRD 写出 entity_id 为空 / `entity_type` 不在 {1,2} 时的兜底处理 (纯文本 / 不可点击 / 跳搜索页)
- d) PRD 区分「搜索结果页标签」与「企业主页标签」交互 (是否可点击) 不同时, 显式声明差异
- e) 跨企业跳转的鉴权要求 (跳转后是否需要登录) 被明示

**sources**:
- workspace-劳动仲裁/wiki/约束-ds_risk_labour_arbitration_ent.md L17-37 (entity_type/entity_id/standpoint 三件套)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-010 (公告内容企业名跳转 URL 模板缺失 must)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-002 (FR-17 跳转交互对两个入口描述矛盾 must)

---

## FN-08 新增分类字段必给存量回填策略

**dimension**: data_quality
**severity**: must
**status**: experimental
**trigger_when**: PRD 提到向已有 `ds_risk_*` 表新增字段 (如「新增 `is_mediation`」「新增 `is_pre_mediation`」「新增 `riskbird_status`」).
**description**: 风鸟历史数据是常态 (司法立案 / 仲裁公告 / 软件侵权), 新增分类标记字段必给存量数据默认值 + 前端过滤逻辑 + 数据迁移 SLA, 否则 NULL 历史记录会被误过滤丢失.

**checklist** (5/5):
- a) PRD 显式声明新字段对存量数据的默认值 (NULL / 0 / 1, 任选其一)
- b) PRD 显式声明前端过滤逻辑如何处理 NULL (`IS NULL` 视为 0 / 视为 1 / 排除)
- c) PRD 给出存量数据回填 SLA (回填启动日 + 完成日 + 期间过渡方案)
- d) PRD 标注新字段是否需要同步到 ES mapping (如有 ES 检索需求)
- e) PRD 标注新字段在主表与 ent 表的双侧添加策略 (是否需要同步 ent 表)

**sources**:
- workspace-fengniao-mediation/wiki/概念-新增数据分类字段必须说明存量回填策略.md (诉前调解 is_mediation 真实场景)
- workspace-fengniao-mediation/wiki/概念-诉前调解：通过字段标记而非独立表的低成本方案.md (复用现有表 + 标记字段模式)

---

## FN-09 移动端 (uni-app) 与 Web 端必显式对齐 ✅ 已升 active (experimental, 2026-04-27)

**dimension**: structure
**severity**: must
**status**: experimental (在 review-dimensions.yaml 中)
**trigger_when**: PRD 同时含「移动端」「H5」「uni-app」「小程序」 + Web 端页面定义.
**description**: 风鸟前端 uni-app 跨平台 + Native/WebView 混合架构. PRD 移动端章节不能仅写「复用 Web 端」「与 Web 端保持一致」, 必须显式列出移动端筛选 / 搜索 / 字段差异, 且明确该页面走原生还是 WebView 容器.

**checklist** (5/5):
- a) PRD 移动端章节不出现「复用 Web 端」「与 X 保持一致」「全都和立案信息 UI 保持一致」未点明对象的隐式引用 (引用必须有具体章节号)
- b) PRD 显式标注每个移动端页面是「原生」还是「WebView」(走 `pages/tools/webview` 容器还是原生白名单)
- c) 移动端筛选维度与 Web 端筛选维度的差异在 PRD 中被列举 (如 Web 用案由 / 仲裁机构, 移动用省份 / 年份 / 公告类型) 而非笼统「移动端简化」
- d) 移动端不提供搜索框时, PRD 显式说明用什么交互替代 (筛选组合 / 历史关键词 / 不需要)
- e) 移动端字段映射的数据源 (`area_code` 映射省份, `publish_date` 提取年份等) 在 PRD 中显式给出

**sources**:
- 风鸟 wiki/architecture/前端架构.md (uni-app + 分包 packageQuery/packageUser/packageA)
- 风鸟 wiki/concepts/混合架构.md (Native + WebView 路由白名单)
- workspace-fengniao-mediation/wiki/概念-隐式 UI 引用导致验收标准空白.md (诉前调解隐式引用问题)
- workspace-劳动仲裁/wiki/决策-移动端筛选差异化.md L17-29 (省份/年份/公告类型差异化)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-018 (移动端 2.3.3 占位说明 should)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-003 (移动端筛选项无业务规则支撑 must)

---

## FN-10 数据导出 SLA 三件套

**dimension**: quality
**severity**: must
**status**: experimental
**trigger_when**: PRD 含「导出」「Excel」「CSV」「下载报告」任一表述.
**description**: 风鸟导出场景 (劳动仲裁 / 纳税人资质 / 找客户) 都缺导出三件套 (上限 / 格式 / 权限). PRD 必须给出三件套 + 异步任务 task_id 兜底, 否则后端无法实现接口契约.

**checklist** (5/5):
- a) PRD 给出导出条数上限 (具体数值, 如 10000 条) 或显式说明无上限
- b) PRD 给出导出文件格式 (Excel `.xlsx` / CSV / JSON 等) 而非仅写「下载报告」
- c) PRD 给出导出权限要求 (登录 / VIP / 角色), 写明无权限时的提示
- d) 导出超过上限时的兜底方案被写出 (截断 + 提示 / 异步任务 task_id / 分批拉取)
- e) 导出接口的命名 (如 `POST /<module>/export`) 与既有路径前缀模式一致, 路径不出现占位符

**sources**:
- workspace-纳税人资质/wiki/概念-数据导出规范.md L11-23 (导出上限/格式/权限均 TBD)
- workspace-劳动仲裁/output/review_items_20260427_default.json R-014 (FR-18 导出 10000 条但 §2.5 无导出接口 must)

---

## 草稿评估 (PM 审参考)

### 预期触发频率 + reject_rate (10 条排名)

| rule_id | 预期触发频率 | 预期 reject_rate | 跟现有规则 overlap | 给 implement agent 的 actionability |
|---|---|---|---|---|
| **FN-01** | 高 (~80% 风鸟 PRD 涉及 ds_risk_*) | 中-高 (~60%) | RC-009 已查物理表定义但不查 WHERE 条件; **互补**, 不重复 | 高 — implement 直接照 WHERE 条件生成 SQL |
| **FN-02** | 中 (~50%, 主表+ent 表场景) | 高 (~75%, R-016 实测命中) | V-02 / RC-009 部分覆盖跨表; **FN-02 更具体到 \_ent 命名 + 类型对**, 不重复 | 高 — implement 知道取数源 |
| **FN-03** | 高 (~90%) | 高 (~75%, R-008 实测) | RC-004 (技术约定节存在) 仅查"有没有", 不查值是否硬约定; **互补** | 极高 — 一次到位 |
| **FN-04** | 高 (~85%) | 中 (~50%) | RC-005 (四态 UI) 仅查文案/样式, 不查错误码; V-12 异常处理仅笼统; **FN-04 把错误码硬约定打进四态**, 不重复 | 极高 |
| **FN-05** | 中-高 (~60%) | 高 (~70%, R-012 实测) | 无重叠 — 通用规则无地区码概念 | 高 — 知道用 level1/2/3AreaCode |
| **FN-06** | 中 (~40%, 仅含人名场景) | 极高 (~85%, R-004/R-007/R-011 同主题反复) | 无重叠 | 高 — 复姓字典是关键 |
| **FN-07** | 中-高 (~60%) | 高 (~70%, R-010 实测) | RC-013 (伪代码字段可追溯) 不覆盖 URL 模板; **互补** | 极高 |
| **FN-08** | 中 (~40%, 仅向已有表新增字段) | 高 (~70%) | 无重叠 — 这是风鸟独有数据治理约束 | 高 |
| **FN-09** | 高 (~85%, 风鸟全部 PRD 都跨端) | 中-高 (~65%, R-018/R-003 实测) | V-05 / V-07 (一致性 / 矛盾) 部分覆盖, **但 FN-09 把"端差异显式"作为正向要求**, 不是矛盾检测; **互补** | 高 — 走原生还是 WebView 直接落代码 |
| **FN-10** | 中 (~45%, 含导出场景) | 高 (~75%, 三 workspace 反复 TBD) | RC-010 (数值类字段标注来源) 部分查上限, 但不查格式/权限; **FN-10 更完整** | 高 |

### 3 条最高 ROI (按 reject_rate × 命中频率)

1. **FN-03 风鸟鉴权与基础路径硬约定** (高 × 高): 风鸟 90% PRD 都涉及接口, R-008 已实测 must 反复. ROI 第一.
2. **FN-09 移动端与 Web 端必显式对齐** (高 × 中-高): 风鸟全部 PRD 都跨端, "复用 Web 端"是顽固痼疾. uni-app 混合架构必检.
3. **FN-01 ds_risk_\* 三段过滤约定** (高 × 中-高): 风鸟 80% PRD 涉及 ds_risk_\*, 三段过滤是平台级硬约定, AI Coding 不知就生成错的 SQL.

### 跟现有 21 条规则的 overlap 分析

- **无完全重叠** — 10 条规则全是「风鸟领域专属」, 通用 V-/RC-/EV- 不能替代
- **有部分协同** (互补不重复):
  - FN-01 与 RC-009 (物理表定义一致性) 协同 — RC-009 查 DDL 完整, FN-01 查 WHERE 条件硬约定
  - FN-02 与 V-02 / D-01 (跨表字段类型一致性) 协同 — V-02 通用版, FN-02 风鸟主表 + \_ent 命名约定特化
  - FN-03 与 RC-004 (技术约定节存在) 协同 — RC-004 查"有没有", FN-03 查"值是不是 Bearer JWT"
  - FN-04 与 RC-005 (四态 UI) + V-12 (异常处理) 协同 — 通用规则查四态存在, FN-04 把错误码具体值钉死
  - FN-09 与 V-07 (逻辑一致性) 协同 — V-07 检测矛盾, FN-09 检测「显式对齐」缺失 (反方向)
- **建议**: 升 active 时 PM 在每条 FN- 规则的 prompt 里加一句"请先看通用 V-/RC- 是否已捕获, 仅当未捕获时报 FN-XX", 防止双倍 fail

### Actionability for Implement Agent

10 条全部是「让 implement 一次到位」类型, 而非「只 PM 看」:
- FN-01 / FN-02 / FN-05 / FN-08: SQL 直接照写
- FN-03 / FN-04 / FN-07 / FN-10: API 路径 + 错误码 + URL 模板直接照写
- FN-06: 脱敏函数直接照写
- FN-09: 路由白名单直接照写

### 上线节奏建议

- **第一波 (本周)**: FN-01 / FN-03 / FN-09 (高频高 ROI) 升 experimental, 跑 3 个 workspace 验证
- **第二波 (下周)**: FN-02 / FN-04 / FN-05 / FN-07 升 experimental
- **第三波 (PM 审过 + 真实采纳数据后)**: FN-06 / FN-08 / FN-10 升 experimental
- 每条 status=experimental 跑满 2 周看 reject_by_reason / 采纳率, 再决定升 active 或退 inactive

---

> 草稿完, 等 PM 审. 审完升 active 流程: 把规则文本 (description + checklist) 复制进 review-dimensions.yaml 对应 dimension 的 `rules:` 块, 再加 checklist 项 (rule_id / name / enabled: true / owner / status: experimental).
