from __future__ import annotations

import asyncio
import importlib
import io
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _fresh_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'phase1.db'}")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("ANALYSIS_HISTORY_RETENTION_ENABLED", "false")
    for module_name in ["main", "db", "auth", "ai_analyzer", "aws_scanner", "progress", "report_schema", "export"]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("main")


def _signup(client: TestClient, email: str = "user@example.com") -> tuple[str, int]:
    response = client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    body = response.json()
    return body["token"], body["user"]["id"]


def test_cancel_running_analysis_is_persisted_idempotent_and_publishes_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        token, user_id = _signup(client)
        db = main.SessionLocal()
        try:
            analysis = main.create_analysis(db, user_id, "us-east-1", None)
            analysis.status = "running"
            db.commit()
            analysis_id = analysis.id
        finally:
            db.close()

        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(f"/api/analyses/{analysis_id}/cancel", headers=headers)
        second = client.post(f"/api/analyses/{analysis_id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["analysis"]["status"] == "cancelled"
    assert second.json()["analysis"]["status"] == "cancelled"
    assert "cancelled by the user" in first.json()["analysis"]["analysis_result"]["reason"]
    assert any(event["event"] == "cancelled" and event["status"] == "cancelled" for event in main.progress_manager.history(analysis_id))


def test_cancel_completed_analysis_is_safe_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        token, user_id = _signup(client, "done@example.com")
        db = main.SessionLocal()
        try:
            analysis = main.create_analysis(db, user_id, "us-east-1", None)
            analysis.status = "completed"
            analysis.analysis_result = {"report": {"summary": "done"}, "resources": [], "findings": [], "warnings": []}
            db.commit()
            analysis_id = analysis.id
        finally:
            db.close()
        response = client.post(f"/api/analyses/{analysis_id}/cancel", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["analysis"]["status"] == "completed"


def test_cancellation_after_scan_prevents_later_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    main.init_db()
    db = main.SessionLocal()
    try:
        user = main.create_user(db, "cancel-stage@example.com", "hash")
        analysis = main.create_analysis(db, user.id, "us-east-1", None)
        analysis_id = analysis.id
        user_id = user.id
    finally:
        db.close()

    class CancellingScanner:
        def __init__(self, region: str, resource_group: str | None = None):
            pass

        def scan(self) -> dict[str, Any]:
            db = main.SessionLocal()
            try:
                main.cancel_analysis(db, analysis_id, "Cancelled while scan was running.")
            finally:
                db.close()
            return {"region": "us-east-1", "resources": [], "warnings": [], "errors": []}

    def should_not_run(_: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("analysis stage should not run after cancellation")

    monkeypatch.setattr(main, "AwsScanner", CancellingScanner)
    monkeypatch.setattr(main, "analyze_costs", should_not_run)

    asyncio.run(main.run_analysis_job(analysis_id, user_id, "us-east-1", None))

    db = main.SessionLocal()
    try:
        record = db.get(main.Analysis, analysis_id)
        assert record.status == "cancelled"
        assert record.analysis_result["reason"] == "Cancelled while scan was running."
    finally:
        db.close()


def test_progress_history_ttl_cleanup_is_temporary_memory_only() -> None:
    from progress import ProgressManager

    now = [1000.0]
    manager = ProgressManager(ttl_seconds=10, now=lambda: now[0])
    asyncio.run(manager.publish(1, "started", status="running"))
    now[0] = 1009.0
    assert manager.history(1)[0]["message"] == "started"
    now[0] = 1011.0
    assert manager.cleanup_expired() == 1
    assert manager.history(1) == []


def test_history_is_preserved_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    db_mod = importlib.import_module("db")
    db_mod.init_db()
    db = db_mod.SessionLocal()
    try:
        user = db_mod.create_user(db, "history@example.com", "hash")
        for index in range(55):
            db_mod.create_analysis(db, user.id, "us-east-1", f"group-{index}")
        assert db_mod.cleanup_history_retention(db) == 0
        assert db.query(db_mod.Analysis).filter(db_mod.Analysis.user_id == user.id).count() == 55
    finally:
        db.close()


def test_history_retention_is_opt_in_and_configurable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    db_mod = importlib.import_module("db")
    monkeypatch.setenv("ANALYSIS_HISTORY_RETENTION_ENABLED", "true")
    monkeypatch.setenv("ANALYSIS_HISTORY_MAX_RECORDS", "2")
    monkeypatch.delenv("ANALYSIS_HISTORY_RETENTION_DAYS", raising=False)
    db_mod.init_db()
    db = db_mod.SessionLocal()
    try:
        user = db_mod.create_user(db, "retention@example.com", "hash")
        base = db_mod.utcnow()
        ids: list[int] = []
        for index in range(4):
            analysis = db_mod.create_analysis(db, user.id, "us-east-1", None)
            analysis.created_at = base + timedelta(minutes=index)
            ids.append(analysis.id)
        db.commit()
        assert db_mod.cleanup_history_retention(db) == 2
        remaining = [row.id for row in db.query(db_mod.Analysis).order_by(db_mod.Analysis.created_at).all()]
        assert remaining == ids[-2:]
    finally:
        db.close()


def test_canonical_schema_normalizes_legacy_without_duplicate_issues() -> None:
    from report_schema import normalize_analysis_result

    result = normalize_analysis_result({
        "region": "us-east-1",
        "scan": {"resources": [{"service": "EC2", "id": "i-1", "metrics": {"low_utilization_candidate": True}}]},
        "analysis": {"summary": "legacy", "issues": [{"resource_id": "i-1"}], "confidence": {"score": 80, "label": "High"}},
    })
    assert result["schema_version"] == "2.0"
    assert "issues" not in result
    assert result["findings"][0]["resource_id"] == "i-1"
    assert result["resources"][0]["metrics"]["utilization_signal"]["assessment"] == "observation"


def test_zip_export_endpoint_contains_exact_safe_utf8_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = _fresh_app(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        token, user_id = _signup(client, "zip@example.com")
        scan_result = {
            "region": "us-east-1",
            "account_id": "277731792560",
            "identity_arn": "arn:aws:iam::277731792560:user/budgetbeagle-app",
            "resources": [
                {"service": "EC2", "id": "i-long-1234567890abcdef0", "state": "running", "type_or_sku": "t3.micro", "metrics": {"low_utilization_candidate": True}},
                {"service": "EBS", "id": "vol-0def456", "state": "available", "type_or_sku": "gp3", "metrics": {"size_gb": 8, "unattached": True}},
                {"service": "S3", "id": "demo-test-beagle", "state": "active", "type_or_sku": "bucket", "metrics": {"lifecycle_status": {"status": "unknown", "code": "AccessDenied", "permission": "s3:GetLifecycleConfiguration"}}},
            ],
            "warnings": [{"service": "S3", "resource_id": "demo-test-beagle", "code": "AccessDenied", "message": "Lifecycle unknown", "permission": "s3:GetLifecycleConfiguration", "resolution": "Add permission"}],
            "billing": {
                "status": "available",
                "service_costs_ytd": [{"name": "Amazon Elastic Compute Cloud", "amount_usd": 12.34, "display": "$12.34"}],
                "region_costs_ytd": [{"name": "us-east-1", "amount_usd": 12.34, "display": "$12.34"}],
            },
            "errors": [],
        }
        analysis_report = {
            "status": "completed_with_warnings",
            "summary": "Export test",
            "resources_scanned": 3,
            "issues_found": 1,
            "confirmed_issues": 1,
            "estimated_monthly_savings": 0.0,
            "estimated_monthly_savings_display": "$0.00/month",
            "findings": [{
                "category": "confirmed_issue", "category_label": "Confirmed issue",
                "service": "EBS",
                "resource_id": "vol-0def456",
                "issue_type": "Unattached EBS volume",
                "severity": "high",
                "confidence": "high",
                "finding_confidence": {"score": 90, "label": "High", "level": "high", "factors": []},
                "savings_confidence": {"score": 95, "label": "High", "level": "high", "factors": []},
                "estimated_monthly_savings": 0.0,
                "estimated_monthly_savings_display": "$0.00/month",
                "pricing_status": "not_applicable",
                "evidence": {"Attached": "No"},
                "recommendation": "Create a snapshot before deleting.",
                "savings_basis": "Unknown remains unknown when price is unavailable.",
                "action_risk": "Destructive. Create and verify a snapshot first.",
            }],
            "warnings": scan_result["warnings"],
            "billing": scan_result["billing"],
            "metrics": {},
            "scan_confidence": {"score": 80, "label": "High", "level": "high", "factors": []},
        }
        canonical = main.build_canonical_result(region="us-east-1", resource_group=None, scan_result=scan_result, analysis=analysis_report)
        db = main.SessionLocal()
        try:
            analysis = main.Analysis(user_id=user_id, region="us-east-1", scan_target="whole-region", resources_scanned=3, issues_found=1, estimated_savings="$0.00/month", status="completed_with_warnings", analysis_result=canonical)
            db.add(analysis)
            db.commit()
            analysis_id = analysis.id
        finally:
            db.close()

        response = client.get(f"/api/analyses/{analysis_id}/export/zip", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "report.json",
            "summary.csv",
            "resources.csv",
            "findings.csv",
            "billing-services.csv",
            "billing-regions.csv",
            "warnings.csv",
            "service-coverage.csv",
        ]
        decoded = {name: archive.read(name).decode("utf-8") for name in archive.namelist()}

    joined = "\n".join(decoded.values())
    assert "277731792560" not in joined
    assert "arn:aws:" not in joined
    assert "AKIA" not in joined
    assert "ASIA" not in joined
    assert "i-long-1234567890abcdef0" in decoded["resources.csv"]
    assert "vol-0def456" in decoded["findings.csv"]
    assert "Attached" in decoded["findings.csv"]
    assert "Create a snapshot" in decoded["findings.csv"]
    assert "Unknown remains unknown" in decoded["findings.csv"]
    assert "Amazon Elastic Compute Cloud" in decoded["billing-services.csv"]
    assert "us-east-1" in decoded["billing-regions.csv"]
    assert "s3:GetLifecycleConfiguration" in decoded["warnings.csv"]
    assert "EBS" in decoded["service-coverage.csv"]


def test_export_payload_normalizes_negative_zero_and_canonical_summary() -> None:
    from export import build_export_payload

    payload = build_export_payload({
        "id": 99,
        "status": "completed",
        "region": "ap-southeast-1",
        "scan_target": "whole-region",
        "analysis_result": {
            "report": {
                "summary": "Manual fixture",
                "resources_scanned": 3,
                "issues_found": 0,
                "confirmed_issues": 0,
                "recommendations": 1,
                "observations": 1,
                "actionable_findings": 1,
                "estimated_monthly_savings": None,
                "estimated_monthly_savings_display": "Not enough data",
            },
            "scan": {"region": "ap-southeast-1", "errors": []},
            "resources": [{"service": "EC2", "id": "i-1"}, {"service": "EBS", "id": "vol-1"}, {"service": "S3", "id": "bucket-1"}],
            "findings": [
                {"category": "recommendation", "service": "S3", "resource_id": "bucket-1", "issue_type": "S3 lifecycle policy review", "severity": "low", "confidence": "low", "estimated_monthly_savings": None, "estimated_monthly_savings_display": "Not enough data", "evidence": {"Lifecycle status": "Absent"}, "recommendation": "Review lifecycle policy.", "savings_basis": "Not enough data.", "action_risk": "No command generated."},
                {"category": "observation", "service": "EC2", "resource_id": "i-1", "issue_type": "Low EC2 CPU utilization review candidate", "severity": "low", "confidence": "low", "estimated_monthly_savings": None, "estimated_monthly_savings_display": "Not enough data", "evidence": {}, "recommendation": "Monitor.", "savings_basis": "Not enough data.", "action_risk": "No command generated."},
            ],
            "warnings": [],
            "billing": {
                "status": "available",
                "monthly_account_costs": [{"label": "May 2026", "amount_usd": -0.001, "display": "$-0.00"}],
                "service_costs_ytd": [{"name": "Amazon Elastic Compute Cloud", "amount_usd": -0.001, "display": "$-0.00"}],
                "region_costs_ytd": [{"name": "NoRegion", "amount_usd": -0.001, "display": "$-0.00"}],
            },
            "scan_confidence": {"score": 95, "label": "High", "level": "high"},
            "service_coverage": [
                {"service": "EC2", "status": "completed", "count": 1},
                {"service": "EBS", "status": "completed", "count": 1},
                {"service": "S3", "status": "completed", "count": 1},
                {"service": "RDS", "status": "no_resources", "count": 0},
                {"service": "Load Balancing", "status": "no_resources", "count": 0},
                {"service": "Elastic IP", "status": "no_resources", "count": 0},
                {"service": "NAT Gateway", "status": "no_resources", "count": 0},
            ],
        },
    })
    serialized = json.dumps(payload)
    assert payload["report"]["confirmed_issues"] == 0
    assert payload["report"]["recommendations"] == 1
    assert payload["report"]["observations"] == 1
    assert payload["report"]["actionable_findings"] == 1
    assert payload["report"]["service_coverage_summary"]["services_scanned_display"] == "7/7"
    assert "$-0.00" not in serialized
    assert "-$0.00" not in serialized
    assert "-0.00 USD" not in serialized
