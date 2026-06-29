from __future__ import annotations

import asyncio
from typing import Any

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


load_dotenv()

app = FastAPI(title="AI Cloud Cost Detective API", version="0.4.0")
progress_manager = ProgressManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
    return {"analyses": [serialize_analysis(analysis) for analysis in analyses]}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    analysis = db.get(Analysis, analysis_id)
    if not analysis or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    return {"analysis": serialize_analysis(analysis)}


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
        ai_analysis = await run_in_threadpool(lambda: analyze_costs(scan_result))

        await progress_manager.publish(analysis_id, "Storing results...")
        result = {
            "region": region,
            "resource_group": resource_group,
            "scan": scan_result,
            "analysis": ai_analysis,
        }
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