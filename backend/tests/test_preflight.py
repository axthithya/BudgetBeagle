from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _fresh_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'preflight.db'}")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    for module_name in ["main", "db", "auth", "ai_analyzer", "aws_scanner", "progress"]:
        sys.modules.pop(module_name, None)

    return importlib.import_module("main")


def test_env_examples_cover_backend_getenv_calls() -> None:
    env_names: set[str] = set()
    pattern = re.compile(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']")
    for path in BACKEND_DIR.glob("*.py"):
        env_names.update(pattern.findall(path.read_text()))

    root_example = (ROOT_DIR / ".env.example").read_text()
    backend_example = (BACKEND_DIR / ".env.example").read_text()

    missing = [
        name
        for name in sorted(env_names)
        if f"{name}=" not in root_example or f"{name}=" not in backend_example
    ]
    assert missing == []


def test_scanner_keeps_results_when_one_service_is_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    from aws_scanner import AwsScanner

    scanner = AwsScanner("us-east-1")
    monkeypatch.setattr(scanner, "_validate_credentials", lambda: None)
    monkeypatch.setattr(scanner, "_metric_average", lambda *args, **kwargs: 2.5)
    monkeypatch.setattr(scanner, "_scan_billing_context", lambda: {"status": "unavailable"})

    class Paginator:
        def __init__(self, pages: list[dict[str, Any]]):
            self.pages = pages

        def paginate(self, **_: Any):
            return self.pages

    class FakeEc2:
        def get_paginator(self, operation: str) -> Paginator:
            if operation == "describe_instances":
                return Paginator(
                    [
                        {
                            "Reservations": [
                                {
                                    "Instances": [
                                        {
                                            "InstanceId": "i-idle",
                                            "InstanceType": "t3.large",
                                            "State": {"Name": "running"},
                                            "Tags": [{"Key": "Name", "Value": "idle-app"}],
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                )
            if operation == "describe_volumes":
                return Paginator(
                    [
                        {
                            "Volumes": [
                                {
                                    "VolumeId": "vol-unattached",
                                    "VolumeType": "gp3",
                                    "State": "available",
                                    "Size": 100,
                                    "Tags": [],
                                }
                            ]
                        }
                    ]
                )
            if operation == "describe_nat_gateways":
                return Paginator([{"NatGateways": []}])
            raise AssertionError(operation)

        def describe_addresses(self) -> dict[str, Any]:
            return {"Addresses": [{"AllocationId": "eipalloc-unused", "PublicIp": "203.0.113.10"}]}

    class EmptyPaginatorClient:
        def get_paginator(self, _: str) -> Paginator:
            return Paginator([{}])

    class EmptyS3:
        def list_buckets(self) -> dict[str, Any]:
            return {"Buckets": []}

    def fake_client(service: str):
        if service == "ec2":
            return FakeEc2()
        if service == "rds":
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied for test"}},
                "DescribeDBInstances",
            )
        if service in {"elbv2", "elb"}:
            return EmptyPaginatorClient()
        if service == "s3":
            return EmptyS3()
        raise AssertionError(service)

    monkeypatch.setattr(scanner, "_client", fake_client)

    result = scanner.scan()

    assert [resource["id"] for resource in result["resources"]] == [
        "i-idle",
        "vol-unattached",
        "eipalloc-unused",
    ]
    assert any(error["service"] == "rds" and error["code"] == "AccessDenied" for error in result["errors"])


def test_analyze_websocket_report_flow_with_mocked_scanner_and_groq(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main = _fresh_app(monkeypatch, tmp_path)

    fake_scan_result = {
        "region": "us-east-1",
        "resource_group": None,
        "resources": [
            {
                "service": "EC2",
                "id": "i-idle",
                "name": "idle-app",
                "type_or_sku": "t3.large",
                "state": "running",
                "tags": {"Name": "idle-app"},
                "metrics": {"avg_cpu_14d": 2.5, "low_utilization_candidate": True},
            },
            {
                "service": "EBS",
                "id": "vol-unattached",
                "name": "",
                "type_or_sku": "gp3",
                "state": "available",
                "tags": {},
                "metrics": {"size_gb": 100, "unattached": True},
            },
            {
                "service": "ElasticIP",
                "id": "eipalloc-unused",
                "name": "",
                "type_or_sku": "public-ipv4",
                "state": "unassociated",
                "tags": {},
                "metrics": {"public_ip": "203.0.113.10", "unassociated": True},
            },
        ],
        "errors": [],
    }

    class FakeScanner:
        def __init__(self, region: str, resource_group: str | None = None):
            self.region = region
            self.resource_group = resource_group

        def scan(self) -> dict[str, Any]:
            assert self.region == "us-east-1"
            assert self.resource_group is None
            return fake_scan_result

    def fake_analyze_costs(scan_result: dict[str, Any]) -> dict[str, Any]:
        assert scan_result == fake_scan_result
        return {
            "summary": "Three test findings.",
            "resources_scanned": 3,
            "issues_found": 3,
            "estimated_monthly_savings": "$42.00/month",
            "issues": [
                {
                    "resource_id": "i-idle",
                    "issue_type": "Low EC2 CPU",
                    "severity": "medium",
                    "explanation": "Average CPU was 2.5%.",
                    "estimated_monthly_savings": "$20.00/month",
                    "fix_command": "aws ec2 stop-instances --instance-ids i-idle",
                },
                {
                    "resource_id": "vol-unattached",
                    "issue_type": "Unattached EBS",
                    "severity": "high",
                    "explanation": "The volume is available and unattached.",
                    "estimated_monthly_savings": "$12.00/month",
                    "fix_command": "aws ec2 delete-volume --volume-id vol-unattached",
                },
                {
                    "resource_id": "eipalloc-unused",
                    "issue_type": "Unassociated Elastic IP",
                    "severity": "low",
                    "explanation": "The Elastic IP is not associated.",
                    "estimated_monthly_savings": "$10.00/month",
                    "fix_command": "aws ec2 release-address --allocation-id eipalloc-unused",
                },
            ],
            "notes": [],
        }

    monkeypatch.setattr(main, "AwsScanner", FakeScanner)
    monkeypatch.setattr(main, "analyze_costs", fake_analyze_costs)

    with TestClient(main.app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"email": "preflight@example.com", "password": "password123"},
        )
        assert signup.status_code == 200
        token = signup.json()["token"]

        unauthorized = client.post("/api/analyze", json={"region": "us-east-1"})
        assert unauthorized.status_code == 401

        start = client.post(
            "/api/analyze",
            json={"region": "us-east-1", "resource_group": None},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert start.status_code == 200
        body = start.json()
        assert body["status"] == "queued"
        analysis_id = body["analysis_id"]

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/progress/{analysis_id}?token=not-a-jwt"):
                pass

        with client.websocket_connect(f"/ws/progress/{analysis_id}?token={token}") as websocket:
            messages = [websocket.receive_json()["message"] for _ in range(5)]

        assert messages == [
            "Scanning AWS resources in us-east-1...",
            "Pulling CloudWatch metrics...",
            "Building deterministic cost report...",
            "Storing results...",
            "Analysis complete",
        ]

        report = client.get(
            f"/api/analyses/{analysis_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert report.status_code == 200
        record = report.json()["analysis"]
        assert record["status"] == "completed"
        assert record["resources_scanned"] == 3
        assert record["issues_found"] == 3
        assert record["estimated_savings"] == "$42.00/month"

        result = record["analysis_result"]
        assert [issue["resource_id"] for issue in result["analysis"]["issues"]] == [
            "i-idle",
            "vol-unattached",
            "eipalloc-unused",
        ]

        history = client.get("/api/history", headers={"Authorization": f"Bearer {token}"})
        assert history.status_code == 200
        assert history.json()["analyses"][0]["id"] == analysis_id


# ── Prompt 10: E2E acceptance scenario ────────────────────────────────


def test_e2e_mocked_acceptance_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Full mocked scenario per Prompt 10 §12:
    - Account ID 277731792560
    - S3 lifecycle → AccessDenied
    - Cost Explorer → AccessDenied
    - EC2/EBS/S3 scans succeed
    Expected:
    - status: completed_with_warnings
    - Account masked: ********2560
    - No full account ID or ARN in response
    - Lifecycle status: unknown, no lifecycle issue
    - Cost Explorer warning present
    - Savings: Not enough data
    """
    main = _fresh_app(monkeypatch, tmp_path)

    fake_scan_result = {
        "region": "ap-southeast-1",
        "resource_group": None,
        "account_id": "********2560",
        "identity_type": "iam_user",
        "identity_name": "budgetbeagle-app",
        "resources": [
            {
                "service": "EC2",
                "id": "i-0abc123",
                "name": "test-server",
                "type_or_sku": "t3.micro",
                "state": "running",
                "metrics": {
                    "cpu_utilization": {
                        "metric_source": "CloudWatch",
                        "metric_name": "CPUUtilization",
                        "average": 0.13,
                        "minimum": 0.01,
                        "maximum": 0.5,
                        "datapoint_count": 5,
                        "requested_start": "2026-06-15T00:00:00+00:00",
                        "requested_end": "2026-06-29T00:00:00+00:00",
                        "requested_window_days": 14,
                        "actual_start": "2026-06-29T07:00:00+00:00",
                        "actual_end": "2026-06-29T12:00:00+00:00",
                        "actual_duration_hours": 5,
                        "instance_launch_time": "2026-06-29T06:00:00+00:00",
                        "status": "present",
                    },
                    "launch_time": "2026-06-29T06:00:00+00:00",
                },
            },
            {
                "service": "EBS",
                "id": "vol-0def456",
                "name": "",
                "type_or_sku": "gp3",
                "state": "in-use",
                "metrics": {
                    "size_gb": 8,
                    "iops": 3000,
                    "throughput_mibps": 125,
                    "attachment_count": 1,
                    "unattached": False,
                },
            },
            {
                "service": "S3",
                "id": "demo-test-beagle",
                "name": "demo-test-beagle",
                "type_or_sku": "bucket",
                "state": "active",
                "metrics": {
                    "lifecycle_status": {
                        "status": "unknown",
                        "code": "AccessDenied",
                        "message": "Lifecycle configuration could not be verified.",
                        "permission": "s3:GetLifecycleConfiguration",
                    },
                    "bucket_size_bytes": None,
                    "object_count": None,
                },
            },
        ],
        "errors": [],
        "warnings": [
            {
                "service": "S3",
                "resource_id": "demo-test-beagle",
                "code": "AccessDenied",
                "permission": "s3:GetLifecycleConfiguration",
                "message": "Lifecycle configuration could not be verified.",
                "title": "Lifecycle configuration could not be verified",
                "resolution": "Add the optional read-only permission and run the scan again.",
                "severity": "warning",
                "operation": "GetBucketLifecycleConfiguration",
            },
            {
                "service": "Cost Explorer",
                "resource_id": "",
                "code": "AccessDeniedException",
                "permission": "ce:GetCostAndUsage",
                "message": "Cost Explorer data could not be collected.",
                "title": "Billing data unavailable",
                "resolution": "Add the optional Cost Explorer read permission to enable billing totals.",
                "severity": "warning",
                "operation": "GetCostAndUsage",
            },
        ],
        "billing": {
            "status": "unavailable",
            "error": {"code": "AccessDeniedException", "message": "Cost Explorer data could not be collected.", "permission": "ce:GetCostAndUsage"},
        },
    }

    class FakeScanner:
        def __init__(self, region: str, resource_group: str | None = None):
            self.region = region
            self.resource_group = resource_group

        def scan(self) -> dict[str, Any]:
            return fake_scan_result

    monkeypatch.setattr(main, "AwsScanner", FakeScanner)
    monkeypatch.setattr(main, "analyze_costs", lambda sr, **kw: __import__("cost_rules").build_cost_report(sr))

    with TestClient(main.app) as client:
        signup = client.post("/api/auth/signup", json={"email": "e2e@example.com", "password": "password123"})
        assert signup.status_code == 200
        token = signup.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        start = client.post("/api/analyze", json={"region": "ap-southeast-1"}, headers=headers)
        assert start.status_code == 200
        analysis_id = start.json()["analysis_id"]

        with client.websocket_connect(f"/ws/progress/{analysis_id}?token={token}") as ws:
            msgs = [ws.receive_json()["message"] for _ in range(5)]
        assert msgs[-1] == "Analysis complete"

        report = client.get(f"/api/analyses/{analysis_id}", headers=headers)
        assert report.status_code == 200
        record = report.json()["analysis"]
        result = record["analysis_result"]
        analysis = result["analysis"]

        # 1. Status
        assert record["status"] == "completed_with_warnings"

        # 2. Account masking
        scan = result["scan"]
        assert scan.get("account_id") in ("********2560", None)
        serialized = json.dumps(result)
        assert "277731792560" not in serialized  # No full account ID

        # 3. No full IAM ARN
        assert "arn:aws:" not in serialized

        # 4. S3 lifecycle
        s3_resources = [r for r in scan["resources"] if r.get("service") == "S3"]
        assert len(s3_resources) == 1
        lifecycle = s3_resources[0]["metrics"]["lifecycle_status"]
        assert lifecycle["status"] == "unknown"
        s3_findings = [f for f in analysis.get("findings", []) if f.get("service") == "S3"]
        assert len(s3_findings) == 0  # No lifecycle issue from unknown

        # 5. Cost Explorer warning present
        ce_warnings = [w for w in analysis.get("warnings", []) if "Cost Explorer" in str(w.get("service", ""))]
        assert len(ce_warnings) > 0

        # 6. Resource scan completed
        assert record["resources_scanned"] == 3

        # 7. Savings
        assert analysis.get("estimated_monthly_savings") is None or analysis.get("estimated_monthly_savings_display") == "Not enough data"

        # 8. No missing_lifecycle_policy: No in serialized output
        assert "missing_lifecycle_policy" not in serialized

        # 9. No AKIA/ASIA access keys
        assert "AKIA" not in serialized
        assert "ASIA" not in serialized


def test_historical_reports_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reports with old fields must be sanitized before rendering."""
    main = _fresh_app(monkeypatch, tmp_path)

    # Manually insert a record with old-style fields
    with TestClient(main.app) as client:
        signup = client.post("/api/auth/signup", json={"email": "hist@example.com", "password": "password123"})
        token = signup.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        db_mod = __import__("db")
        db = db_mod.SessionLocal()
        try:
            analysis = db_mod.Analysis(
                user_id=signup.json()["user"]["id"],
                region="us-east-1",
                scan_target="whole-region",
                resources_scanned=1,
                issues_found=0,
                estimated_savings="Not enough data",
                status="completed",
                analysis_result={
                    "region": "us-east-1",
                    "scan": {
                        "account_id": "277731792560",
                        "resources": [{
                            "service": "S3",
                            "id": "old-bucket",
                            "metrics": {
                                "has_lifecycle_policy": None,
                                "missing_lifecycle_policy": False,
                            },
                        }],
                        "errors": [{"message": "User arn:aws:iam::277731792560:user/test denied"}],
                    },
                    "analysis": {"summary": "Old report", "issues": [], "findings": []},
                },
            )
            db.add(analysis)
            db.commit()
            aid = analysis.id
        finally:
            db.close()

        resp = client.get(f"/api/analyses/{aid}", headers=headers)
        assert resp.status_code == 200
        data = json.dumps(resp.json())

        # Must not expose full account ID
        assert "277731792560" not in data
        # Must not expose full ARN
        assert "arn:aws:iam" not in data
        # Must not have old lifecycle booleans
        assert "has_lifecycle_policy" not in data
        assert "missing_lifecycle_policy" not in data
