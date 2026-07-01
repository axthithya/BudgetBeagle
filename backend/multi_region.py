from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from region_discovery import RegionDiscoveryResult, discover_enabled_regions, normalize_region_values
from report_schema import build_service_coverage, coverage_summary, finding_summary


SCHEMA_VERSION = "2.1"
SCAN_MODES = {"single_region", "selected_regions", "all_enabled_regions"}
REGIONAL_STATUSES = {"pending", "running", "completed", "completed_with_warnings", "failed", "cancelled", "interrupted"}
OVERALL_TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "cancelled", "interrupted"}
DEFAULT_MULTI_REGION_CONCURRENCY = 3
MAX_MULTI_REGION_CONCURRENCY = 10


class RegionResolutionError(ValueError):
    def __init__(self, message: str, *, code: str = "InvalidRegionSelection", status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ConcurrencyConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedScanRequest:
    region_mode: str
    requested_regions: list[str]
    resolved_regions: list[str]
    resource_group: str | None = None

    @property
    def primary_region(self) -> str:
        return self.resolved_regions[0] if self.resolved_regions else ""

    @property
    def is_multi_region(self) -> bool:
        return self.region_mode != "single_region" or len(self.resolved_regions) > 1

    @property
    def display_region(self) -> str:
        if len(self.resolved_regions) == 1:
            return self.resolved_regions[0]
        if self.region_mode == "all_enabled_regions":
            return "all_enabled_regions"
        return "multiple_regions"

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_mode": self.region_mode,
            "requested_regions": list(self.requested_regions),
            "resolved_regions": list(self.resolved_regions),
            "region_count": len(self.resolved_regions),
        }


def normalize_scan_request(
    *,
    region: str | None,
    resource_group: str | None,
    region_mode: str | None = None,
    requested_regions: list[str] | None = None,
    discovery: RegionDiscoveryResult | None = None,
) -> NormalizedScanRequest:
    mode = (region_mode or "").strip() or "single_region"
    if mode not in SCAN_MODES:
        raise RegionResolutionError(f"Unsupported region mode: {mode}", code="UnsupportedRegionMode")

    submitted = [str(item).strip() for item in (requested_regions or []) if str(item or "").strip()]

    if mode == "single_region":
        selected = submitted[0] if submitted else str(region or "").strip()
        if not selected:
            raise RegionResolutionError("A region is required for single-region scans.", code="MissingRegion")
        try:
            resolved = normalize_region_values([selected])
        except ValueError as exc:
            raise RegionResolutionError(str(exc), code="MalformedRegion") from exc
        return NormalizedScanRequest(
            region_mode="single_region",
            requested_regions=[selected],
            resolved_regions=resolved,
            resource_group=resource_group,
        )

    if mode == "selected_regions":
        if not submitted:
            raise RegionResolutionError("Select at least one region.", code="MissingSelectedRegions")
        try:
            resolved = normalize_region_values(submitted)
        except ValueError as exc:
            raise RegionResolutionError(str(exc), code="MalformedRegion") from exc
        return NormalizedScanRequest(
            region_mode="selected_regions",
            requested_regions=submitted,
            resolved_regions=resolved,
            resource_group=resource_group,
        )

    result = discovery or discover_enabled_regions()
    if not result.available:
        error = result.error
        message = error.message if error else "Enabled regions could not be discovered."
        code = error.code if error else "RegionDiscoveryUnavailable"
        raise RegionResolutionError(message, code=code, status_code=403 if result.status == "permission_denied" else 400)
    return NormalizedScanRequest(
        region_mode="all_enabled_regions",
        requested_regions=[],
        resolved_regions=result.regions,
        resource_group=resource_group,
    )


def validate_multi_region_concurrency(raw: str | None = None) -> int:
    value = raw if raw is not None else os.getenv("MULTI_REGION_CONCURRENCY", str(DEFAULT_MULTI_REGION_CONCURRENCY))
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConcurrencyConfigurationError("MULTI_REGION_CONCURRENCY must be an integer.") from exc
    if parsed < 1:
        raise ConcurrencyConfigurationError("MULTI_REGION_CONCURRENCY must be at least 1.")
    if parsed > MAX_MULTI_REGION_CONCURRENCY:
        raise ConcurrencyConfigurationError(f"MULTI_REGION_CONCURRENCY must be {MAX_MULTI_REGION_CONCURRENCY} or lower.")
    return parsed


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started_at: str, finished_at: str) -> int:
    try:
        start = datetime.fromisoformat(started_at)
        finish = datetime.fromisoformat(finished_at)
        return max(int((finish - start).total_seconds() * 1000), 0)
    except ValueError:
        return 0


