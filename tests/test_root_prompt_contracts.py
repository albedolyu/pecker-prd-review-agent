from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pecker_root_prompt_aligns_with_conservative_review_contract():
    prompt = (ROOT / "啄木鸟_系统提示词.md").read_text(encoding="utf-8")

    assert "不确定不输出改进项" in prompt
    assert "每条改进项必须能定位到 PRD 的具体位置" in prompt
    assert "建议必须是开发或 PM 能直接执行的改法" in prompt


def test_mini_pecker_prompt_does_not_re_review_business_value():
    prompt = (ROOT / "小啄_系统提示词.md").read_text(encoding="utf-8")

    assert "不重新判断 PRD 业务价值" in prompt
    assert "只检查评审产物的完整性、一致性和安全红线" in prompt
    assert "业务取舍争议标为人工复核" in prompt
