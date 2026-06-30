from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cost_rules import build_cost_report, build_gp3_modify_command
from pricing import PricingQuote


def _scan(resources: list[dict[str, Any]], warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"region": "ap-southeast-1", "resources": resources, "warnings": warnings or [], "errors": []}


def _ebs(volume_id: str = "vol-gp3", state: str = "in-use", iops: int = 3000, throughput: int = 125) -> dict[str, Any]:
    return {
        "service": "EBS",
        "id": volume_id,
        "type_or_sku": "gp3",
        "state": state,
        "metrics": {
            "size_gb": 8,
            "iops": iops,
            "throughput_mibps": throughput,
            "unattached": state == "available",
        },
    }


def _s3(status: str, object_count: int | None = None, size_bytes: int | None = None) -> dict[str, Any]:
    lifecycle: dict[str, Any] = {"status": status}
    if status == "unknown":
        lifecycle.update({"code": "AccessDenied", "permission": "s3:GetLifecycleConfiguration"})
    return {
        "service": "S3",
        "id": "empty-bucket",
        "type_or_sku": "bucket",
        "state": "active",
        "metrics": {
            "lifecycle_status": lifecycle,
            "object_count": object_count,
            "bucket_size_bytes": size_bytes,
        },
    }


def _cpu(avg: float | None, datapoints: int, hours: float, launch: str = "2026-06-01T00:00:00+00:00") -> dict[str, Any]:
    return {
        "metric_source": "CloudWatch",
        "metric_name": "CPUUtilization",
        "average": avg,
        "minimum": avg,
        "maximum": avg,
        "datapoint_count": datapoints,
        "requested_start": "2026-06-15T00:00:00+00:00",
        "requested_end": "2026-06-29T00:00:00+00:00",
        "requested_window_days": 14,
        "actual_start": "2026-06-28T10:00:00+00:00" if datapoints else None,
        "actual_end": "2026-06-28T12:00:00+00:00" if datapoints else None,
        "actual_duration_hours": hours,
        "instance_launch_time": launch,
    }


def _ec2(cpu: dict[str, Any], instance_id: str = "i-low") -> dict[str, Any]:
    return {
        "service": "EC2",
        "id": instance_id,
        "type_or_sku": "t3.micro",
        "state": "running",
        "metrics": {"cpu_utilization": cpu, "launch_time": cpu.get("instance_launch_time")},
    }


class StaticPrice:
    def __init__(self, quote: PricingQuote):
        self.quote = quote
        self.calls: list[dict[str, Any]] = []

    def quote_ec2_on_demand(self, **kwargs: Any) -> PricingQuote:
        self.calls.append(kwargs)
        return self.quote


def _verified_price(region: str = "ap-southeast-1", hourly: float = 0.0128) -> PricingQuote:
    return PricingQuote("verified", hourly, "test pricing", f"{region} Linux On-Demand test price", region, "Linux", "Shared")


def _missing_price(region: str = "ap-southeast-1") -> PricingQuote:
    return PricingQuote("unavailable", None, None, "Current regional EC2 price could not be verified.", region, "Linux", "Shared")


def test_default_gp3_baseline_is_not_over_provisioned() -> None:
    report = build_cost_report(_scan([_ebs(iops=3000, throughput=125)]))
    assert [item for item in report["findings"] if item["service"] == "EBS"] == []


def test_gp3_commands_never_specify_fewer_than_3000_iops() -> None:
    assert build_gp3_modify_command(region="ap-southeast-1", volume_id="vol-1", target_iops=300, target_throughput_mibps=125) is None
    command = build_gp3_modify_command(region="ap-southeast-1", volume_id="vol-1", target_iops=3000, target_throughput_mibps=125)
    assert command is not None
    assert "--iops 3000" in command["text"]


def test_additional_gp3_iops_are_only_calculated_above_3000() -> None:
    report = build_cost_report(_scan([_ebs(iops=6000, throughput=125)]))
    ebs = report["findings"][0]
    assert ebs["evidence"]["Additional IOPS"] == 3000
    assert "--iops 3000" in ebs["command"]["text"]


def test_additional_gp3_throughput_is_only_calculated_above_125() -> None:
    report = build_cost_report(_scan([_ebs(iops=3000, throughput=250)]))
    ebs = report["findings"][0]
    assert ebs["evidence"]["Additional throughput"] == "125 MiB/s"
    assert "--throughput 125" in ebs["command"]["text"]


