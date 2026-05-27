from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

from pecker.redaction import redact_mapping, redact_text

RiskLevel = Literal["low", "medium", "high"]


class ToolRegistryError(Exception):
    pass


class ToolAccessError(ToolRegistryError):
    pass


class ToolConfirmationRequired(ToolRegistryError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    allowed_callers: tuple[str, ...]
    risk_level: RiskLevel = "low"
    timeout_seconds: float = 30.0
    requires_human_confirmation: bool = False
    audit_policy: Literal["metadata_only", "metadata_and_redacted_params"] = "metadata_only"
    mcp_server: str | None = None
    mcp_tool: str | None = None
    mcp_operation: Literal["read", "write", "delete", "code_execution", "database_write"] | None = None


@dataclass
class ToolRegistry:
    specs: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if "*" in spec.allowed_callers:
            raise ValueError("wildcard callers are not allowed")
        if spec.mcp_operation in {"write", "delete", "code_execution", "database_write"}:
            if not spec.requires_human_confirmation:
                raise ValueError("high-risk MCP tools require human confirmation")
        self.specs[spec.name] = spec

    def execute(
        self,
        name: str,
        params: dict[str, Any],
        *,
        caller: str,
        human_confirmed: bool = False,
    ) -> dict[str, Any]:
        spec = self.specs[name]
        if caller not in spec.allowed_callers:
            raise ToolAccessError(f"{caller!r} is not allowed to call {name!r}")
        if spec.requires_human_confirmation and not human_confirmed:
            raise ToolConfirmationRequired(f"{name!r} requires human confirmation")

        started = perf_counter()
        try:
            data = spec.handler(params)
            status = "success"
            error = None
        except Exception as exc:  # noqa: BLE001 - tools return governed failures.
            data = {}
            status = "error"
            error = redact_text(str(exc))

        duration_ms = int((perf_counter() - started) * 1000)
        trace = {
            "tool": spec.name,
            "caller": caller,
            "status": status,
            "risk_level": spec.risk_level,
            "duration_ms": duration_ms,
        }
        if spec.mcp_server and spec.mcp_tool:
            trace["mcp"] = {
                "server": spec.mcp_server,
                "tool": spec.mcp_tool,
                "operation": spec.mcp_operation or "read",
            }

        audit: dict[str, Any] = {"tool": spec.name, "caller": caller}
        if spec.audit_policy == "metadata_and_redacted_params":
            audit["params"] = redact_mapping(params)

        return {"success": status == "success", "data": data, "error": error, "trace": trace, "audit": audit}


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="prd.extract_sections",
            description="Extract markdown headings from a PRD.",
            handler=lambda p: {"headings": _extract_headings(str(p.get("content") or ""))},
            allowed_callers=("review.precheck", "worker.structure"),
            risk_level="low",
            audit_policy="metadata_and_redacted_params",
        )
    )
    registry.register(
        ToolSpec(
            name="design.fetch_context",
            description="Placeholder for read-only design context fetches.",
            handler=lambda p: {"url": redact_text(str(p.get("url") or "")), "status": "placeholder"},
            allowed_callers=("review.precheck",),
            risk_level="medium",
            audit_policy="metadata_and_redacted_params",
            mcp_server="figma",
            mcp_tool="get_design_context",
            mcp_operation="read",
        )
    )
    return registry


def _extract_headings(content: str) -> list[str]:
    return [line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("#")]
