# Streamlit 旧版已退役

Streamlit 版 `legacy/app.py` 已退役，不再维护，计划在 2026-06-01 从仓库删除。

团队试用、运维部署和问题排查请统一使用 Next.js 版：

- 线上地址：http://pecker.xxx.internal
- 本地前端：`make dev-web`
- 本地后端：`make dev-api`

本目录仅保留给历史复盘和极端兜底，不接收新功能、体验优化或稳定性修复。若 Next.js 版缺少旧版能力，请先记录到 `docs/legacy_retirement_plan.md`，不要继续扩展 Streamlit。
