---
source: prd/侵权软件需求文档-v1.0-原始.md
created: 2026-04-12
updated: 2026-04-12
tags: [domain/数据契约, status/已验证]
---

# 约束-ds_risk_software_infringement_data

## 表基本信息

| 项目 | 内容 |
|------|------|
| 表名 | ds_risk_software_infringement_data |
| 数据库类型 | MySQL |
| 数据库地址 | 106.75.3.103:12572/ds_risk（样例，需正式化） |
| 用途 | 存储侵权软件记录主表 |

## DDL（来自 PRD 样例，需确认为正式内容）

```sql
CREATE TABLE `ds_risk_software_infringement_data` (
  `id`                       bigint(20)    NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `entid`                    bigint(20)    DEFAULT NULL COMMENT '企业id',
  `app_name`                 varchar(256)  DEFAULT NULL COMMENT '应用名称',
  `app_development_market`   varchar(256)  DEFAULT NULL COMMENT '应用来源',
  `app_version`              varchar(256)  DEFAULT NULL COMMENT '应用版本',
  `app_question`             varchar(2000) DEFAULT NULL COMMENT '所涉问题',
  `publish_date`             date          DEFAULT NULL COMMENT '发布日期',
  `data_status`              tinyint(4)    DEFAULT NULL COMMENT '数据状态 0有效',
  `riskbird_status`          tinyint(4)    DEFAULT NULL COMMENT '展示状态 0展示 1不展示',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='侵权软件数据表';
```

## 关键字段说明

| 字段名 | 类型 | 说明 | 枚举值 |
|--------|------|------|--------|
| entid | bigint | 企业ID，关联企业主表 | >0 为有效企业 |
| app_name | varchar(256) | 应用名称 | - |
| app_development_market | varchar(256) | 应用来源（市场） | - |
| app_version | varchar(256) | 应用版本号 | - |
| app_question | varchar(2000) | 所涉及的问题描述 | - |
| publish_date | date | 工信部发布日期 | - |
| data_status | tinyint | 数据有效状态 | 0=有效 |
| riskbird_status | tinyint | 风鸟平台展示状态 | 0=展示, 1=不展示 |

## 查询过滤条件

```sql
WHERE entid > 0
  AND data_status = 0
  AND riskbird_status = 0
```

## 默认排序

```sql
ORDER BY publish_date DESC
```

支持前端切换为升序（ASC）。

## 已知盲区

- ⚠️ `riskbird_status` 是否存在其他枚举值（如 2、3）未确认
- ⚠️ `entid` 关联的企业主表名称未在 PRD 中说明
- ⚠️ PG 数据库是否涉及本需求未确认（PRD 中 PG 行为 xxx 占位）

## 关联

- [[概念-侵权软件]]
- [[场景-企业主页侵权软件]]
