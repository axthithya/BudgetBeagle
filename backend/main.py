from __future__ import annotations

import asyncio
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ai_analyzer import analyze_costs
from auth import create_access_token, get_current_user, get_user_from_token, hash_password, verify_password
from aws_scanner import AwsScanner, ScannerAuthError, ScannerError, ScannerRegionError
from multi_region import (
    ConcurrencyConfigurationError,
    NormalizedScanRequest,
    RegionResolutionError,
    apply_multi_region_metadata,
    build_region_result,
    deduplicate_findings,
    deduplicate_resources,
    normalize_scan_request,
    service_coverage_for_aggregate,
    utc_timestamp,
)
from region_discovery import discover_enabled_regions
from scan_orchestrator import run_scan_request
from db import (
    Analysis,
    SessionLocal,
    User,
    complete_analysis,
    create_analysis,
    cancel_analysis,
    create_user,
    fail_analysis,
    get_db,
    get_user_by_email,
    init_db,
    serialize_analysis,
)
from progress import ProgressManager
from report_schema import SCHEMA_VERSION, build_canonical_result, normalize_analysis_result
from sanitize import mask_account_id, mask_arn, parse_identity, sanitize_report
from export import generate_zip_export


load_dotenv()


def cors_origins() -> list[str]:
    raw_origins = os.getenv("BUDGETBEAGLE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app = FastAPI(title="BudgetBeagle API", version="2.0.0")
progress_manager = ProgressManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    region: str | None = Field(None, min_length=3)
    resource_group: str | None = None
    region_mode: str | None = None
    requested_regions: list[str] = Field(default_factory=list)

class AuthRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with SessionLocal() as db:
        from db import cleanup_history_retention, cleanup_stale_jobs
        count = cleanup_stale_jobs(db)
        if count > 0:
            print(f"Cleaned up {count} stale job(s) from previous run.")
        retained_count = cleanup_history_retention(db)
        if retained_count > 0:
            print(f"Cleaned up {retained_count} analysis history record(s) by explicit retention settings.")
        progress_manager.cleanup_expired()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/signup")
def signup(payload: AuthRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if get_user_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    user = create_user(db, email, hash_password(payload.password))
    return _auth_response(user)


@app.post("/api/auth/login")
def login(payload: AuthRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = get_user_by_email(db, payload.email.strip().lower())
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    return _auth_response(user)


@app.get("/api/regions")
def regions(_: User = Depends(get_current_user)) -> dict[str, Any]:
    return discover_enabled_regions().as_api_response()


# ── Core vs optional permissions ─────────────────────────────────────────
_CORE_PERMISSIONS = [
    "sts:GetCallerIdentity",
    "ec2:DescribeInstances",
    "ec2:DescribeVolumes",
    "ec2:DescribeAddresses",
    "ec2:DescribeNatGateways",
    "ec2:DescribeRegions",
    "elasticloadbalancing:DescribeLoadBalancers",
    "rds:DescribeDBInstances",
    "s3:ListAllMyBuckets",
    "s3:GetBucketLocation",
    "cloudwatch:GetMetricStatistics",
]
_OPTIONAL_PERMISSIONS = [
    "s3:GetLifecycleConfiguration",
    "ce:GetCostAndUsage",
]


def _check_permission(session: Any, perm: str) -> bool:
    """Best-effort check whether a permission is available."""
    try:
        if perm == "s3:GetLifecycleConfiguration":
            client = session.client("s3")
            buckets = client.list_buckets().get("Buckets", [])
            if buckets:
                try:
                    client.get_bucket_lifecycle_configuration(Bucket=buckets[0]["Name"])
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code == "AccessDenied":
                        return False
            return True
        if perm == "ce:GetCostAndUsage":
            client = session.client("ce", region_name="us-east-1")
            from datetime import date, timedelta
            today = date.today()
            start = (today - timedelta(days=1)).isoformat()
            end = today.isoformat()
            client.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
            )
            return True
        return True
    except (ClientError, NoCredentialsError, PartialCredentialsError, Exception):
        return False


@app.get("/api/aws/status")
def aws_status(_: User = Depends(get_current_user)) -> dict[str, Any]:
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    try:
        session = boto3.Session(region_name=region)
        identity = session.client("sts").get_caller_identity()
        account_id = identity.get("Account", "")
        arn = identity.get("Arn", "")
        parsed = parse_identity(arn)

        core_available = []
        core_missing = []
        for perm in _CORE_PERMISSIONS:
            core_available.append(perm)  # STS worked, core are likely available

        optional_available = []
        optional_missing = []
        for perm in _OPTIONAL_PERMISSIONS:
            if _check_permission(session, perm):
                optional_available.append(perm)
            else:
                optional_missing.append(perm)

        connection = "connected"
        if optional_missing:
            connection = "connected_with_limited_permissions"

        return {
            "connected": True,
            "connection_status": connection,
            "account_id_masked": mask_account_id(account_id),
            "identity_type": parsed["identity_type"],
            "identity_name": parsed["identity_name"],
            "default_region": region,
            "required_permissions": {
                "available": core_available,
                "missing": core_missing,
            },
            "optional_permissions": {
                "available": optional_available,
                "missing": optional_missing,
            },
        }
    except (NoCredentialsError, PartialCredentialsError):
        return {
            "connected": False,
            "connection_status": "not_connected",
            "account_id_masked": None,
            "identity_type": None,
            "identity_name": None,
            "default_region": region,
            "required_permissions": {"available": [], "missing": _CORE_PERMISSIONS},
            "optional_permissions": {"available": [], "missing": _OPTIONAL_PERMISSIONS},
        }
    except (ClientError, Exception):
        return {
            "connected": False,
            "connection_status": "not_connected",
            "account_id_masked": None,
            "identity_type": None,
            "identity_name": None,
            "default_region": region,
            "required_permissions": {"available": [], "missing": _CORE_PERMISSIONS},
            "optional_permissions": {"available": [], "missing": _OPTIONAL_PERMISSIONS},
        }


@app.get("/api/resource-groups")
def resource_groups(
    region: str | None = None,
    _: User = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    try:
        return {"resource_groups": AwsScanner.resource_groups(region)}
    except ScannerAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ScannerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze")
async def analyze(
    payload: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        scan_request = normalize_scan_request(
            region=payload.region,
            resource_group=payload.resource_group,
            region_mode=payload.region_mode,
            requested_regions=payload.requested_regions,
        )
    except RegionResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc

    analysis = create_analysis(db, current_user.id, scan_request.display_region, payload.resource_group)
    asyncio.create_task(
        run_analysis_job(
            analysis.id,
            current_user.id,
            scan_request.primary_region,
            payload.resource_group,
            region_mode=scan_request.region_mode,
            requested_regions=scan_request.requested_regions,
            resolved_regions=scan_request.resolved_regions,
        )
    )
    return {
        "analysis_id": analysis.id,
        "status": analysis.status,
        "websocket_url": f"/ws/progress/{analysis.id}",
        **scan_request.as_dict(),
    }

@app.get("/api/history")
def history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    analyses = (
        db.query(Analysis)
        .filter(Analysis.user_id == current_user.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    return {"analyses": [_safe_serialize(analysis) for analysis in analyses]}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    return {"analysis": _safe_serialize(analysis)}


@app.get("/api/analyses/{analysis_id}/export/zip")
def export_analysis_zip(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    if analysis.status not in {"completed", "completed_with_warnings"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Analysis is not completed.")
    return generate_zip_export(_safe_serialize(analysis))


@app.post("/api/analyses/{analysis_id}/cancel")
async def cancel_analysis_endpoint(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    
    if analysis.status in {"completed", "completed_with_warnings", "failed", "cancelled", "interrupted"}:
        return {"analysis": _safe_serialize(analysis)}
        
    analysis = cancel_analysis(db, analysis_id, "Analysis was cancelled by the user.")
    if analysis:
        await progress_manager.publish(
            analysis_id,
            "Analysis cancelled.",
            event="cancelled",
            status="cancelled",
            terminal=True,
            details={"reason": "Analysis was cancelled by the user."},
        )
    return {"analysis": _safe_serialize(analysis)}


@app.websocket("/ws/progress/{analysis_id}")
async def websocket_progress(websocket: WebSocket, analysis_id: int) -> None:
    token = websocket.query_params.get("token", "")
    db = SessionLocal()
    try:
        user = get_user_from_token(token, db)
        analysis = db.get(Analysis, analysis_id)
        if not analysis or analysis.user_id != user.id:
            await websocket.close(code=1008)
            return
    except HTTPException:
        await websocket.close(code=1008)
        return
    finally:
        db.close()

    await progress_manager.connect(analysis_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress_manager.disconnect(analysis_id, websocket)


async def run_analysis_job(
    analysis_id: int,
    user_id: int,
    region: str,
    resource_group: str | None,
    *,
    region_mode: str | None = None,
    requested_regions: list[str] | None = None,
    resolved_regions: list[str] | None = None,
) -> None:
    db = SessionLocal()
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis or analysis.user_id != user_id:
            await progress_manager.publish(analysis_id, "Analysis failed: analysis record not found.", event="failed", status="failed", terminal=True)
            return
        if analysis.status == "cancelled":
            return
        scan_request = _job_scan_request(region, resource_group, region_mode, requested_regions, resolved_regions)
        analysis.status = "running"
        db.commit()

        async def stop_if_cancelled(stage: str) -> bool:
            db.refresh(analysis)
            if analysis.status != "cancelled":
                return False
            await progress_manager.publish(
                analysis_id,
                "Analysis cancelled.",
                event="cancelled",
                status="cancelled",
                terminal=True,
                details={"stage": stage, "reason": (analysis.analysis_result or {}).get("reason") or "Analysis was cancelled by the user."},
            )
            return True

        if await stop_if_cancelled("before_scan"):
            return

        if scan_request.is_multi_region:
            await progress_manager.publish(
                analysis_id,
                f"Scanning AWS resources across {len(scan_request.resolved_regions)} regions...",
                status="running",
                details=_progress_details(scan_request, stage="scan", overall_percentage=5),
            )

            async def publish_progress(message: str, details: dict[str, Any]) -> None:
                await progress_manager.publish(analysis_id, message, status="running", details=_progress_details(scan_request, **details))

            scan_result, regional_results, partial_warnings = await run_scan_request(
                scan_request,
                scanner_cls=AwsScanner,
                publish_progress=publish_progress,
                is_cancelled=stop_if_cancelled,
            )
            scan_for_analysis = scan_result
        else:
            started_at = utc_timestamp()
            await progress_manager.publish(analysis_id, f"Scanning AWS resources in {scan_request.primary_region}...", status="running", details={"stage": "scan"})
            await progress_manager.publish(analysis_id, "Pulling CloudWatch metrics...", status="running", details={"stage": "metrics"})
            scan_result = await run_in_threadpool(lambda: AwsScanner(scan_request.primary_region, resource_group).scan())
            finished_at = utc_timestamp()
            regional_results = [
                build_region_result(
                    region=scan_request.primary_region,
                    status="completed_with_warnings" if scan_result.get("warnings") or scan_result.get("errors") else "completed",
                    started_at=started_at,
                    finished_at=finished_at,
                    resources=scan_result.get("resources", []),
                    warnings=scan_result.get("warnings", []),
                    errors=scan_result.get("errors", []),
                )
            ]
            partial_warnings = []
            scan_for_analysis = scan_result

        if await stop_if_cancelled("after_scan"):
            return
        await progress_manager.publish(
            analysis_id,
            "Building deterministic cost report...",
            status="running",
            details=_progress_details(scan_request, stage="analysis", overall_percentage=88),
        )
        ai_analysis = await run_in_threadpool(lambda: analyze_costs(scan_for_analysis))

        if await stop_if_cancelled("after_analysis"):
            return
        await progress_manager.publish(
            analysis_id,
            "Storing results...",
            status="running",
            details=_progress_details(scan_request, stage="storage", overall_percentage=96),
        )
        result = build_canonical_result(region=scan_request.primary_region, resource_group=resource_group, scan_result=scan_result, analysis=ai_analysis)
        result = _finalize_scan_result(result, scan_request, regional_results, partial_warnings)

        if await stop_if_cancelled("before_storage"):
            return
        savings_display = result.get("report", {}).get("estimated_monthly_savings_display") or "Not enough data"
        final_status = str(result.get("report", {}).get("status") or "completed")
        complete_analysis(
            db,
            analysis_id,
            result,
            resources_scanned=int(result.get("report", {}).get("resources_scanned") or len(result.get("resources", []))),
            issues_found=int(result.get("report", {}).get("confirmed_issues") or 0),
            estimated_savings=str(savings_display),
            status=final_status,
        )
        await progress_manager.publish(
            analysis_id,
            "Analysis complete" if final_status != "failed" else "Analysis failed",
            event="completed" if final_status != "failed" else "failed",
            status=final_status,
            terminal=True,
            details=_progress_details(scan_request, stage="complete", overall_percentage=100),
        )
    except (ScannerAuthError, ScannerRegionError, ScannerError, ConcurrencyConfigurationError) as exc:
        fail_analysis(db, analysis_id, str(exc))
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc}", event="failed", status="failed", terminal=True, details={"reason": str(exc)})
    except RegionResolutionError as exc:
        fail_analysis(db, analysis_id, str(exc))
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc}", event="failed", status="failed", terminal=True, details={"reason": str(exc), "code": exc.code})
    except RuntimeError as exc:
        db.refresh(analysis)
        if analysis.status == "cancelled":
            return
        fail_analysis(db, analysis_id, str(exc))
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc}", event="failed", status="failed", terminal=True, details={"reason": str(exc)})
    except Exception as exc:
        fail_analysis(db, analysis_id, "Unexpected analysis failure.")
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc.__class__.__name__}", event="failed", status="failed", terminal=True, details={"reason": "Unexpected analysis failure."})
    finally:
        db.close()


def _job_scan_request(
    region: str,
    resource_group: str | None,
    region_mode: str | None,
    requested_regions: list[str] | None,
    resolved_regions: list[str] | None,
) -> NormalizedScanRequest:
    if region_mode and resolved_regions:
        return NormalizedScanRequest(
            region_mode=region_mode,
            requested_regions=requested_regions or ([region] if region_mode == "single_region" else []),
            resolved_regions=resolved_regions,
            resource_group=resource_group,
        )
    return normalize_scan_request(region=region, resource_group=resource_group, region_mode=region_mode, requested_regions=requested_regions)


def _finalize_scan_result(
    result: dict[str, Any],
    scan_request: NormalizedScanRequest,
    regional_results: list[dict[str, Any]],
    partial_warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    scan = result.get("scan", {}) if isinstance(result.get("scan"), dict) else {}
    account_id = scan.get("account_id") or (result.get("billing", {}) if isinstance(result.get("billing"), dict) else {}).get("account_id")
    resources = deduplicate_resources(result.get("resources", []), account_id=account_id)
    findings = deduplicate_findings(result.get("findings", []), account_id=account_id, resources=resources)
    result["resources"] = resources
    result["findings"] = findings
    warnings = result.get("warnings", []) if isinstance(result.get("warnings"), list) else []
    errors = scan.get("errors", []) if isinstance(scan.get("errors"), list) else []
    result["service_coverage"] = service_coverage_for_aggregate(resources, warnings, errors)
    return apply_multi_region_metadata(
        result,
        request=scan_request,
        regional_results=regional_results,
        partial_failure_warnings=partial_warnings,
    )


def _progress_details(scan_request: NormalizedScanRequest, **details: Any) -> dict[str, Any]:
    payload = {
        "region_mode": scan_request.region_mode,
        "requested_regions": scan_request.requested_regions,
        "resolved_regions": scan_request.resolved_regions,
        "total_region_count": len(scan_request.resolved_regions),
        "completed_region_count": details.pop("completed_region_count", 0),
        "failed_region_count": details.pop("failed_region_count", 0),
        "active_regions": details.pop("active_regions", []),
        "cancellation_state": "not_cancelled",
        "overall_percentage": min(max(int(details.pop("overall_percentage", 0)), 0), 100),
    }
    payload.update(details)
    return payload

def _auth_response(user: User) -> dict[str, Any]:
    return {
        "token": create_access_token(user),
        "user": {"id": user.id, "email": user.email},
    }


def _safe_serialize(analysis: Analysis) -> dict[str, Any]:
    """Serialize an analysis record with sensitive data sanitized and schema-normalized."""
    data = serialize_analysis(analysis)
    result = data.get("analysis_result")
    if isinstance(result, dict):
        if "error" in result and not any(key in result for key in ("report", "analysis", "scan", "findings", "resources")):
            data["analysis_result"] = sanitize_report(result)
        else:
            data["analysis_result"] = sanitize_report(
                normalize_analysis_result(result, region=data.get("region"), resource_group=data.get("scan_target"))
            )
    normalized = data.get("analysis_result") if isinstance(data.get("analysis_result"), dict) else {}
    report = normalized.get("report", {}) if isinstance(normalized.get("report"), dict) else {}
    data["issues_found"] = int(report.get("confirmed_issues") or data.get("issues_found") or 0)
    data["confirmed_issues"] = int(report.get("confirmed_issues") or 0)
    data["recommendations"] = int(report.get("recommendations") or 0)
    data["observations"] = int(report.get("observations") or 0)
    data["actionable_findings"] = int(report.get("actionable_findings") or data["confirmed_issues"] + data["recommendations"])
    data["service_coverage_summary"] = report.get("service_coverage_summary", {})
    data["schema_version"] = SCHEMA_VERSION
    return data