def test_unattached_gp3_volume_creates_unused_volume_issue() -> None:
    report = build_cost_report(_scan([_ebs(state="available")]))
    assert report["confirmed_issues"] == 1
    assert report["findings"][0]["issue_type"] == "Unattached EBS volume"
    assert report["findings"][0]["command"]["risk"] == "destructive"


def test_s3_lifecycle_status_values_from_scanner() -> None:
    from aws_scanner import AwsScanner

    scanner = AwsScanner("ap-southeast-1")

    class Present:
        def get_bucket_lifecycle_configuration(self, Bucket: str) -> dict[str, Any]:
            return {"Rules": [{"Status": "Enabled"}]}

    class Absent:
        def get_bucket_lifecycle_configuration(self, Bucket: str) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "NoSuchLifecycleConfiguration", "Message": "none"}}, "GetBucketLifecycleConfiguration")

    class Denied:
        def get_bucket_lifecycle_configuration(self, Bucket: str) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetBucketLifecycleConfiguration")

    assert scanner._bucket_lifecycle_status(Present(), "bucket")["status"] == "present"
    assert scanner._bucket_lifecycle_status(Absent(), "bucket")["status"] == "absent"
    denied = scanner._bucket_lifecycle_status(Denied(), "bucket")
    assert denied["status"] == "unknown"
    assert scanner.warnings[-1]["permission"] == "s3:GetLifecycleConfiguration"


def test_unknown_lifecycle_never_creates_missing_lifecycle_issue() -> None:
    report = build_cost_report(_scan([_s3("unknown", object_count=0, size_bytes=0)]))
    assert report["status"] == "completed_with_warnings"
    assert report["findings"] == []
    assert report["warnings"][0]["service"] == "S3"


def test_empty_s3_bucket_produces_zero_savings_without_fake_growth() -> None:
    report = build_cost_report(_scan([_s3("absent", object_count=0, size_bytes=0)]))
    finding = report["findings"][0]
    assert finding["estimated_monthly_savings"] == 0.0
    assert finding["estimated_monthly_savings_display"] == "$0.00/month"
    serialized = json.dumps(report).lower()
    assert "100 gb" not in serialized
    assert ("modest " + "data growth") not in serialized


def test_ec2_with_no_metrics_is_not_idle() -> None:
    report = build_cost_report(_scan([_ec2(_cpu(None, datapoints=0, hours=0))]))
    assert report["findings"] == []


def test_recently_launched_ec2_does_not_claim_14_days_of_evidence() -> None:
    cpu = _cpu(0.13, datapoints=8, hours=2, launch="2026-06-28T09:00:00+00:00")
    report = build_cost_report(_scan([_ec2(cpu)]), pricing_resolver=StaticPrice(_missing_price()))
    finding = report["findings"][0]
    assert finding["category"] == "observation"
    assert finding["evidence"]["Requested analysis window"] == "14 days"
    assert finding["evidence"]["Actual covered duration"] == "2.0 hours"
    assert "over the last 14 days" not in finding["explanation"]


def test_low_cpu_with_insufficient_datapoints_is_low_confidence_observation() -> None:
    report = build_cost_report(_scan([_ec2(_cpu(0.13, datapoints=8, hours=2))]), pricing_resolver=StaticPrice(_missing_price()))
    finding = report["findings"][0]
    assert finding["category"] == "observation"
    assert finding["confidence"] == "low"
    assert finding["command"] is None


def test_low_cpu_with_sufficient_datapoints_creates_review_recommendation() -> None:
    report = build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=StaticPrice(_verified_price()))
    finding = report["findings"][0]
    assert finding["category"] == "recommendation"
    assert finding["confidence"] == "medium"
    assert finding["command"]["text"].startswith("aws ec2 stop-instances")
    assert "downtime" in finding["action_risk"]


def test_ec2_pricing_is_tied_to_selected_region() -> None:
    resolver = StaticPrice(_verified_price("ap-southeast-1"))
    build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=resolver)
    assert resolver.calls[0]["region"] == "ap-southeast-1"
    assert resolver.calls[0]["instance_type"] == "t3.micro"


