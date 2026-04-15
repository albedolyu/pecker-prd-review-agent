# 操作日志

<!-- 格式：## [YYYY-MM-DD] 操作类型 | 说明 -->

## [2026-04-12] review | 数据维度-对外投资增加间接投资_原始版本.md

- 评审人：许大伟
- PRD 版本：v1.2
- 知识库预检：空库，识别 6 个盲区，使用者选择跳过补充，直接进入评审
- 改进项：15 条（must×11 + should×3 + 待确定×2 [C类⚠️]）
- 确认结果：全部接受（Y）
- 新增 Wiki 页面（5个）：
  - 概念-对外投资.md
  - 约束-对外投资DDL.md
  - 场景-直接投资列表页.md
  - 场景-间接投资列表页.md
  - 决策-股权链展示上限.md
- 产出文件：
  - output/PRD_原版_20260412.md
  - output/PRD_改动报告_20260412.md
  - output/PRD_差异报告_20260412.md
  - output/PRD_交互记录_20260412.md
- 盲区标注（依据不足⚠️ 的模块）：
  - 间接投资持股合计计算规则
  - nacaoid 与行业分类的映射关系
  - 企业经营状态枚举值
  - 上市/非上市判断字段
  - 信用报告现有结构
  - 竞品企查查股权链细节

## [2026-04-12] init | 初始化知识库

- 创建 wiki/index.md 和 wiki/log.md
- 评审人：许大伟
- PRD：对外投资（数据维度-对外投资增加间接投资）

## [2026-04-12 18:47] consolidation | 鸮鹦自动整理

### 创建占位页面 (3)
- `场景-投资详情弹窗.md`
- `场景-对外投资筛选逻辑.md`
- `概念-间接投资持股计算.md`

## [2026-04-12] review | 数据维度-对外投资增加间接投资_原始版本.md（第二轮·许大伟人工评审）

- 评审人：许大伟
- PRD 版本：v1.2
- 知识库预检：
  - 强相关页面 14 个（知识库已较为完整）
  - 盲区 4 个：ES索引名称、生产IP暴露规范、信用报告现有结构、ES字段同步机制
  - 使用者选择跳过补充，直接进入评审
  - 涉及盲区的改进项已标注 `依据不足⚠️`
- 改进项：14 条（must×8 + should×4 + 待确定×2 [C类⚠️]）
- 确认结果：全部接受（Y）
- 新增/更新 Wiki 页面（2个）：
  - 决策-生产数据库地址暴露规范.md（新增）
  - 决策-直接投资持股合计字段映射.md（新增）
- 产出文件：
  - output/PRD_改动报告_20260412.md（更新）
  - output/PRD_差异报告_20260412.md（更新）
  - output/PRD_交互记录_20260412.md（更新）

## [2026-04-15] auto_fix | add_to_index=3 fix_frontmatter=19

## [2026-04-15 05:16] consolidation | 鸮鹦自动整理

### 修复 frontmatter (19)
- `决策-生产数据库地址暴露规范.md` (补充: sources)
- `决策-直接投资持股合计字段映射.md` (补充: sources)
- `决策-移动端保留认缴出资额.md` (补充: sources)
- `决策-股权链展示上限.md` (补充: sources)
- `场景-对外投资列表浏览与筛选.md` (补充: sources)
- `场景-对外投资筛选逻辑.md` (补充: sources)
- `场景-投资详情弹窗.md` (补充: sources)
- `场景-直接投资列表页.md` (补充: sources)
- `场景-间接投资列表页.md` (补充: sources)
- `概念-对外投资.md` (补充: sources)
- `概念-持股合计.md` (补充: sources)
- `概念-间接投资持股计算.md` (补充: sources)
- `竞品-企查查-对外投资.md` (补充: sources)
- `约束-ds_company_discover_invest表结构.md` (补充: sources)
- `约束-ds_invest_alpha表结构.md` (补充: sources)
- `约束-t_ds_company_basic表结构.md` (补充: sources)
- `约束-对外投资DDL.md` (补充: sources)
- `约束-对外投资数据库连接.md` (补充: sources)
- `约束-对外投资跨表关系.md` (补充: sources)

### 添加到索引 (3)
- `实体-对外投资模块的核心数据实体.md`
- `实体-对外投资的关键约束条件.md`
- `概念-对外投资PRD的重点审阅维度.md`

## [2026-04-15] rebuild_index | pages=22

## [2026-04-15] review_done | reviewer=xinshu prd=评审对外投资 PRD items=25 retracted=0

## [2026-04-15] auto_fix | add_to_index=6

## [2026-04-15 10:07] consolidation | 鸮鹦自动整理

### 添加到索引 (6)
- `决策-后端接口型 PRD 易漏接口契约定义.md`
- `决策-数据源定义易出现类型矛盾.md`
- `决策-版本号一致性检查点（结构层）.md`
- `实体-对外投资模块：多数据源架构.md`
- `概念-xinshu 评审偏好：结构严谨性优先.md`
- `约束-技术约定基础路径：_api_v1.md`

## [2026-04-15] rebuild_index | pages=28

## [2026-04-15] review_done | reviewer=default prd=对外投资基线v3 items=9 retracted=0

## [2026-04-15] auto_fix | add_to_index=7

## [2026-04-15 11:16] consolidation | 鸮鹦自动整理

### 添加到索引 (7)
- `决策-字段映射规则容易重复识别同一问题.md`
- `决策-混合数据源 PRD 的一致性漏报风险.md`
- `实体-对外投资模块的核心数据关系.md`
- `实体-混合数据源的集成路由模式.md`
- `概念-default 审阅人的 must 级关注维度.md`
- `概念-苍鹰交叉校验的关键检查点.md`
- `约束-评审规则编号体系映射.md`

## [2026-04-15] rebuild_index | pages=35

## [2026-04-15] review_done | reviewer=default prd=对外投资基线v4 items=9 retracted=0