def build_region_result(
    *,
    region: str,
    status: str,
    started_at: str,
    finished_at: str,
    resources: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    services_attempted: list[str] | None = None,
    services_completed: list[str] | None = None,
    services_failed: list[str] | None = None,
    error_category: str | None = None,
    safe_error_message: str | None = None,
) -> dict[str, Any]:
    resources = resources or []
    warnings = warnings or []
    errors = errors or []
    attempted = _normalize_service_list(services_attempted or supported_scan_services())
    default_failed = [str(item.get("service") or "") for item in errors]
    failed = _normalize_service_list(services_failed if services_failed is not None else default_failed)
    if services_completed is None:
        if status in {"failed", "cancelled", "interrupted"}:
            completed = []
        else:
            completed = [service for service in attempted if service not in failed]
    else:
        completed = _normalize_service_list(services_completed)
    status = _consistent_region_status(status, attempted, completed, failed)
    return {
        "region": region,
        "status": status if status in REGIONAL_STATUSES else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms(started_at, finished_at),
        "resources_discovered": len(resources),
        "findings_generated": 0,
        "warnings": warnings,
        "warning_count": len(warnings),
        "error_category": error_category,
        "safe_error_message": safe_error_message,
        "services_attempted": attempted,
        "services_completed": completed,
        "services_failed": failed,
    }


def supported_scan_services() -> list[str]:
    return ["EC2", "EBS", "Elastic IP", "Load Balancing", "RDS", "S3", "NAT Gateway"]


def decorate_resource(resource: dict[str, Any], *, account_id: str | None, fallback_region: str | None) -> dict[str, Any]:
    item = dict(resource)
    region = str(item.get("region") or fallback_region or "").strip()
    scope = str(item.get("scope") or ("regional" if region else "global"))
    if scope == "global":
        region = "global"
    item["scope"] = scope
    if region:
        item["region"] = region
    item.setdefault("account_id", account_id)
    item["canonical_resource_id"] = canonical_resource_identity(item, account_id=account_id)
    return item