def test_missing_ec2_pricing_returns_null_savings() -> None:
    report = build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=StaticPrice(_missing_price()))
    finding = report["findings"][0]
    assert finding["pricing_status"] == "unavailable"
    assert finding["estimated_monthly_savings"] is None
    assert finding["maximum_monthly_avoidable_cost_usd"] is None


def test_groq_cannot_modify_deterministic_savings_or_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_analyzer = importlib.import_module("ai_analyzer")
    report = build_cost_report(_scan([_s3("absent", object_count=0, size_bytes=0)]))
    finding_id = report["findings"][0]["id"]

    content = json.dumps(
        {
            "summary": "AI summary",
            "finding_explanations": [
                {
                    "finding_id": finding_id,
                    "explanation": "Clearer wording.",
                    "estimated_monthly_savings": 999,
                    "evidence": {"Stored bytes": 999999},
                }
            ],
        }
    )

    class FakeGroq:
        def __init__(self, api_key: str):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])))

    monkeypatch.setenv("GROQ_API_KEY", "fake")
    monkeypatch.setattr(ai_analyzer, "Groq", FakeGroq)
    analyzed = ai_analyzer.analyze_costs(_scan([_s3("absent", object_count=0, size_bytes=0)]), use_groq=True)
    finding = analyzed["findings"][0]
    assert finding["estimated_monthly_savings"] == 0.0
    assert finding["evidence"]["Stored bytes"] == 0
    assert finding["ai_explanation"] == "Clearer wording."


def test_invalid_groq_response_does_not_fail_report(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_analyzer = importlib.import_module("ai_analyzer")

    class FakeGroq:
        def __init__(self, api_key: str):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])))

    monkeypatch.setenv("GROQ_API_KEY", "fake")
    monkeypatch.setattr(ai_analyzer, "Groq", FakeGroq)
    analyzed = ai_analyzer.analyze_costs(_scan([_s3("absent", object_count=0, size_bytes=0)]), use_groq=True)
    assert analyzed["findings"][0]["estimated_monthly_savings"] == 0.0
    assert "AI explanation was unavailable" in analyzed["notes"][0]


def test_total_savings_excludes_unknown_and_unsupported_estimates() -> None:
    report = build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=StaticPrice(_missing_price()))
    assert report["estimated_monthly_savings"] is None
    assert report["estimated_monthly_savings_display"] == "Not enough data"


def test_real_scan_regression_scenario_is_covered() -> None:
    report = build_cost_report(
        _scan(
            [
                _ec2(_cpu(0.13, datapoints=8, hours=2), instance_id="i-real"),
                _ebs("vol-real", state="in-use", iops=3000, throughput=125),
                _s3("unknown", object_count=0, size_bytes=0),
            ],
            warnings=[
                {
                    "service": "S3",
                    "resource_id": "empty-bucket",
                    "code": "AccessDenied",
                    "permission": "s3:GetLifecycleConfiguration",
                    "message": "BudgetBeagle could not verify the bucket lifecycle configuration because the IAM identity lacks permission.",
                }
            ],
        ),
        pricing_resolver=StaticPrice(_missing_price()),
    )

    assert report["resources_scanned"] == 3
    assert report["confirmed_issues"] == 0
    assert [item for item in report["findings"] if item["service"] == "EBS"] == []
    assert [item for item in report["findings"] if item["service"] == "S3"] == []
    assert len(report["warnings"]) == 1
    assert report["estimated_monthly_savings_display"] == "Not enough data"
    assert report["status"] == "completed_with_warnings"


def test_report_contains_display_values_for_frontend() -> None:
    report = build_cost_report(_scan([_s3("absent", object_count=0, size_bytes=0)]))
    assert report["findings"][0]["estimated_monthly_savings_display"] == "$0.00/month"
    report = build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=StaticPrice(_missing_price()))
    assert report["findings"][0]["estimated_monthly_savings_display"] == "Not enough data"


