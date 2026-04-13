---
source: PRD评审-2026-04-11
created: 2026-04-11
updated: 2026-04-11
tags: [domain/数据表, status/已验证]
---

# ds_risk_labour_arbitration（劳动仲裁主表）

## 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint(20) | 自增主键 |
| title | varchar(500) | 公告标题 |
| case_code | varchar(200) | 标准化案号 |
| applicant | text | 申请人 |
| defendant | text | 被申请人 |
| case_reason | varchar(500) | 仲裁原因 |
| open_time | **datetime** | 开庭时间 |
| publish_date | date | 公告日期 |
| type | tinyint(2) | 公告类型（1:送达, 2:开庭） |
| arbitration_org | varchar(250) | 仲裁机构 |
| data_status | tinyint(2) | 数据状态（0有效, 1历史, 2删除, 3去重） |
| riskbird_status | tinyint(2) | 风鸟屏蔽字段（0展示, 1屏蔽） |

## 关键约束

- data_status = 0 且 riskbird_status = 0 才展示
- open_time 是 **datetime** 类型（注意：ent 表同名字段是 date 类型，存在类型差异）

## 关联

- [[约束-ds_risk_labour_arbitration_ent]]
- [[概念-筛选规则]]