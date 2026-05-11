from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_legacy_readme_declares_retirement_deadline():
    content = _read("legacy/README.md")

    assert "已退役" in content
    assert "2026-06-01" in content
    assert "Next.js" in content
    assert "http://pecker" in content


def test_legacy_app_warns_and_delays_startup():
    content = _read("legacy/app.py")

    assert 'LEGACY_RETIREMENT_DATE = "2026-06-01"' in content
    assert "st.error" in content
    assert "time.sleep(3)" in content


def test_legacy_app_requires_explicit_override_to_run():
    content = _read("legacy/app.py")

    assert 'LEGACY_ENABLE_ENV = "PECKER_ENABLE_LEGACY_STREAMLIT"' in content
    assert 'os.environ.get(LEGACY_ENABLE_ENV) != "1"' in content
    assert "st.stop()" in content


def test_dev_guide_no_longer_guides_streamlit_startup():
    content = _read("DEV.md")

    assert "# 终端 3 — Streamlit" not in content
    assert "streamlit run legacy/app.py" not in content


def test_streamlit_dependency_is_marked_deprecated():
    requirements = _read("requirements.txt")
    pyproject = _read("pyproject.toml")

    assert "# deprecated, remove 2026-06-01" in requirements
    assert "streamlit>=1.35.0" in requirements
    assert "# deprecated, remove 2026-06-01" in pyproject
    assert '"streamlit>=1.35.0"' in pyproject


def test_migration_and_retirement_plan_cover_legacy_capabilities():
    migration = _read("docs/MIGRATION_v1_to_v2.md")
    plan = _read("docs/legacy_retirement_plan.md")

    assert "Streamlit legacy 退役" in migration
    for capability in ["上传 PRD", "知识盲区", "并行评审", "逐条确认", "导出报告"]:
        assert capability in migration

    assert "2026-06-01" in plan
    assert "legacy/" in plan
    assert "Next.js" in plan