def test_billing_context_feeds_report_metrics_and_confidence() -> None:
    billing = {
        "status": "available",
        "account_total_ytd_usd": 18.45,
        "selected_region_ytd_usd": 0.0,
        "monthly_account_costs": [
            {"label": "Jan 2026", "amount_usd": 5.27, "display": "$5.27"},
            {"label": "Feb 2026", "amount_usd": 3.14, "display": "$3.14"},
            {"label": "Mar 2026", "amount_usd": 3.14, "display": "$3.14"},
            {"label": "Apr 2026", "amount_usd": 3.14, "display": "$3.14"},
            {"label": "May 2026", "amount_usd": 3.14, "display": "$3.14"},
            {"label": "Jun 2026", "amount_usd": 0.62, "display": "$0.62"},
        ],
        "service_costs_ytd": [{"name": "EC2 - Other", "amount_usd": 15.38, "display": "$15.38"}],
        "region_costs_ytd": [{"name": "ap-southeast-1", "amount_usd": 16.77, "display": "$16.77"}],
        "insights": [{"type": "no_spend_in_selected_region", "title": "No spend in this region", "severity": "medium", "message": "No regional spend.", "regions": []}],
    }
    report = build_cost_report({"region": "ap-south-1", "resources": [], "warnings": [], "errors": [], "billing": billing})

    assert report["billing"] == billing
    assert report["metrics"]["account_total_ytd_display"] == "$18.45"
    assert report["metrics"]["selected_region_ytd_display"] == "$0.00"
    assert report["metrics"]["monthly_account_average_display"] == "$3.08/month"
    assert report["scan_confidence"]["score"] == 95


def test_cost_explorer_access_denied_produces_warning() -> None:
    from billing import scan_billing_context

    warnings: list[dict[str, str | None]] = []

    class FakeSession:
        def client(self, service: str, region_name: str | None = None):
            assert service == "ce"
            assert region_name == "us-east-1"
            return self

        def get_cost_and_usage(self, **_: Any) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetCostAndUsage")

    def warn(service: str, resource_id: str | None, code: str, message: str, permission: str | None = None) -> None:
        warnings.append({"service": service, "resource_id": resource_id, "code": code, "message": message, "permission": permission})

    billing = scan_billing_context(FakeSession(), selected_region="ap-south-1", account_id="123456789012", warn=warn)

    assert billing["status"] == "unavailable"
    assert billing["error"]["permission"] == "ce:GetCostAndUsage"
    assert warnings == [
        {
            "service": "Cost Explorer",
            "resource_id": None,
            "code": "AccessDeniedException",
            "message": "Cost Explorer data could not be collected.",
            "permission": "ce:GetCostAndUsage",
        }
    ]


# ── New tests for prompt 10 ──────────────────────────────────────────────


def test_confidence_includes_explainable_factors() -> None:
    """Confidence must include a 'factors' list with named entries."""
    report = build_cost_report(
        _scan(
            [_ec2(_cpu(0.13, datapoints=5, hours=5))],
            warnings=[{
                "service": "S3",
                "resource_id": "demo-bucket",
                "code": "AccessDenied",
                "message": "Lifecycle check failed.",
                "permission": "s3:GetLifecycleConfiguration",
            }],
        ),
        pricing_resolver=StaticPrice(_missing_price()),
    )
    confidence = report["scan_confidence"]
    assert "score" in confidence
    assert "factors" in confidence
    assert isinstance(confidence["factors"], list)
    assert len(confidence["factors"]) > 0
    factor_names = [f["name"] for f in confidence["factors"]]
    assert any("warning" in name.lower() for name in factor_names)
    for factor in confidence["factors"]:
        assert "name" in factor
        assert "effect" in factor
        assert "reason" in factor
        assert factor["effect"] in ("positive", "negative", "neutral")


def test_confidence_level_field_present() -> None:
    report = build_cost_report(_scan([]))
    assert "level" in report["scan_confidence"]
    assert report["scan_confidence"]["level"] in ("high", "medium", "low")


def test_confidence_model_separates_scan_finding_and_savings_confidence() -> None:
    unknown_report = build_cost_report(_scan([_ec2(_cpu(1.5, datapoints=48, hours=48))]), pricing_resolver=StaticPrice(_missing_price()))
    unknown_finding = unknown_report["findings"][0]
    assert "scan_confidence" in unknown_report
    assert "finding_confidence" in unknown_finding
    assert "savings_confidence" not in unknown_finding
    assert unknown_report["savings_confidence"]["level"] == "not_applicable"

    numeric_report = build_cost_report(_scan([_s3("absent", object_count=0, size_bytes=0)]))
    numeric_finding = numeric_report["findings"][0]
    assert numeric_finding["estimated_monthly_savings"] == 0.0
    assert numeric_finding["savings_confidence"]["level"] == "high"
    assert numeric_report["savings_confidence"]["level"] == "high"


