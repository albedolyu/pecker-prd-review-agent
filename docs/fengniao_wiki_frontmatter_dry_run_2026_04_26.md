# 风鸟 wiki frontmatter 批量补全 — Dry Run 报告

**生成时间**: 2026-04-26
**wiki-root**: `C:/Users/20834/Desktop/代码项目/风鸟代码库/wiki`
**扫描文件总数**: 51

## 分类汇总

| 类别 | 文件数 | 含义 |
|------|--------|------|
| full_add_4 | 6 | 4 个字段全部要补 (frontmatter 无 verified_by/sources/last_verified/authority 任一) |
| partial | 45 | 部分字段已有, 只补缺失的 |
| no_op | 0 | 4 字段全已有, 不动 (idempotent) |
| error | 0 | YAML 解析或读取失败, 跳过 |

## 逐文件预览

| file | added_fields | sources_count | frontmatter_existed | error |
|------|--------------|---------------|---------------------|-------|
| `api/API总览.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 10 | yes | - |
| `api/移动端API.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 8 | yes | - |
| `api/管理端API.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `architecture/CDN静态资源工作台.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `architecture/前端架构.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 15 | yes | - |
| `architecture/后端架构.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 20 | yes | - |
| `architecture/系统架构总览.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 2 | yes | - |
| `concepts/JWT认证流程.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `concepts/WebView桥接.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `concepts/混合架构.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `decisions/_template.md` | verified_by=源码同步, sources=1, last_verified=2026-04-26, authority=canonical | 1 | yes | - |
| `entities/前端组件.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 8 | yes | - |
| `entities/技术栈.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `entities/数据库模型.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 12 | yes | - |
| `index.md` | verified_by=源码同步, sources=1, last_verified=2026-04-26, authority=canonical | 1 | no | - |
| `log.md` | verified_by=源码同步, sources=10, last_verified=2026-04-26, authority=canonical | 10 | no | - |
| `modules/AI机器人.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/CDN资产目录.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 2 | yes | - |
| `modules/CMS内容管理.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/VIP会员.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/人脸核验.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/付费报告.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/企业关联图谱.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 8 | yes | - |
| `modules/企业搜索.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 8 | yes | - |
| `modules/失信被执行人.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/客诉工单.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/小程序访客访问控制.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/广告控制.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/开放API.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/找客户.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `modules/支付系统.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/收藏系统.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `modules/数据导出.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/服务端告警.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/未注册用户管理.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `modules/法人高管查询.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/消息通知.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/用户认证.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 14 | yes | - |
| `modules/积分系统.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/管理端在线监控.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/联盟商品广告.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/裁判文书搜索.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 3 | yes | - |
| `modules/邀请分享.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 4 | yes | - |
| `modules/隐私合规.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/风险扫描.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `modules/风险监控.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 6 | yes | - |
| `modules/风险评估.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 2 | yes | - |
| `modules/高级筛选.md` | verified_by=源码同步, last_verified=2026-04-26, authority=canonical | 5 | yes | - |
| `onboarding/_template.md` | verified_by=源码同步, sources=1, last_verified=2026-04-26, authority=canonical | 1 | yes | - |
| `runbook/_template.md` | verified_by=源码同步, sources=1, last_verified=2026-04-26, authority=canonical | 1 | yes | - |
| `runbook/本地开发环境搭建.md` | verified_by=源码同步, sources=1, last_verified=2026-04-26, authority=canonical | 1 | no | - |

## 下一步

- 若预览 OK, 跑 `python scripts/fengniao_wiki_frontmatter_batch.py --apply --yes` 真改
- `--apply` 会追加 audit 行到 `<wiki-root>/log.md`
- 如需回滚, 用 git 撤销 (前提是 wiki 在 git 仓库内)
