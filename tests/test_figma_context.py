from __future__ import annotations

import io
import json


def test_enrich_figma_raw_materials_fetches_node_text(monkeypatch):
    from api import figma_context

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        payload = {
            "name": "Checkout prototype",
            "nodes": {
                "12:34": {
                    "document": {
                        "name": "Final step",
                        "type": "FRAME",
                        "children": [
                            {"name": "Export report", "type": "TEXT", "characters": "导出报告"},
                            {"name": "Confirm button", "type": "TEXT", "characters": "确认并进入最后一步"},
                        ],
                    }
                }
            },
        }
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "test-figma-token")
    monkeypatch.setattr(figma_context.urllib.request, "urlopen", fake_urlopen)

    materials = figma_context.enrich_figma_raw_materials(
        [
            "\n".join(
                [
                    "[补充材料: Figma]",
                    "来源: PRD text",
                    "链接: https://www.figma.com/design/abc123/Product?node-id=12-34&token=secret",
                ]
            )
        ]
    )

    assert captured["url"] == "https://api.figma.com/v1/files/abc123/nodes?ids=12%3A34"
    assert captured["authorization"] == "Bearer test-figma-token"
    assert captured["timeout"] > 0
    assert len(materials) == 2
    parsed = materials[1]
    assert "[补充材料: Figma 解析]" in parsed
    assert "Checkout prototype" in parsed
    assert "Final step" in parsed
    assert "导出报告" in parsed
    assert "确认并进入最后一步" in parsed
    assert "test-figma-token" not in parsed
    assert "secret" not in parsed


def test_enrich_figma_raw_materials_gracefully_reports_missing_token(monkeypatch):
    from api import figma_context

    monkeypatch.delenv("FIGMA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("PECKER_FIGMA_ACCESS_TOKEN", raising=False)

    materials = figma_context.enrich_figma_raw_materials(
        [
            "\n".join(
                [
                    "[补充材料: Figma]",
                    "来源: PRD text",
                    "链接: https://www.figma.com/design/abc123/Product?node-id=12-34",
                ]
            )
        ]
    )

    assert len(materials) == 2
    assert "未配置 FIGMA_ACCESS_TOKEN" in materials[1]
    assert "abc123" in materials[1]


def test_enrich_figma_raw_materials_is_idempotent(monkeypatch):
    from api import figma_context

    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "test-figma-token")
    raw = [
        "\n".join(
            [
                "[补充材料: Figma]",
                "链接: https://www.figma.com/design/abc123/Product?node-id=12-34",
            ]
        ),
        "\n".join(
            [
                "[补充材料: Figma 解析]",
                "链接: https://www.figma.com/design/abc123/Product?node-id=12-34",
                "读取状态: 已读取",
            ]
        ),
    ]

    assert figma_context.enrich_figma_raw_materials(raw) == raw
