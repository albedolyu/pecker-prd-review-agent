---
source: PRD评审-2026-04-11
created: 2026-04-11
updated: 2026-04-11
tags: [domain/数据表, status/已验证]
---

# ds_risk_labour_arbitration_ent（劳动仲裁关联表）

## 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint(20) | 自增主键 |
| table_id | bigint(20) | 关联主表 id |
| entity_name | varchar(255) | 主体名称 |
| entity_type | tinyint(2) | 主体类型（1:人, 2:企业） |
| entity_id | bigint(20) | 主体 ID |
| standpoint | tinyint(2) | 当事人身份（1:申请人, 2:被申请人） |
| case_code | varchar(200) | 标准化案号 |
| open_time | **date** | 开庭时间 |
| publish_date | date | 公告日期 |
| type | tinyint(2) | 公告类型（1:送达, 2:开庭） |
| arbitration_org | varchar(200) | 仲裁机构 |
| data_status | tinyint(2) | 数据状态（0有效, 1历史, 2删除, 3去重） |

## 关键约束

- 与主表通过 table_id = 主表.id 关联，一对多
- open_time 是 **date** 类型（注意：主表同名字段是 datetime 类型，存在类型差异）
- 查询入口：从 ent 表入手，通过 entity_id 关联企业

## 关联

- [[约束-ds_risk_labour_arbitration]]
- [[概念-筛选规则]]