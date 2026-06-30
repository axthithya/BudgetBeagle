from __future__ import annotations

from copy import deepcopy
from typing import Any

SUPPORTED_SERVICES = ["EC2", "EBS", "S3", "RDS", "Load Balancing", "Elastic IP", "NAT Gateway"]


def build_canonical_result(
    *,
    region: str,
    resource_group: str | None,
    scan_result: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    scan = deepcopy(scan_result) if isinstance(scan_result, dict) else {}
    deterministic = deepcopy(analysis) if isinstance(analysis, dict) else {}
    resources = [_normalize_resource(item) for item in scan.get("resources", [])]
    findings = deepcopy(deterministic.get("findings") or deterministic.get("issues") or [])
    warnings = deepcopy(deterministic.get("warnings") or scan.get("warnings") or [])
    billing = deepcopy(deterministic.get("billing") or scan.get("billing") or {})
    metrics = deepcopy(deterministic.get("metrics") or {})
    service_coverage = deterministic.get("service_coverage") or metrics.get("service_coverage") or build_service_coverage(resources, warnings)
    savings_confidence = deterministic.get("savings_confidence") or _aggregate_savings_confidence(deterministic.get("estimated_monthly_savings"))

    report = {
        "status": deterministic.get("status") or ("completed_with_warnings" if warnings else "completed"),
        "summary": deterministic.get("summary") or "Report completed.",
        "resources_scanned": deterministic.get("resources_scanned", len(resources)),
        "issues_found": deterministic.get("issues_found", deterministic.get("confirmed_issues", 0)),
        "confirmed_issues": deterministic.get("confirmed_issues", deterministic.get("issues_found", 0)),
        "recommendations": deterministic.get("recommendations", 0),
        "observations": deterministic.get("observations", 0),
        "warnings_count": deterministic.get("warnings_count", len(warnings)),
        "estimated_monthly_savings": deterministic.get("estimated_monthly_savings"),
        "estimated_monthly_savings_display": deterministic.get("estimated_monthly_savings_display", "Not enough data"),
        "potential_monthly_savings": deterministic.get("potential_monthly_savings"),
        "potential_maximum_avoidable_cost": deterministic.get("potential_maximum_avoidable_cost"),
        "yearly_savings": deterministic.get("yearly_savings"),
        "savings_confidence": savings_confidence,
    }

    return {
        "schema_version": "2.0",
        "report": report,
        "scan": _scan_metadata(scan, region, resource_group),
        "billing": billing,
        "resources": resources,
        "findings": findings,
        "warnings": warnings,
        "metrics": metrics,
        "scan_confidence": deterministic.get("scan_confidence") or deterministic.get("confidence") or _default_scan_confidence(),
        "service_coverage": service_coverage,
        "ai_enrichment": {
            "status": deterministic.get("ai_enrichment_status", "none"),
            "summary": deterministic.get("ai_summary"),
            "notes": deterministic.get("notes", []),
        },
    }


def normalize_analysis_result(raw: dict[str, Any], *, region: str | None = None, resource_group: str | None = None) -> dict[str, Any]:
    data = deepcopy(raw) if isinstance(raw, dict) else {}
    if not data:
        return {}
    if "error" in data and not any(key in data for key in ("report", "analysis", "scan", "findings", "resources")):
        return data
    if "report" in data and "resources" in data and "findings" in data:
        canonical = deepcopy(data)
        canonical.setdefault("schema_version", "2.0")
        canonical.setdefault("warnings", [])
        canonical.setdefault("billing", {})
        canonical.setdefault("metrics", {})
        canonical.setdefault("service_coverage", build_service_coverage(canonical.get("resources", []), canonical.get("warnings", [])))
        canonical.setdefault("ai_enrichment", {"status": canonical.pop("ai_enrichment_status", "none"), "notes": []})
        canonical.pop("issues", None)
        return canonical

    scan = data.get("scan") if isinstance(data.get("scan"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else data
    if "findings" not in analysis and "findings" in data:
        analysis = {**analysis, "findings": data.get("findings")}
    if "warnings" not in analysis and "warnings" in data:
        analysis = {**analysis, "warnings": data.get("warnings")}
    if "billing" not in analysis and "billing" in data:
        analysis = {**analysis, "billing": data.get("billing")}
    if "metrics" not in analysis and "metrics" in data:
        analysis = {**analysis, "metrics": data.get("metrics")}
    if "scan_confidence" not in analysis and "scan_confidence" in data:
        analysis = {**analysis, "scan_confidence": data.get("scan_confidence")}

    return build_canonical_result(
        region=str(region or data.get("region") or scan.get("region") or ""),
        resource_group=resource_group if resource_group is not None else data.get("resource_group") or scan.get("resource_group"),
        scan_result=scan,
        analysis=analysis,
    )


def build_service_coverage(resources: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    count_by_service: dict[str, int] = {}
    for resource in resources:
        service = _coverage_service_name(str(resource.get("service") or ""))
        if service:
            count_by_service[service] = count_by_service.get(service, 0) + 1
    warn_services = {_coverage_service_name(str(warning.get("service") or "")) for warning in warnings}

    coverage: list[dict[str, Any]] = []
    for service in SUPPORTED_SERVICES:
        count = count_by_service.get(service, 0)
        has_warning = service in warn_services
        if count > 0 and has_warning:
            status = "completed_with_warnings"
        elif count > 0:
            status = "completed"
        else:
            status = "no_resources"
        coverage.append({"service": service, "status": status, "count": count})
    return coverage


def _scan_metadata(scan: dict[str, Any], region: str, resource_group: str | None) -> dict[str, Any]:
    metadata = {key: deepcopy(value) for key, value in scan.items() if key not in {"resources", "warnings", "billing"}}
    metadata["region"] = region or metadata.get("region") or ""
    metadata["resource_group"] = resource_group if resource_group is not None else metadata.get("resource_group")
    return metadata


def _normalize_resource(resource: Any) -> dict[str, Any]:
    item = deepcopy(resource) if isinstance(resource, dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    if metrics.get("low_utilization_candidate") is True:
        cpu = metrics.get("cpu_utilization") if isinstance(metrics.get("cpu_utilization"), dict) else {}
        datapoints = _to_number(cpu.get("datapoint_count") or metrics.get("cpu_datapoints")) or 0
        hours = _to_number(cpu.get("actual_duration_hours") or metrics.get("observed_hours")) or 0
        sufficient = datapoints >= 24 and hours >= 24
        metrics["utilization_signal"] = {
            "signal": "low_cpu",
            "evidence_sufficient": sufficient,
            "assessment": "recommendation" if sufficient else "observation",
        }
        metrics.pop("low_utilization_candidate", None)
        item["metrics"] = metrics
    return item


def _coverage_service_name(service: str) -> str:
    normalized = service.upper().replace(" ", "")
    if normalized in {"ELB", "CLASSICELB", "ELBV2", "LOADBALANCING"}:
        return "Load Balancing"
    if normalized in {"ELASTICIP", "EIP"}:
        return "Elastic IP"
    if normalized == "NATGATEWAY":
        return "NAT Gateway"
    if normalized in {"EC2", "EBS", "S3", "RDS"}:
        return normalized
    return ""


def _aggregate_savings_confidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, (int, float)):
        return {
            "level": "not_applicable",
            "label": "Not applicable",
            "basis": "No numeric evidence-backed savings were available.",
            "factors": [{"name": "Numeric savings", "effect": "neutral", "reason": "Savings confidence is not applicable without numeric savings."}],
        }
    return {
        "score": 85,
        "level": "high" if value == 0 else "medium",
        "label": "High" if value == 0 else "Medium",
        "basis": "Numeric savings are evidence-backed and separated from finding confidence.",
        "factors": [{"name": "Numeric savings", "effect": "positive", "reason": "Only numeric evidence-backed savings are included."}],
    }


def _default_scan_confidence() -> dict[str, Any]:
    return {
        "score": 75,
        "level": "medium",
        "label": "Medium",
        "basis": "Scan confidence was normalized from a legacy report.",
        "factors": [{"name": "Legacy report", "effect": "neutral", "reason": "Detailed scan-confidence factors were not stored in the original report."}],
    }


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
