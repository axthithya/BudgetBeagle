from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable

import boto3

from aws_scanner import AwsScanner
from billing import scan_billing_context
from multi_region import (
    NormalizedScanRequest,
    build_region_result,
    deduplicate_resources,
    partial_region_warning,
    service_coverage_for_aggregate,
    supported_scan_services,
    utc_timestamp,
    validate_multi_region_concurrency,
)
from sanitize import scrub_sensitive_text


ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
CancelCallback = Callable[[str], Awaitable[bool]]


async def run_scan_request(
    request: NormalizedScanRequest,
    *,
    scanner_cls: type = AwsScanner,
    publish_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if not request.is_multi_region:
        return await _run_single_region(request, scanner_cls=scanner_cls)
    return await _run_multi_region(request, scanner_cls=scanner_cls, publish_progress=publish_progress, is_cancelled=is_cancelled)


async def _run_single_region(
    request: NormalizedScanRequest,
    *,
    scanner_cls: type,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    region = request.primary_region
    started_at = utc_timestamp()
    scan_result = await asyncio.to_thread(lambda: _new_scanner(scanner_cls, region, request.resource_group).scan())
    finished_at = utc_timestamp()
    regional_result = build_region_result(
        region=region,
        status="completed_with_warnings" if scan_result.get("warnings") or scan_result.get("errors") else "completed",
        started_at=started_at,
        finished_at=finished_at,
        resources=scan_result.get("resources", []),
        warnings=scan_result.get("warnings", []),
        errors=scan_result.get("errors", []),
    )
    scan_result.update(request.as_dict())
    scan_result["regional_results"] = [regional_result]
    scan_result["partial_failure_warnings"] = []
    return scan_result, [regional_result], []


async def _run_multi_region(
    request: NormalizedScanRequest,
    *,
    scanner_cls: type,
    publish_progress: ProgressCallback | None,
    is_cancelled: CancelCallback | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    concurrency = validate_multi_region_concurrency()
    queue: asyncio.Queue[str] = asyncio.Queue()
    for region in request.resolved_regions:
        queue.put_nowait(region)

    regional_results: list[dict[str, Any]] = []
    regional_scans: list[dict[str, Any]] = []
    partial_warnings: list[dict[str, Any]] = []
    active_regions: set[str] = set()
    completed_count = 0
    failed_count = 0
    total = len(request.resolved_regions)
    last_percent = 0
    loop = asyncio.get_running_loop()

    async def emit(message: str, **details: Any) -> None:
        nonlocal last_percent
        if publish_progress:
            next_percent = _progress_percent(completed_count, failed_count, total, details.pop("base_percent", 5))
            last_percent = max(last_percent, next_percent)
            await publish_progress(message, {
                "stage": details.pop("stage", "scan"),
                "region_mode": request.region_mode,
                "total_region_count": total,
                "completed_region_count": completed_count,
                "failed_region_count": failed_count,
                "active_regions": sorted(active_regions),
                "overall_percentage": last_percent,
                **details,
            })

    async def worker(worker_id: int, executor: ThreadPoolExecutor) -> None:
        nonlocal completed_count, failed_count
        while True:
            if is_cancelled and await is_cancelled(f"before_region_worker_{worker_id}"):
                return
            try:
                region = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started_at = utc_timestamp()
            active_regions.add(region)
            await emit(f"Scanning AWS resources in {region}...", current_region=region)
            try:
                scanner = _new_scanner(scanner_cls, region, request.resource_group, include_billing=False, scan_s3=False)
                scan_result = await loop.run_in_executor(executor, scanner.scan)
                finished_at = utc_timestamp()
                resources = scan_result.get("resources", [])
                warnings = scan_result.get("warnings", [])
                errors = scan_result.get("errors", [])
                status = "completed_with_warnings" if warnings or errors else "completed"
                regional_scans.append(scan_result)
                regional_results.append(
                    build_region_result(
                        region=region,
                        status=status,
                        started_at=started_at,
                        finished_at=finished_at,
                        resources=resources,
                        warnings=warnings,
                        errors=errors,
                    )
                )
                completed_count += 1
            except Exception as exc:
                finished_at = utc_timestamp()
                message = _safe_exception_message(exc)
                warning = partial_region_warning(region, message)
                partial_warnings.append(warning)
                regional_results.append(
                    build_region_result(
                        region=region,
                        status="failed",
                        started_at=started_at,
                        finished_at=finished_at,
                        resources=[],
                        warnings=[warning],
                        errors=[{"service": "Region", "code": exc.__class__.__name__, "message": message, "region": region}],
                        error_category=exc.__class__.__name__,
                        safe_error_message=message,
                    )
                )
                failed_count += 1
            finally:
                active_regions.discard(region)
                queue.task_done()
                await emit(
                    f"Finished {region}.",
                    current_region=region,
                    resources_discovered=sum(len(scan.get("resources", [])) for scan in regional_scans),
                    warning_count=len(partial_warnings) + sum(len(scan.get("warnings", [])) for scan in regional_scans),
                )

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="budgetbeagle-region") as executor:
        workers = [asyncio.create_task(worker(index, executor)) for index in range(min(concurrency, total))]
        await asyncio.gather(*workers)

    if is_cancelled and await is_cancelled("after_regions"):
        raise RuntimeError("Analysis was cancelled.")

    resources: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(partial_warnings)
    errors: list[dict[str, Any]] = []
    account_id = None
    account_id_raw = None
    identity_type = None
    identity_name = None
    for scan in sorted(regional_scans, key=lambda item: str(item.get("region") or "")):
        resources.extend(scan.get("resources", []))
        warnings.extend(scan.get("warnings", []))
        errors.extend(scan.get("errors", []))
        account_id = account_id or scan.get("account_id")
        account_id_raw = account_id_raw or scan.get("account_id_raw")
        identity_type = identity_type or scan.get("identity_type")
        identity_name = identity_name or scan.get("identity_name")

    s3_scan = await _scan_s3_once(request, scanner_cls=scanner_cls, publish_progress=publish_progress)
    if s3_scan:
        resources.extend(s3_scan.get("resources", []))
        warnings.extend(s3_scan.get("warnings", []))
        errors.extend(s3_scan.get("errors", []))
        account_id = account_id or s3_scan.get("account_id")
        account_id_raw = account_id_raw or s3_scan.get("account_id_raw")
        identity_type = identity_type or s3_scan.get("identity_type")
        identity_name = identity_name or s3_scan.get("identity_name")

    billing_warnings: list[dict[str, Any]] = []

    def warn(service: str, resource_id: str | None, code: str, message: str, permission: str | None) -> None:
        billing_warnings.append({
            "service": service,
            "resource_id": resource_id,
            "code": code,
            "message": message,
            "permission": permission,
            "severity": "warning",
        })

    billing = await asyncio.to_thread(
        lambda: scan_billing_context(
            boto3.Session(region_name=request.primary_region),
            selected_regions=request.resolved_regions,
            account_id=account_id_raw or account_id,
            warn=warn,
        )
    )
    warnings.extend(billing_warnings)
    resources = deduplicate_resources(resources, account_id=account_id)

    aggregate = {
        "region": request.primary_region,
        "resource_group": request.resource_group,
        "account_id": account_id,
        "account_id_raw": account_id_raw,
        "identity_type": identity_type,
        "identity_name": identity_name,
        "billing": billing,
        "resources": resources,
        "errors": errors,
        "warnings": warnings,
        "service_coverage": service_coverage_for_aggregate(resources, warnings, errors),
        **request.as_dict(),
        "regional_results": sorted(regional_results, key=lambda item: str(item.get("region") or "")),
        "partial_failure_warnings": partial_warnings,
    }
    return aggregate, aggregate["regional_results"], partial_warnings


async def _scan_s3_once(
    request: NormalizedScanRequest,
    *,
    scanner_cls: type,
    publish_progress: ProgressCallback | None,
) -> dict[str, Any] | None:
    scanner = _new_scanner(scanner_cls, request.primary_region, request.resource_group, include_billing=False, scan_s3=False)
    if not hasattr(scanner, "scan_s3_buckets_for_regions"):
        return None
    if publish_progress:
        await publish_progress("Scanning S3 buckets once for selected regions...", {
            "stage": "s3",
            "region_mode": request.region_mode,
            "total_region_count": len(request.resolved_regions),
            "overall_percentage": 75,
            "current_service": "S3",
        })
    return await asyncio.to_thread(lambda: scanner.scan_s3_buckets_for_regions(request.resolved_regions))


def _new_scanner(scanner_cls: type, region: str, resource_group: str | None, **kwargs: Any) -> Any:
    try:
        return scanner_cls(region, resource_group, **kwargs)
    except TypeError:
        return scanner_cls(region, resource_group)


def _progress_percent(completed_count: int, failed_count: int, total: int, base_percent: int) -> int:
    if total <= 0:
        return base_percent
    percent = base_percent + int(((completed_count + failed_count) / total) * 65)
    return max(base_percent, min(percent, 95))


def _safe_exception_message(exc: Exception) -> str:
    message = scrub_sensitive_text(str(exc) or exc.__class__.__name__)
    if not message or len(message) > 500:
        return "Region scan failed."
    return message