def decorate_finding(
    finding: dict[str, Any],
    *,
    account_id: str | None,
    resource_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    item = dict(finding)
    service = str(item.get("service") or "AWS")
    resource_id = str(item.get("resource_id") or item.get("id") or "unknown")
    matched = resource_lookup.get((_norm(service), resource_id)) or resource_lookup.get(("", resource_id))
    region = str(item.get("region") or (matched or {}).get("region") or "")
    scope = str(item.get("scope") or (matched or {}).get("scope") or ("regional" if region else "global"))
    if scope == "global":
        region = "global"
    if region:
        item["region"] = region
    item["scope"] = scope
    item["source"] = str(item.get("source") or "budgetbeagle_rule")
    item["canonical_finding_id"] = canonical_finding_identity(item, account_id=account_id)
    item["id"] = item["canonical_finding_id"]
    return item


def canonical_resource_identity(resource: dict[str, Any], *, account_id: str | None) -> str:
    account = str(account_id or resource.get("account_id") or "unknown-account")
    region = str(resource.get("region") or "global")
    scope = str(resource.get("scope") or ("regional" if region != "global" else "global"))
    service = str(resource.get("service") or "AWS")
    resource_type = str(resource.get("resource_type") or resource.get("type_or_sku") or "unknown")
    resource_id = str(resource.get("id") or resource.get("resource_id") or "unknown")
    return _identity("resource", account, scope, region, service, resource_type, resource_id)


def canonical_finding_identity(finding: dict[str, Any], *, account_id: str | None) -> str:
    account = str(account_id or finding.get("account_id") or "unknown-account")
    source = str(finding.get("source") or "budgetbeagle_rule")
    region = str(finding.get("region") or "global")
    scope = str(finding.get("scope") or ("regional" if region != "global" else "global"))
    service = str(finding.get("service") or "AWS")
    resource_id = str(finding.get("resource_id") or "unknown")
    rule = str(finding.get("recommendation_type") or finding.get("issue_type") or finding.get("category") or "finding")
    return _identity("finding", source, account, scope, region, service, resource_id, rule)


def deduplicate_resources(resources: list[dict[str, Any]], *, account_id: str | None) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for resource in resources:
        item = decorate_resource(resource, account_id=account_id, fallback_region=resource.get("region"))
        by_id[item["canonical_resource_id"]] = item
    return list(by_id.values())


def deduplicate_findings(
    findings: list[dict[str, Any]],
    *,
    account_id: str | None,
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lookup = _resource_lookup(resources)
    by_id: dict[str, dict[str, Any]] = {}
    for finding in findings:
        item = decorate_finding(finding, account_id=account_id, resource_lookup=lookup)
        by_id[item["canonical_finding_id"]] = item
    return list(by_id.values())


def apply_multi_region_metadata(
    canonical: dict[str, Any],
    *,
    request: NormalizedScanRequest,
    regional_results: list[dict[str, Any]],
    partial_failure_warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = dict(canonical)
    result["schema_version"] = SCHEMA_VERSION
    result.update(request.as_dict())
    result["regional_results"] = _finalize_region_counts(regional_results, result.get("resources", []), result.get("findings", []))
    result["partial_failure_warnings"] = list(partial_failure_warnings or [])
    result["regional_resources"] = [item for item in result.get("resources", []) if item.get("scope") != "global"]
    result["global_resources"] = [item for item in result.get("resources", []) if item.get("scope") == "global"]
    result["regional_findings"] = [item for item in result.get("findings", []) if item.get("scope") != "global"]
    result["global_findings"] = [item for item in result.get("findings", []) if item.get("scope") == "global"]
    scan = result.setdefault("scan", {})
    if isinstance(scan, dict):
        scan.update(request.as_dict())
        scan["regional_results"] = result["regional_results"]
        scan["partial_failure_warnings"] = result["partial_failure_warnings"]
    report = result.setdefault("report", {})
    if isinstance(report, dict):
        status = overall_status(result["regional_results"], resources=result.get("resources", []), warnings=result.get("warnings", []))
        report["status"] = status
        report["warnings_count"] = len(result.get("warnings", []))
        report["region_count"] = len(request.resolved_regions)
        report["regions_completed"] = sum(1 for item in result["regional_results"] if item.get("status") in {"completed", "completed_with_warnings"})
        report["regions_failed"] = sum(1 for item in result["regional_results"] if item.get("status") == "failed")
        report["service_coverage"] = result.get("service_coverage", [])
        report["service_coverage_summary"] = coverage_summary(result.get("service_coverage", []))
    return result


def overall_status(regional_results: list[dict[str, Any]], *, resources: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "failed") for item in regional_results]
    if any(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status == "interrupted" for status in statuses):
        return "interrupted"
    if statuses and all(status == "failed" for status in statuses) and not resources:
        return "failed"
    if any(status in {"failed", "completed_with_warnings"} for status in statuses) or warnings:
        return "completed_with_warnings"
    return "completed"


def partial_region_warning(region: str, message: str, *, code: str = "RegionScanFailed") -> dict[str, Any]:
    return {
        "service": "Region",
        "resource_id": region,
        "region": region,
        "code": code,
        "message": message,
        "title": f"{region} scan did not fully complete",
        "resolution": "Review IAM permissions and region availability, then retry the scan.",
        "severity": "warning",
    }


def service_coverage_for_aggregate(resources: list[dict[str, Any]], warnings: list[dict[str, Any]], errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return build_service_coverage(resources, warnings, errors)


def summary_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    return finding_summary(findings)


def _normalize_service_list(values: list[str] | None) -> list[str]:
    services: list[str] = []
    for value in values or []:
        service = _coverage_name(str(value)) or str(value or "").strip()
        if service and service not in services:
            services.append(service)
    return services


def _consistent_region_status(status: str, attempted: list[str], completed: list[str], failed: list[str]) -> str:
    normalized = status if status in REGIONAL_STATUSES else "failed"
    if attempted and set(failed) >= set(attempted) and not completed:
        return "failed"
    if normalized == "completed" and (failed or (attempted and not completed)):
        return "completed_with_warnings"
    return normalized


def _completed_services(resources: list[dict[str, Any]], warnings: list[dict[str, Any]], errors: list[dict[str, Any]]) -> list[str]:
    failed = {_coverage_name(str(item.get("service") or "")) for item in errors}
    completed = {_coverage_name(str(item.get("service") or "")) for item in resources}
    completed.update(_coverage_name(str(item.get("service") or "")) for item in warnings)
    completed.discard("")
    return sorted(service for service in completed if service not in failed)


def _finalize_region_counts(
    regional_results: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    resources_by_region: dict[str, int] = {}
    findings_by_region: dict[str, int] = {}
    for resource in resources:
        region = str(resource.get("region") or "global")
        resources_by_region[region] = resources_by_region.get(region, 0) + 1
    for finding in findings:
        region = str(finding.get("region") or "global")
        findings_by_region[region] = findings_by_region.get(region, 0) + 1
    finalized = []
    for item in regional_results:
        region = str(item.get("region") or "")
        updated = dict(item)
        updated["resources_discovered"] = resources_by_region.get(region, int(updated.get("resources_discovered") or 0))
        updated["findings_generated"] = findings_by_region.get(region, int(updated.get("findings_generated") or 0))
        finalized.append(updated)
    return sorted(finalized, key=lambda item: str(item.get("region") or ""))


def _resource_lookup(resources: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    by_id_counts: dict[str, int] = {}
    for resource in resources:
        rid = str(resource.get("id") or resource.get("resource_id") or "")
        if not rid:
            continue
        by_id_counts[rid] = by_id_counts.get(rid, 0) + 1
        lookup[(_norm(str(resource.get("service") or "")), rid)] = resource
    for resource in resources:
        rid = str(resource.get("id") or resource.get("resource_id") or "")
        if rid and by_id_counts.get(rid) == 1:
            lookup[("", rid)] = resource
    return lookup


def _identity(*parts: str) -> str:
    return ":".join(_slug(part) for part in parts)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._:/@-]+", "-", str(value).strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _coverage_name(service: str) -> str:
    normalized = _norm(service)
    if normalized in {"ELB", "CLASSICELB", "ELBV2", "LOADBALANCING", "LOADBALANCER", "LOADBALANCERS"}:
        return "Load Balancing"
    if normalized in {"ELASTICIP", "EIP", "ELASTICIPS"}:
        return "Elastic IP"
    if normalized in {"NATGATEWAY", "NATGATEWAYS"}:
        return "NAT Gateway"
    if normalized in {"EC2", "EBS", "S3", "RDS"}:
        return normalized
    return ""
