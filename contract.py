"""
Contract for the Post Fiat Task Node task-generation agent surface.

This is the minimum structured output an AI agent must produce when proposing
a task for the Task Node to record on-chain. It is intentionally small — the
goal is to test whether AI-mediated coordination is *deterministic enough to
audit*, not to model the full Post Fiat stack.

A valid agent response is a JSON object with the fields below, optionally
followed by a single tool call (`submit_task` or `escalate_to_human`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: tuple[str, ...] = (
    "task_id",
    "task_type",
    "description",
    "reward_pft",
    "difficulty",
    "verification_method",
)

ALLOWED_TASK_TYPES: frozenset[str] = frozenset({
    "code_review",
    "data_labeling",
    "documentation",
    "research",
    "validation",
})

ALLOWED_DIFFICULTY: frozenset[str] = frozenset({"low", "medium", "high"})

ALLOWED_VERIFICATION: frozenset[str] = frozenset({
    "validator_consensus",
    "automated_check",
    "human_review",
})

# Tools the agent is permitted to call.
ALLOWED_TOOLS: frozenset[str] = frozenset({"submit_task", "escalate_to_human"})

# Required arguments per tool.
TOOL_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "submit_task": ("task_id", "memo_format"),
    "escalate_to_human": ("reason",),
}

# Whitelisted argument keys per tool. Anything outside this set is a
# contract violation — useful for catching agents that hallucinate args.
TOOL_ALLOWED_ARGS: dict[str, frozenset[str]] = {
    "submit_task": frozenset({"task_id", "memo_format", "priority"}),
    "escalate_to_human": frozenset({"reason", "context"}),
}


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A single contract violation or note."""
    code: str
    message: str
    severity: str  # "fail" | "warn"


@dataclass
class ValidationResult:
    findings: list[Finding]

    @property
    def outcome(self) -> str:
        if any(f.severity == "fail" for f in self.findings):
            return "fail"
        if any(f.severity == "warn" for f in self.findings):
            return "warn"
        return "pass"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_structured_output(payload: Any) -> list[Finding]:
    """Validate the structured-output portion of an agent response."""
    findings: list[Finding] = []

    if not isinstance(payload, dict):
        findings.append(Finding(
            code="STRUCT_NOT_OBJECT",
            message=f"structured_output must be a JSON object, got {type(payload).__name__}",
            severity="fail",
        ))
        return findings

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in payload:
            findings.append(Finding(
                code="STRUCT_MISSING_FIELD",
                message=f"missing required field: {field}",
                severity="fail",
            ))

    # Enum-style fields (only check if present)
    if "task_type" in payload and payload["task_type"] not in ALLOWED_TASK_TYPES:
        findings.append(Finding(
            code="STRUCT_BAD_ENUM",
            message=f"task_type {payload['task_type']!r} not in {sorted(ALLOWED_TASK_TYPES)}",
            severity="fail",
        ))

    if "difficulty" in payload and payload["difficulty"] not in ALLOWED_DIFFICULTY:
        findings.append(Finding(
            code="STRUCT_BAD_ENUM",
            message=f"difficulty {payload['difficulty']!r} not in {sorted(ALLOWED_DIFFICULTY)}",
            severity="fail",
        ))

    if "verification_method" in payload and payload["verification_method"] not in ALLOWED_VERIFICATION:
        findings.append(Finding(
            code="STRUCT_BAD_ENUM",
            message=f"verification_method {payload['verification_method']!r} not in {sorted(ALLOWED_VERIFICATION)}",
            severity="fail",
        ))

    # reward_pft must be a positive number
    if "reward_pft" in payload:
        reward = payload["reward_pft"]
        if not isinstance(reward, (int, float)) or isinstance(reward, bool):
            findings.append(Finding(
                code="STRUCT_BAD_TYPE",
                message=f"reward_pft must be numeric, got {type(reward).__name__}",
                severity="fail",
            ))
        elif reward <= 0:
            findings.append(Finding(
                code="STRUCT_BAD_VALUE",
                message=f"reward_pft must be > 0, got {reward}",
                severity="fail",
            ))
        elif reward >= 5000:
            findings.append(Finding(
                code="STRUCT_SUSPICIOUS",
                message=f"reward_pft={reward} unusually large; review before submission",
                severity="warn",
            ))

    return findings


def validate_tool_call(tool: dict[str, Any] | None,
                       expected_tool: str | None,
                       expected_args: dict[str, Any] | None) -> list[Finding]:
    """Validate the tool-call portion of an agent response.

    `expected_tool` of None means: no tool call expected (e.g. refusal cases
    that escalate via plain text). `expected_args` may be a partial match —
    keys present must equal the recorded value.
    """
    findings: list[Finding] = []

    if expected_tool is None:
        if tool is not None:
            findings.append(Finding(
                code="TOOL_UNEXPECTED",
                message=f"expected no tool call, got {tool.get('name')!r}",
                severity="fail",
            ))
        return findings

    if tool is None:
        findings.append(Finding(
            code="TOOL_MISSING",
            message=f"expected tool call {expected_tool!r}, got none",
            severity="fail",
        ))
        return findings

    name = tool.get("name")
    args = tool.get("arguments", {})

    if name not in ALLOWED_TOOLS:
        findings.append(Finding(
            code="TOOL_DISALLOWED",
            message=f"tool {name!r} not in allowed set {sorted(ALLOWED_TOOLS)}",
            severity="fail",
        ))
        return findings

    if name != expected_tool:
        findings.append(Finding(
            code="TOOL_WRONG_NAME",
            message=f"expected tool {expected_tool!r}, got {name!r}",
            severity="fail",
        ))
        # keep going so we still surface arg issues

    if not isinstance(args, dict):
        findings.append(Finding(
            code="TOOL_BAD_ARGS",
            message=f"arguments must be an object, got {type(args).__name__}",
            severity="fail",
        ))
        return findings

    # Required args present?
    for required in TOOL_REQUIRED_ARGS.get(name, ()):
        if required not in args:
            findings.append(Finding(
                code="TOOL_MISSING_ARG",
                message=f"{name}: missing required argument {required!r}",
                severity="fail",
            ))

    # Any unexpected args?
    allowed = TOOL_ALLOWED_ARGS.get(name, frozenset())
    for key in args:
        if key not in allowed:
            findings.append(Finding(
                code="TOOL_UNEXPECTED_ARG",
                message=f"{name}: unexpected argument {key!r} (allowed: {sorted(allowed)})",
                severity="fail",
            ))

    # Recorded-value match (only on keys the fixture pinned)
    if expected_args:
        for key, expected_val in expected_args.items():
            if key in args and args[key] != expected_val:
                findings.append(Finding(
                    code="TOOL_ARG_VALUE",
                    message=f"{name}.{key}: expected {expected_val!r}, got {args[key]!r}",
                    severity="fail",
                ))

    return findings
