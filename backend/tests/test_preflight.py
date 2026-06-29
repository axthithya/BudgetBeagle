from __future__ import annotations

import importlib
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
            "Analyzing costs with Groq...",
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
