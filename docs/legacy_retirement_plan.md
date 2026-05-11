# Streamlit legacy 退役计划

## 结论

`legacy/` 目录里的 Streamlit 旧版已退役，2026-06-01 删除。删除前只允许做风险提示和迁移说明，不再新增功能。

## 迁移目标

- 统一团队入口到 Next.js + FastAPI。
- 避免 Streamlit 与 Next.js 双轨长期不一致。
- 把 PM 试用反馈、审计日志、报告导出和后台统计都沉到主线实现。

## 删除前检查

- 线上 Next.js 入口可访问：http://pecker.xxx.internal
- 上传 PRD、知识盲区预检、并行评审、逐条确认、导出报告均由 Next.js 主线覆盖。
- DEV.md 不再引导启动 `streamlit run legacy/app.py`。
- requirements.txt 和 pyproject.toml 均标记 `streamlit>=1.35.0` 为 2026-06-01 待删除依赖。

## 2026-06-01 删除 PR 范围

- 删除 `legacy/`。
- 从 `requirements.txt` 删除 `streamlit>=1.35.0`。
- 从 `pyproject.toml` 删除 `streamlit>=1.35.0`。
- 跑通 Python 测试、Web TypeScript 检查和关键导出流程。