def test_warnings_have_structured_fields() -> None:
    """All warnings must include title, resolution, and severity."""
    report = build_cost_report(
        _scan(
            [_s3("unknown", object_count=0, size_bytes=0)],
            warnings=[{
                "service": "S3",
                "resource_id": "demo-bucket",
                "code": "AccessDenied",
                "message": "Lifecycle configuration could not be verified.",
                "permission": "s3:GetLifecycleConfiguration",
                "title": "Lifecycle configuration could not be verified",
                "resolution": "Add the optional read-only permission and run the scan again.",
                "severity": "warning",
            }],
        )
    )
    for warning in report["warnings"]:
        assert "title" in warning or "service" in warning
        assert "severity" in warning or "code" in warning


def test_s3_unknown_lifecycle_never_displays_missing_no() -> None:
    """Lifecycle unknown must never show 'missing_lifecycle_policy: No'."""
    report = build_cost_report(_scan([_s3("unknown", object_count=0, size_bytes=0)]))
    serialized = json.dumps(report)
    assert "missing_lifecycle_policy" not in serialized
    assert report["findings"] == []  # No findings from unknown status


def test_cost_explorer_access_denied_does_not_fail_resource_scan() -> None:
    """Cost Explorer denial must not prevent resources from being scanned."""
    billing = {
        "status": "unavailable",
        "error": {"code": "AccessDeniedException", "message": "denied", "permission": "ce:GetCostAndUsage"},
    }
    report = build_cost_report({
        "region": "ap-southeast-1",
        "resources": [_ebs(state="available")],
        "warnings": [],
        "errors": [],
        "billing": billing,
    })
    assert report["resources_scanned"] == 1
    assert report["confirmed_issues"] == 1  # Unattached EBS volume


def test_no_duplicate_warning_cards() -> None:
    """Same warning should not appear as both scanner warning and cost_rules warning."""
    warnings = [{
        "service": "S3",
        "resource_id": "demo-bucket",
        "code": "AccessDenied",
        "message": "denied",
        "permission": "s3:GetLifecycleConfiguration",
    }]
    report = build_cost_report(_scan([_s3("unknown")], warnings=warnings))
    s3_warnings = [w for w in report["warnings"] if w.get("service") == "S3" and w.get("resource_id") == "demo-bucket"]
    # At most 1 unique S3/demo-bucket/AccessDenied warning
    codes = [(w.get("service"), w.get("resource_id"), w.get("code")) for w in s3_warnings]
    assert len(set(codes)) <= 1, f"Duplicate warnings found: {codes}"


def test_completed_with_warnings_status_when_optional_checks_fail() -> None:
    warnings = [{
        "service": "Cost Explorer",
        "resource_id": "",
        "code": "AccessDenied",
        "message": "denied",
    }]
    report = build_cost_report(_scan([], warnings=warnings))
    assert report["status"] == "completed_with_warnings"


def test_lifecycle_status_without_dict_defaults_to_unknown() -> None:
    """When lifecycle_status is missing entirely, _lifecycle_status returns unknown."""
    from cost_rules import _lifecycle_status
    assert _lifecycle_status({}) == "unknown"
    assert _lifecycle_status({"lifecycle_status": "present"}) == "present"
    assert _lifecycle_status({"lifecycle_status": "absent"}) == "absent"
    assert _lifecycle_status({"lifecycle_status": {"status": "unknown"}}) == "unknown"


