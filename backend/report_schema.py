from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "2.1"
SUPPORTED_SERVICES = ["EC2", "EBS", "S3", "RDS", "Load Balancing", "Elastic IP", "NAT Gateway"]
SCANNED_SERVICE_STATUSES = {"completed", "completed_with_warnings", "no_resources"}

CATEGORY_LABELS = {
    "confirmed_issue": "Confirmed issue",
    "recommendation": "Recommendation",
    "observation": "Observation",
}


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
    findings = [_normalize_finding(item) for item in (deterministic.get("findings") or deterministic.get("issues") or [])]
    warnings = deepcopy(deterministic.get("warnings") or scan.get("warnings") or [])
    errors = deepcopy(scan.get("errors") or deterministic.get("errors") or [])
    billing = normalize_billing_context(deterministic.get("billing") or scan.get("billing") or {})
    metrics = normalize_money_fields(deepcopy(deterministic.get("metrics") or {}))
    service_coverage = build_service_coverage(
        resources,
        warnings,
        errors,
        deterministic.get("service_coverage") or metrics.get("service_coverage") or scan.get("service_coverage"),
    )
    counts = finding_summary(findings) if findings else _fallback_counts(deterministic)
    service_summary = coverage_summary(service_coverage)
    savings_confidence = deterministic.get("savings_confidence") or _aggregate_savings_confidence(deterministic.get("estimated_monthly_savings"))

    report = {
        "status": deterministic.get("status") or ("completed_with_warnings" if warnings else "completed"),
        "summary": deterministic.get("summary") or _summary_text(len(resources), counts, deterministic.get("estimated_monthly_savings_display")),
        "resources_scanned": deterministic.get("resources_scanned", len(resources)),
        "issues_found": counts["confirmed_issues"],
        "confirmed_issues": counts["confirmed_issues"],
        "recommendations": counts["recommendations"],
        "observations": counts["observations"],
        "actionable_findings": counts["actionable_findings"],
        "warnings_count": deterministic.get("warnings_count", len(warnings)),
        "estimated_monthly_savings": normalize_money_number(deterministic.get("estimated_monthly_savings")),
        "estimated_monthly_savings_display": normalize_money_string(deterministic.get("estimated_monthly_savings_display", "Not enough data")),
        "potential_monthly_savings": normalize_money_fields(deterministic.get("potential_monthly_savings")),
        "potential_maximum_avoidable_cost": normalize_money_fields(deterministic.get("potential_maximum_avoidable_cost")),
        "yearly_savings": normalize_money_fields(deterministic.get("yearly_savings")),
        "savings_confidence": savings_confidence,
        "service_coverage_summary": service_summary,
    }

    result = {
        "schema_version": SCHEMA_VERSION,
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
    return normalize_money_fields(_ensure_region_metadata(result, region=region, resource_group=resource_group))


def normalize_analysis_result(raw: dict[str, Any], *, region: str | None = None, resource_group: str | None = None) -> dict[str, Any]:
    data = deepcopy(raw) if isinstance(raw, dict) else {}
    if not data:
        return {}
    if "error" in data and not any(key in data for key in ("report", "analysis", "scan", "findings", "resources")):
        return data
    if "report" in data and "resources" in data and "findings" in data:
        canonical = deepcopy(data)
        canonical["schema_version"] = SCHEMA_VERSION
        canonical.setdefault("warnings", [])
        canonical.setdefault("billing", {})
        canonical.setdefault("metrics", {})
        canonical["resources"] = [_normalize_resource(item) for item in canonical.get("resources", [])]
        canonical["findings"] = [_normalize_finding(item) for item in canonical.get("findings", [])]
        report = canonical.setdefault("report", {})
        counts = finding_summary(canonical["findings"]) if canonical["findings"] else _fallback_counts(report)
        report["issues_found"] = counts["confirmed_issues"]
        report["confirmed_issues"] = counts["confirmed_issues"]
        report["recommendations"] = counts["recommendations"]
        report["observations"] = counts["observations"]
        report["actionable_findings"] = counts["actionable_findings"]
        canonical["billing"] = normalize_billing_context(canonical.get("billing", {}))
        canonical["metrics"] = normalize_money_fields(canonical.get("metrics", {}))
        canonical["service_coverage"] = build_service_coverage(
            canonical.get("resources", []),
            canonical.get("warnings", []),
            canonical.get("scan", {}).get("errors", []) if isinstance(canonical.get("scan"), dict) else [],
            canonical.get("service_coverage"),
        )
        report["service_coverage_summary"] = coverage_summary(canonical["service_coverage"])
        canonical.setdefault("ai_enrichment", {"status": canonical.pop("ai_enrichment_status", "none"), "notes": []})
        canonical.pop("issues", None)
        return normalize_money_fields(_ensure_region_metadata(canonical, region=region, resource_group=resource_group))

    scan = data.get("scan") if isinstance(data.get("scan"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else data
    for key in ("findings", "warnings", "billing", "metrics", "scan_confidence", "service_coverage"):
        if key not in analysis and key in data:
            analysis = {**analysis, key: data.get(key)}

    return build_canonical_result(
        region=str(region or data.get("region") or scan.get("region") or ""),
        resource_group=resource_group if resource_group is not None else data.get("resource_group") or scan.get("resource_group"),
        scan_result=scan,
        analysis=analysis,
    )


def canonical_finding_category(value: Any) -> str:
    normalized = str(value or "recommendation").strip().lower()
    normalized = re.sub(r"[\s-]+", "_", normalized).replace("confirmedissue", "confirmed_issue")
    if normalized in {"confirmed_issue", "confirmed_issues", "issue", "issues"}:
        return "confirmed_issue"
    if normalized in {"recommendation", "recommendations", "review_candidate"}:
        return "recommendation"
    if normalized in {"observation", "observations", "informational"}:
        return "observation"
    return "recommendation"


def category_label(value: Any) -> str:
    return CATEGORY_LABELS.get(canonical_finding_category(value), "Recommendation")


def finding_summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    confirmed = sum(1 for item in findings if canonical_finding_category(item.get("category")) == "confirmed_issue")
    recommendations = sum(1 for item in findings if canonical_finding_category(item.get("category")) == "recommendation")
    observations = sum(1 for item in findings if canonical_finding_category(item.get("category")) == "observation")
    return {
        "confirmed_issues": confirmed,
        "recommendations": recommendations,
        "observations": observations,
        "actionable_findings": confirmed + recommendations,
    }


def build_service_coverage(
    resources: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]] | None = None,
    explicit: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    count_by_service: dict[str, int] = {}
    for resource in resources:
        service = _coverage_service_name(str(resource.get("service") or ""))
        if service:
            count_by_service[service] = count_by_service.get(service, 0) + 1

    warning_services = {_coverage_service_name(str(warning.get("service") or "")) for warning in warnings}
    warning_services.discard("")
    error_services = {_coverage_service_name(str(error.get("service") or "")) for error in (errors or [])}
    error_services.discard("")
    explicit_by_service: dict[str, dict[str, Any]] = {}
    for item in explicit or []:
        service = _coverage_service_name(str(item.get("service") or ""))
        if service:
            explicit_by_service[service] = item

    coverage: list[dict[str, Any]] = []
    for service in SUPPORTED_SERVICES:
        explicit_item = explicit_by_service.get(service, {})
        explicit_count = _to_int(explicit_item.get("count")) if explicit_item else None
        count = count_by_service.get(service, 0) if explicit_count is None else explicit_count
        status = _normalize_coverage_status(explicit_item.get("status")) if explicit_item else ""
        if not status:
            if service in error_services:
                status = "failed"
            elif service in warning_services:
                status = "completed_with_warnings"
            elif count > 0:
                status = "completed"
            else:
                status = "no_resources"
        if status == "completed" and service in warning_services:
            status = "completed_with_warnings"
        coverage.append({
            "service": service,
            "status": status,
            "count": count,
            "label": coverage_label(status, count),
            "scanned": status in SCANNED_SERVICE_STATUSES,
            "has_resources": count > 0,
        })
    return coverage


def coverage_summary(coverage: list[dict[str, Any]]) -> dict[str, int | str]:
    total = len(coverage) or len(SUPPORTED_SERVICES)
    scanned = sum(1 for item in coverage if item.get("status") in SCANNED_SERVICE_STATUSES or item.get("scanned") is True)
    containing_resources = sum(
        1 for item in coverage if item.get("status") in SCANNED_SERVICE_STATUSES and int(item.get("count") or 0) > 0
    )
    resources_discovered = sum(int(item.get("count") or 0) for item in coverage)
    failed = sum(1 for item in coverage if item.get("status") == "failed")
    skipped = sum(1 for item in coverage if item.get("status") == "skipped")
    return {
        "total_supported_services": total,
        "services_scanned": scanned,
        "services_containing_resources": containing_resources,
        "resources_discovered": resources_discovered,
        "failed_services": failed,
        "skipped_services": skipped,
        "services_scanned_display": f"{scanned}/{total}",
        "services_containing_resources_display": f"{containing_resources}/{total}",
    }


def coverage_label(status: str, count: int) -> str:
    if status == "completed_with_warnings":
        if count > 0:
            return f"Completed with warnings - {count} resource{'s' if count != 1 else ''}"
        return "Completed with warnings - no resources"
    if status == "completed":
        return f"Completed - {count} resource{'s' if count != 1 else ''}"
    if status == "no_resources":
        return "Completed - no resources"
    if status == "failed":
        return "Failed"
    if status == "skipped":
        return "Skipped"
    return status.replace("_", " ").title()


def normalize_billing_context(value: Any) -> dict[str, Any]:
    billing = deepcopy(value) if isinstance(value, dict) else {}
    for key in ("account_total_ytd_usd", "selected_region_ytd_usd"):
        if key in billing:
            billing[key] = normalize_money_number(billing[key])
    for key in ("monthly_account_costs", "monthly_selected_region_costs", "service_costs_ytd", "region_costs_ytd"):
        if key not in billing:
            continue
        rows = []
        for row in billing.get(key, []) or []:
            item = deepcopy(row) if isinstance(row, dict) else {}
            amount = normalize_money_number(item.get("amount_usd"))
            if amount is not None:
                item["amount_usd"] = amount
                item["display"] = format_money(amount)
            elif "display" in item:
                item["display"] = normalize_money_string(item["display"])
            if key == "region_costs_ytd":
                region_name = _billing_region_name(item.get("name") or item.get("label"))
                item["name"] = region_name
                if item.get("label"):
                    item["label"] = region_name
            rows.append(item)
        billing[key] = _merge_billing_region_rows(rows) if key == "region_costs_ytd" else rows
    return normalize_money_fields(billing)



def _billing_region_name(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized.lower() in {"noregion", "global", "global / no region"}:
        return "Global / No Region"
    return normalized or "Unknown"


def _merge_billing_region_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for item in rows:
        name = str(item.get("name") or item.get("label") or "").strip()
        amount = item.get("amount_usd")
        if not name or not isinstance(amount, (int, float)):
            passthrough.append(item)
            continue
        existing = merged.get(name)
        if existing is None:
            merged[name] = item
            continue
        total = normalize_money_number(float(existing.get("amount_usd") or 0) + float(amount)) or 0.0
        existing["amount_usd"] = total
        existing["display"] = format_money(total)
    return [*merged.values(), *passthrough]


def normalize_money_fields(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_usd") or key in {"amount_usd", "estimated_monthly_savings"}:
                result[key] = normalize_money_number(item)
            elif isinstance(item, str):
                result[key] = normalize_money_string(item)
            else:
                result[key] = normalize_money_fields(item)
        return result
    if isinstance(value, list):
        return [normalize_money_fields(item) for item in value]
    if isinstance(value, str):
        return normalize_money_string(value)
    return value


def normalize_money_number(value: Any) -> float | None:
    numeric = _to_number(value)
    if numeric is None:
        return None
    if abs(numeric) < 0.005:
        return 0.0
    return round(numeric, 2)


def normalize_money_string(value: Any) -> str:
    return str(value).replace("$-0.00", "$0.00").replace("-$0.00", "$0.00").replace("-0.00 USD", "0.00 USD")


def format_money(value: Any) -> str:
    numeric = normalize_money_number(value)
    if numeric is None:
        return "Not enough data"
    return f"${numeric:.2f}"


def format_monthly_savings(value: Any) -> str:
    numeric = normalize_money_number(value)
    if numeric is None:
        return "Not enough data"
    return f"${numeric:.2f}/month"


def _ensure_region_metadata(result: dict[str, Any], *, region: str | None, resource_group: str | None) -> dict[str, Any]:
    scan = result.setdefault("scan", {})
    if not isinstance(scan, dict):
        scan = {}
        result["scan"] = scan
    primary_region = str(result.get("region") or scan.get("region") or region or "").strip()
    mode = str(result.get("region_mode") or scan.get("region_mode") or "single_region")
    resolved = _string_list(result.get("resolved_regions") or scan.get("resolved_regions"))
    if not resolved and primary_region:
        resolved = [primary_region]
    requested = _string_list(result.get("requested_regions") or scan.get("requested_regions")) or list(resolved)
    if not resolved and requested:
        resolved = list(requested)
    if mode not in {"single_region", "selected_regions", "all_enabled_regions"}:
        mode = "single_region"
    if mode == "single_region" and len(resolved) > 1:
        mode = "selected_regions"

    result["region"] = primary_region or (resolved[0] if resolved else "")
    result["legacy_primary_region"] = result["region"]
    result["resource_group"] = resource_group if resource_group is not None else result.get("resource_group") or scan.get("resource_group")
    result["region_mode"] = mode
    result["requested_regions"] = requested
    result["resolved_regions"] = resolved
    result["region_count"] = len(resolved)

    resources = result.get("resources") if isinstance(result.get("resources"), list) else []
    findings = result.get("findings") if isinstance(result.get("findings"), list) else []
    for resource in resources:
        if isinstance(resource, dict):
            resource.setdefault("scope", "regional")
            if resolved and resource.get("scope") != "global":
                resource.setdefault("region", result["region"] or resolved[0])
    resource_region_by_id = {
        str(resource.get("id") or resource.get("resource_id") or ""): resource.get("region")
        for resource in resources
        if isinstance(resource, dict)
    }
    for finding in findings:
        if isinstance(finding, dict):
            finding.setdefault("source", "budgetbeagle_rule")
            finding.setdefault("scope", "regional")
            rid = str(finding.get("resource_id") or "")
            if resolved and finding.get("scope") != "global":
                finding.setdefault("region", resource_region_by_id.get(rid) or result["region"] or resolved[0])

    regional_results = result.get("regional_results") or scan.get("regional_results") or []
    if not isinstance(regional_results, list) or not regional_results:
        regional_results = [_legacy_region_result(region_name, resources, findings, result.get("warnings", [])) for region_name in (resolved or [result["region"]]) if region_name]
    partial_warnings = result.get("partial_failure_warnings") or scan.get("partial_failure_warnings") or []
    result["regional_results"] = regional_results
    result["partial_failure_warnings"] = partial_warnings if isinstance(partial_warnings, list) else []
    result["regional_resources"] = [resource for resource in resources if isinstance(resource, dict) and resource.get("scope") != "global"]
    result["global_resources"] = [resource for resource in resources if isinstance(resource, dict) and resource.get("scope") == "global"]
    result["regional_findings"] = [finding for finding in findings if isinstance(finding, dict) and finding.get("scope") != "global"]
    result["global_findings"] = [finding for finding in findings if isinstance(finding, dict) and finding.get("scope") == "global"]

    scan.update({
        "region": result["region"],
        "legacy_primary_region": result["legacy_primary_region"],
        "resource_group": result["resource_group"],
        "region_mode": mode,
        "requested_regions": requested,
        "resolved_regions": resolved,
        "regional_results": regional_results,
        "partial_failure_warnings": result["partial_failure_warnings"],
    })
    report = result.setdefault("report", {})
    if isinstance(report, dict):
        report.setdefault("region_count", len(resolved))
        report.setdefault("regions_completed", sum(1 for item in regional_results if isinstance(item, dict) and item.get("status") in {"completed", "completed_with_warnings"}))
        report.setdefault("regions_failed", sum(1 for item in regional_results if isinstance(item, dict) and item.get("status") == "failed"))
    return result


def _legacy_region_result(region: str, resources: list[Any], findings: list[Any], warnings: list[Any]) -> dict[str, Any]:
    resource_count = sum(1 for item in resources if isinstance(item, dict) and str(item.get("region") or region) == region)
    finding_count = sum(1 for item in findings if isinstance(item, dict) and str(item.get("region") or region) == region)
    warning_items = [item for item in warnings if isinstance(item, dict) and str(item.get("region") or region) == region]
    return {
        "region": region,
        "status": "completed_with_warnings" if warning_items else "completed",
        "started_at": None,
        "finished_at": None,
        "elapsed_ms": 0,
        "resources_discovered": resource_count,
        "findings_generated": finding_count,
        "warnings": warning_items,
        "warning_count": len(warning_items),
        "error_category": None,
        "safe_error_message": None,
        "services_attempted": SUPPORTED_SERVICES,
        "services_completed": SUPPORTED_SERVICES,
        "services_failed": [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]

def _normalize_finding(finding: Any) -> dict[str, Any]:
    item = deepcopy(finding) if isinstance(finding, dict) else {}
    category = canonical_finding_category(item.get("category"))
    item["category"] = category
    item["category_label"] = item.get("category_label") or category_label(category)
    return normalize_money_fields(item)


def _fallback_counts(deterministic: dict[str, Any]) -> dict[str, int]:
    confirmed = _to_int(deterministic.get("confirmed_issues"))
    if confirmed is None:
        confirmed = _to_int(deterministic.get("issues_found")) or 0
    recommendations = _to_int(deterministic.get("recommendations")) or 0
    observations = _to_int(deterministic.get("observations")) or 0
    actionable = _to_int(deterministic.get("actionable_findings"))
    if actionable is None:
        actionable = confirmed + recommendations
    return {
        "confirmed_issues": confirmed,
        "recommendations": recommendations,
        "observations": observations,
        "actionable_findings": actionable,
    }


def _summary_text(resources: int, counts: dict[str, int], monthly_display: Any) -> str:
    savings = normalize_money_string(monthly_display or "Not enough data")
    return (
        f"Scanned {resources} resources. Found {counts['confirmed_issues']} confirmed issues, "
        f"{counts['recommendations']} recommendations, and {counts['observations']} observations. "
        f"Potential monthly savings: {savings}."
    )


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
    return normalize_money_fields(item)


def _coverage_service_name(service: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", service.upper())
    if normalized in {"ELB", "CLASSICELB", "ELBV2", "LOADBALANCING", "LOADBALANCER", "LOADBALANCERS"}:
        return "Load Balancing"
    if normalized in {"ELASTICIP", "EIP", "ELASTICIPS"}:
        return "Elastic IP"
    if normalized in {"NATGATEWAY", "NATGATEWAYS"}:
        return "NAT Gateway"
    if normalized in {"EC2", "EBS", "S3", "RDS"}:
        return normalized
    return ""


def _normalize_coverage_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if status in {"completed", "completed_with_warnings", "no_resources", "failed", "skipped"}:
        return status
    if status in {"completed_no_resources", "completed__no_resources"}:
        return "no_resources"
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


def _to_int(value: Any) -> int | None:
    numeric = _to_number(value)
    return None if numeric is None else int(numeric)
