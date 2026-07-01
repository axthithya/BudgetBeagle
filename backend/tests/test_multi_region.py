from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_scan_request_modes_and_region_validation() -> None:
    from multi_region import RegionResolutionError, normalize_scan_request
    from region_discovery import RegionDiscoveryResult

    legacy = normalize_scan_request(region="us-east-1", resource_group=None)
    assert legacy.region_mode == "single_region"
    assert legacy.requested_regions == ["us-east-1"]
    assert legacy.resolved_regions == ["us-east-1"]

    selected = normalize_scan_request(
        region=None,
        resource_group=None,
        region_mode="selected_regions",
        requested_regions=["us-west-2", "us-east-1", "us-west-2"],
    )
    assert selected.requested_regions == ["us-west-2", "us-east-1", "us-west-2"]
    assert selected.resolved_regions == ["us-east-1", "us-west-2"]

    all_regions = normalize_scan_request(
        region=None,
        resource_group=None,
        region_mode="all_enabled_regions",
        discovery=RegionDiscoveryResult(status="available", regions=["ap-south-1", "us-east-1"]),
    )
    assert all_regions.resolved_regions == ["ap-south-1", "us-east-1"]

    with pytest.raises(RegionResolutionError):
        normalize_scan_request(region=None, resource_group=None, region_mode="selected_regions", requested_regions=["not a region"])


def test_region_discovery_orders_deduplicates_and_handles_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    import region_discovery

    class FakeEc2:
        def describe_regions(self, AllRegions: bool = False) -> dict[str, Any]:
            return {"Regions": [{"RegionName": "us-west-2"}, {"RegionName": "bad region"}, {"RegionName": "us-east-1"}, {"RegionName": "us-east-1"}]}

    class FakeSession:
        def __init__(self, region_name: str | None = None):
            pass

        def client(self, service: str):
            assert service == "ec2"
            return FakeEc2()

    monkeypatch.setattr(region_discovery.boto3, "Session", FakeSession)
    result = region_discovery.discover_enabled_regions()
    assert result.status == "available"
    assert result.regions == ["us-east-1", "us-west-2"]

    class DeniedEc2:
        def describe_regions(self, AllRegions: bool = False) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret arn:aws:iam::123456789012:user/x"}}, "DescribeRegions")

    class DeniedSession(FakeSession):
        def client(self, service: str):
            return DeniedEc2()

    monkeypatch.setattr(region_discovery.boto3, "Session", DeniedSession)
    denied = region_discovery.discover_enabled_regions()
    assert denied.status == "permission_denied"
    assert denied.error is not None
    assert denied.error.permission == "ec2:DescribeRegions"
    assert "arn:aws" not in denied.error.message


def test_multi_region_concurrency_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from multi_region import ConcurrencyConfigurationError, validate_multi_region_concurrency

    assert validate_multi_region_concurrency("1") == 1
    assert validate_multi_region_concurrency("10") == 10
    with pytest.raises(ConcurrencyConfigurationError):
        validate_multi_region_concurrency("0")
    with pytest.raises(ConcurrencyConfigurationError):
        validate_multi_region_concurrency("-2")
    with pytest.raises(ConcurrencyConfigurationError):
        validate_multi_region_concurrency("99")
    with pytest.raises(ConcurrencyConfigurationError):
        validate_multi_region_concurrency("nope")


def test_multi_region_orchestrator_partial_failure_s3_once_and_billing_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import scan_orchestrator
    from multi_region import NormalizedScanRequest

    monkeypatch.setenv("MULTI_REGION_CONCURRENCY", "2")
    scanner_inits: list[tuple[str, dict[str, Any]]] = []
    s3_calls: list[list[str]] = []
    billing_calls: list[list[str]] = []
    progress: list[int] = []

    class FakeScanner:
        def __init__(self, region: str, resource_group: str | None = None, **kwargs: Any):
            self.region = region
            self.resource_group = resource_group
            self.kwargs = kwargs
            scanner_inits.append((region, kwargs))

        def scan(self) -> dict[str, Any]:
            if self.region == "us-west-2":
                raise RuntimeError("AccessDenied for test AKIA123")
            return {
                "region": self.region,
                "resource_group": self.resource_group,
                "account_id": "********1234",
                "account_id_raw": "123456789012",
                "identity_type": "iam_user",
                "identity_name": "tester",
                "resources": [{"service": "EC2", "id": f"i-{self.region}", "region": self.region, "type_or_sku": "t3.micro"}],
                "warnings": [],
                "errors": [],
            }

        def scan_s3_buckets_for_regions(self, regions: list[str]) -> dict[str, Any]:
            s3_calls.append(list(regions))
            return {
                "region": self.region,
                "account_id": "********1234",
                "account_id_raw": "123456789012",
                "resources": [{"service": "S3", "id": "bucket-east", "region": "us-east-1", "type_or_sku": "bucket"}],
                "warnings": [],
                "errors": [],
            }

    def fake_billing(session: Any, *, selected_regions: list[str], account_id: str | None, warn: Any, selected_region: str | None = None) -> dict[str, Any]:
        billing_calls.append(list(selected_regions))
        return {
            "status": "available",
            "selected_regions": selected_regions,
            "account_id": "********1234",
            "account_total_ytd_usd": 10.0,
            "selected_region_ytd_usd": 10.0,
            "monthly_account_costs": [],
            "monthly_selected_region_costs": [],
            "service_costs_ytd": [],
            "region_costs_ytd": [],
        }

    async def publish(_: str, details: dict[str, Any]) -> None:
        progress.append(int(details.get("overall_percentage", 0)))

    monkeypatch.setattr(scan_orchestrator, "scan_billing_context", fake_billing)
    request = NormalizedScanRequest(
        region_mode="selected_regions",
        requested_regions=["us-east-1", "us-west-2"],
        resolved_regions=["us-east-1", "us-west-2"],
    )

    scan_result, regional_results, partial_warnings = asyncio.run(
        scan_orchestrator.run_scan_request(request, scanner_cls=FakeScanner, publish_progress=publish)
    )

    assert [item["status"] for item in regional_results] == ["completed", "failed"]
    assert partial_warnings and partial_warnings[0]["region"] == "us-west-2"
    assert "AKIA" not in partial_warnings[0]["message"]
    assert billing_calls == [["us-east-1", "us-west-2"]]
    assert s3_calls == [["us-east-1", "us-west-2"]]
    assert all(kwargs.get("include_billing") is False for _, kwargs in scanner_inits)
    assert all(kwargs.get("scan_s3") is False for _, kwargs in scanner_inits)
    assert len(scan_result["resources"]) == 2
    assert progress == sorted(progress)
    assert max(progress) <= 100
