from __future__ import annotations

import json
import os
import re
from typing import Any

from groq import Groq


DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def analyze_costs(scan_result: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    client = Groq(api_key=api_key)
    resources = scan_result.get("resources", [])

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an AWS cloud cost analyst. Return only valid JSON with keys "
                    "summary, issues, estimated_monthly_savings, and notes. Each issue must include "
                    "resource_id, issue_type, severity, explanation, estimated_monthly_savings, "
                    "and fix_command. Never recommend destructive commands without explaining that "
                    "the user must review them first."
                ),
            },
            {
                "role": "user",
                "content": _build_prompt(scan_result),
            },
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    return _parse_json(content, resources)


def _build_prompt(scan_result: dict[str, Any]) -> str:
    payload = {
        "region": scan_result.get("region"),
        "resource_group": scan_result.get("resource_group") or "whole-region",
        "resources": scan_result.get("resources", []),
        "scanner_errors": scan_result.get("errors", []),
    }
    return (
        "Analyze this AWS resource inventory and CloudWatch metrics for concrete cost optimization "
        "opportunities. Consider over-provisioned EC2/RDS, unattached EBS, unassociated Elastic IPs, "
        "idle load balancers, NAT Gateway hourly charges, dev/test Multi-AZ databases, storage tier "
        "mismatches, and S3 buckets missing lifecycle policies. Use the real metric values in the "
        "payload. Estimate savings conservatively when exact billing data is unavailable, and include "
        "copy-pasteable aws CLI commands for each issue.\n\n"
        f"{json.dumps(payload, indent=2, default=str)}"
    )


def _parse_json(content: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL)
        if not fenced:
            raise RuntimeError("Groq returned a response that was not valid JSON.")
        parsed = json.loads(fenced.group(1))

    issues = parsed.get("issues") or []
    return {
        "summary": parsed.get("summary", "Analysis complete."),
        "issues": issues,
        "estimated_monthly_savings": parsed.get("estimated_monthly_savings", _sum_savings(issues)),
        "notes": parsed.get("notes", []),
        "resources_scanned": len(resources),
        "issues_found": len(issues),
    }


def _sum_savings(issues: list[dict[str, Any]]) -> str:
    total = 0.0
    for issue in issues:
        value = issue.get("estimated_monthly_savings")
        if isinstance(value, (int, float)):
            total += float(value)
    return f"${total:.2f}/month" if total else "Unknown"