def _manual_regression_fixture() -> dict[str, Any]:
    return {
        "region": "ap-southeast-1",
        "resources": [
            _ec2(_cpu(0.13, datapoints=22, hours=22), instance_id="i-ap-southeast-1-manual"),
            _ebs("vol-ap-southeast-1-manual", state="in-use", iops=3000, throughput=125),
            _s3("absent", object_count=None, size_bytes=None),
        ],
        "warnings": [],
        "errors": [],
        "service_coverage": [
            {"service": "EC2", "status": "completed", "count": 1},
            {"service": "EBS", "status": "completed", "count": 1},
            {"service": "S3", "status": "completed", "count": 1},
            {"service": "RDS", "status": "no_resources", "count": 0},
            {"service": "Load Balancing", "status": "no_resources", "count": 0},
            {"service": "Elastic IP", "status": "no_resources", "count": 0},
            {"service": "NAT Gateway", "status": "no_resources", "count": 0},
        ],
        "billing": {
            "status": "available",
            "account_total_ytd_usd": -0.001,
            "selected_region_ytd_usd": 0.001,
            "monthly_account_costs": [{"label": "May 2026", "amount_usd": -0.001, "display": "$-0.00"}],
            "service_costs_ytd": [
                {"name": "Amazon Simple Storage Service", "amount_usd": 0.0, "display": "$0.00"},
                {"name": "Amazon Elastic Compute Cloud", "amount_usd": -0.001, "display": "$-0.00"},
            ],
            "region_costs_ytd": [{"name": "NoRegion", "amount_usd": -0.001, "display": "$-0.00"}],
        },
    }


def test_manual_fresh_clone_fixture_has_canonical_counts_coverage_confidence_and_money() -> None:
    report = build_cost_report(_manual_regression_fixture(), pricing_resolver=StaticPrice(_missing_price()))

    assert report["resources_scanned"] == 3
    assert report["confirmed_issues"] == 0
    assert report["recommendations"] == 1
    assert report["observations"] == 1
    assert report["actionable_findings"] == 1
    assert report["service_coverage_summary"]["services_scanned_display"] == "7/7"
    assert report["service_coverage_summary"]["services_containing_resources_display"] == "3/7"
    assert report["service_coverage_summary"]["resources_discovered"] == 3
    assert report["scan_confidence"]["level"] == "high"
    assert {item["category"] for item in report["findings"]} == {"observation", "recommendation"}
    assert all(item["finding_confidence"]["level"] == "low" for item in report["findings"])
    assert report["savings_confidence"]["level"] == "not_applicable"
    assert report["estimated_monthly_savings_display"] == "Not enough data"
    serialized = json.dumps(report)
    assert "$-0.00" not in serialized
    assert "-$0.00" not in serialized
    assert "-0.00 USD" not in serialized
    assert report["billing"]["region_costs_ytd"][0]["name"] == "Global / No Region"


def test_service_coverage_counts_scan_completion_separately_from_resources() -> None:
    from report_schema import build_service_coverage, coverage_summary

    explicit = [
        {"service": "EC2", "status": "completed", "count": 1},
        {"service": "EBS", "status": "completed", "count": 1},
        {"service": "S3", "status": "completed", "count": 1},
        {"service": "RDS", "status": "no_resources", "count": 0},
        {"service": "Load Balancing", "status": "no_resources", "count": 0},
        {"service": "Elastic IP", "status": "no_resources", "count": 0},
        {"service": "NAT Gateway", "status": "no_resources", "count": 0},
    ]
    summary = coverage_summary(build_service_coverage([], [], [], explicit))
    assert summary["services_scanned"] == 7
    assert summary["services_containing_resources"] == 3

    failed = [*explicit[:-1], {"service": "NAT Gateway", "status": "failed", "count": 0}]
    summary = coverage_summary(build_service_coverage([], [], [], failed))
    assert summary["services_scanned"] == 6
    assert summary["failed_services"] == 1

    warning = [{"service": "S3", "status": "completed_with_warnings", "count": 0}]
    summary = coverage_summary(build_service_coverage([], [], [], warning))
    assert summary["services_scanned"] == 7

    zero = [{**item, "count": 0, "status": "no_resources"} for item in explicit]
    summary = coverage_summary(build_service_coverage([], [], [], zero))
    assert summary["services_scanned"] == 7
    assert summary["services_containing_resources"] == 0
    assert summary["resources_discovered"] == 0


def test_s3_absent_lifecycle_recommendation_remains_evidence_first() -> None:
    report = build_cost_report(_scan([_s3("absent", object_count=None, size_bytes=None)]))
    finding = report["findings"][0]
    assert finding["category"] == "recommendation"
    assert finding["evidence"]["Lifecycle status"] == "Absent"
    assert finding["evidence"]["Stored bytes"] == "Unknown"
    assert finding["evidence"]["Object count"] == "Unknown"
    assert finding["estimated_monthly_savings"] is None
    assert "savings_confidence" not in finding
    assert finding["command"] is None
    assert report["confirmed_issues"] == 0
