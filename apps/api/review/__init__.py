"""Pecker评审核心子模块拆分 (2026-04-16).

parallel_review.py 1883 行太大,按职责拆到这里:
- dimensions.py: YAML 维度加载 + schema 校验 + 默认值 fallback
- evidence_verify.py: wiki/rules 依据可回溯性验证 + B 类语义检查

parallel_review.py 仍是对外入口,继续 re-export 所有公开符号。
"""
