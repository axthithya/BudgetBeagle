from __future__ import annotations

import json
import os
import re
from typing import Any

from groq import Groq
from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:  # Pydantic v1
    ConfigDict = None  # type: ignore[assignment]

from cost_rules import build_cost_report


DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class AiFindingExplanation(BaseModel):
    finding_id: str = Field(..., min_length=1)
    explanation: str | None = None
    recommendation: str | None = None

    if ConfigDict is not None:
        model_config = ConfigDict(extra="ignore")
    else:
        class Config:
            extra = "ignore"


class AiEnhancement(BaseModel):
    summary: str | None = None
    finding_explanations: list[AiFindingExplanation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    if ConfigDict is not None:
        model_config = ConfigDict(extra="ignore")
    else:
        class Config:
            extra = "ignore"


def analyze_costs(
    scan_result: dict[str, Any],
    pricing_resolver: Any | None = None,
    use_groq: bool = True,
) -> dict[str, Any]:
    report = build_cost_report(scan_result, pricing_resolver=pricing_resolver)
    if use_groq:
        _enhance_with_groq(report, scan_result)
    return report


def _enhance_with_groq(report: dict[str, Any], scan_result: dict[str, Any]) -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return

    try:
        model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You may only rewrite explanations for findings that already exist in the payload. "
                        "Do not create findings. Do not change resource IDs, evidence, metric values, pricing, "
                        "savings, totals, severities, confidence levels, or AWS commands. Return JSON only with "
                        "keys summary, finding_explanations, and notes. finding_explanations items must contain "
                        "finding_id plus optional explanation and recommendation."
                    ),
                },
                {"role": "user", "content": _build_prompt(scan_result, report)},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        enhancement = _parse_enhancement(content)
        _apply_ai_enhancement(report, enhancement)
    except Exception:
        report.setdefault("notes", []).append("AI explanation was unavailable; deterministic findings were preserved.")


def _build_prompt(scan_result: dict[str, Any], report: dict[str, Any]) -> str:
    payload = {
        "region": scan_result.get("region"),
        "resource_group": scan_result.get("resource_group") or "whole-region",
        "validated_findings": [
            {
                "finding_id": item.get("id"),
                "category": item.get("category"),
                "service": item.get("service"),
                "resource_id": item.get("resource_id"),
                "issue_type": item.get("issue_type"),
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
                "evidence": item.get("evidence"),
                "pricing_status": item.get("pricing_status"),
                "savings_basis": item.get("savings_basis"),
                "action_risk": item.get("action_risk"),
            }
            for item in report.get("findings", [])
        ],
        "warnings": report.get("warnings", []),
        "billing": report.get("billing"),
        "confidence": report.get("confidence"),
        "deterministic_summary": report.get("summary"),
    }
    return json.dumps(payload, indent=2, default=str)


def _parse_enhancement(content: str) -> AiEnhancement:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL)
        if not fenced:
            raise
        parsed = json.loads(fenced.group(1))
    if hasattr(AiEnhancement, "model_validate"):
        return AiEnhancement.model_validate(parsed)
    return AiEnhancement.parse_obj(parsed)


def _apply_ai_enhancement(report: dict[str, Any], enhancement: AiEnhancement) -> None:
    findings_by_id = {item.get("id"): item for item in report.get("findings", [])}
    for rewrite in enhancement.finding_explanations:
        finding = findings_by_id.get(rewrite.finding_id)
        if not finding:
            continue
        if rewrite.explanation:
            finding["ai_explanation"] = rewrite.explanation
        if rewrite.recommendation:
            finding["ai_recommendation"] = rewrite.recommendation
    if enhancement.summary:
        report["ai_summary"] = enhancement.summary
    if enhancement.notes:
        report.setdefault("notes", []).extend(enhancement.notes)


__all__ = ["analyze_costs", "_apply_ai_enhancement", "AiEnhancement"]