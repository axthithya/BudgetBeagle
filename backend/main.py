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
from db import (
    Analysis,
    SessionLocal,
    User,
    complete_analysis,
    create_analysis,
    create_user,
    fail_analysis,
    get_db,
    get_user_by_email,
    init_db,
    serialize_analysis,
)
from progress import ProgressManager
from sanitize import mask_account_id, mask_arn, parse_identity, sanitize_report


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
    region: str = Field(..., min_length=3)
    resource_group: str | None = None


class AuthRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with SessionLocal() as db:
        from db import cleanup_stale_jobs
        count = cleanup_stale_jobs(db)
        if count > 0:
            print(f"Cleaned up {count} stale job(s) from previous run.")


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
def regions(_: User = Depends(get_current_user)) -> dict[str, list[str]]:
    try:
        return {"regions": AwsScanner.enabled_regions()}
    except ScannerAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ScannerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    analysis = create_analysis(db, current_user.id, payload.region, payload.resource_group)
    asyncio.create_task(run_analysis_job(analysis.id, current_user.id, payload.region, payload.resource_group))
    return {
        "analysis_id": analysis.id,
        "status": analysis.status,
        "websocket_url": f"/ws/progress/{analysis.id}",
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


@app.post("/api/analyses/{analysis_id}/cancel")
def cancel_analysis_endpoint(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from db import cancel_analysis
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    
    if analysis.status in {"completed", "completed_with_warnings", "failed", "cancelled", "interrupted"}:
        return {"analysis": _safe_serialize(analysis)}
        
    analysis = cancel_analysis(db, analysis_id, "Analysis was cancelled by the user.")
    if analysis:
        # Notify clients
        asyncio.create_task(progress_manager.broadcast(analysis_id, "Analysis cancelled."))
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


async def run_analysis_job(analysis_id: int, user_id: int, region: str, resource_group: str | None) -> None:
    db = SessionLocal()
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis or analysis.user_id != user_id:
            await progress_manager.publish(analysis_id, "Analysis failed: analysis record not found.")
            return
        analysis.status = "running"
        db.commit()

        await progress_manager.publish(analysis_id, f"Scanning AWS resources in {region}...")
        await progress_manager.publish(analysis_id, "Pulling CloudWatch metrics...")
        scan_result = await run_in_threadpool(lambda: AwsScanner(region, resource_group).scan())

        await progress_manager.publish(analysis_id, "Building deterministic cost report...")
        db.refresh(analysis)
        if analysis.status == "cancelled":
            return
        ai_analysis = await run_in_threadpool(lambda: analyze_costs(scan_result))

        await progress_manager.publish(analysis_id, "Storing results...")
        result = {
            "region": region,
            "resource_group": resource_group,
            "scan": scan_result,
            "analysis": ai_analysis,
        }
        # Remove raw account_id from stored data – only masked version should persist
        if "account_id_raw" in result.get("scan", {}):
            del result["scan"]["account_id_raw"]
        savings_display = ai_analysis.get("estimated_monthly_savings_display")
        if not savings_display:
            raw_savings = ai_analysis.get("estimated_monthly_savings")
            savings_display = "Not enough data" if raw_savings is None else str(raw_savings)
        complete_analysis(
            db,
            analysis_id,
            result,
            resources_scanned=ai_analysis.get("resources_scanned", len(scan_result.get("resources", []))),
            issues_found=ai_analysis.get("confirmed_issues", ai_analysis.get("issues_found", len(ai_analysis.get("issues", [])))),
            estimated_savings=str(savings_display),
            status=ai_analysis.get("status", "completed"),
        )
        await progress_manager.publish(analysis_id, "Analysis complete")
    except (ScannerAuthError, ScannerRegionError, ScannerError, RuntimeError) as exc:
        fail_analysis(db, analysis_id, str(exc))
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc}")
    except Exception as exc:
        fail_analysis(db, analysis_id, "Unexpected analysis failure.")
        await progress_manager.publish(analysis_id, f"Analysis failed: {exc.__class__.__name__}")
    finally:
        db.close()


def _auth_response(user: User) -> dict[str, Any]:
    return {
        "token": create_access_token(user),
        "user": {"id": user.id, "email": user.email},
    }


def _safe_serialize(analysis: Analysis) -> dict[str, Any]:
    """Serialize an analysis record with sensitive data sanitized."""
    data = serialize_analysis(analysis)
    if isinstance(data.get("analysis_result"), dict):
        data["analysis_result"] = sanitize_report(data["analysis_result"])
    data["schema_version"] = "2.0"
    return data