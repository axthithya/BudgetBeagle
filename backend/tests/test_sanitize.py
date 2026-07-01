"""Tests for the sanitize module — masking, pattern detection, and report cleanup."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sanitize import (
    build_structured_warning,
    contains_sensitive_patterns,
    mask_account_id,
    mask_arn,
    parse_identity,
    sanitize_report,
    scrub_sensitive_text,
)


# ── 1. Account ID masking ──────────────────────────────────────────────

class TestMaskAccountId:
    def test_masks_to_final_four_digits(self) -> None:
        assert mask_account_id("277731792560") == "********2560"

    def test_masks_short_ids(self) -> None:
        assert mask_account_id("1234") == "********1234"

    def test_handles_none(self) -> None:
        assert mask_account_id(None) == "Unknown"

    def test_handles_empty(self) -> None:
        assert mask_account_id("") == "Unknown"


# ── 2. ARN masking ──────────────────────────────────────────────────────

class TestMaskArn:
    def test_iam_user(self) -> None:
        assert mask_arn("arn:aws:iam::277731792560:user/budgetbeagle-app") == "IAM user: budgetbeagle-app"

    def test_iam_role(self) -> None:
        assert mask_arn("arn:aws:iam::277731792560:role/BudgetBeagleRole") == "IAM role: BudgetBeagleRole"

    def test_assumed_role(self) -> None:
        result = mask_arn("arn:aws:sts::277731792560:assumed-role/MyRole/session")
        assert result == "IAM role: MyRole"

    def test_root(self) -> None:
        assert mask_arn("arn:aws:iam::277731792560:root") == "AWS root account"

    def test_none(self) -> None:
        assert mask_arn(None) == "Unknown identity"

    def test_non_arn_string(self) -> None:
        assert mask_arn("not-an-arn") == "Unknown identity"


# ── 3. Identity parsing ────────────────────────────────────────────────

class TestParseIdentity:
    def test_iam_user(self) -> None:
        result = parse_identity("arn:aws:iam::277731792560:user/budgetbeagle-app")
        assert result == {"identity_type": "iam_user", "identity_name": "budgetbeagle-app"}

    def test_iam_role(self) -> None:
        result = parse_identity("arn:aws:iam::277731792560:role/BudgetBeagleRole")
        assert result == {"identity_type": "iam_role", "identity_name": "BudgetBeagleRole"}

    def test_none_returns_unknown(self) -> None:
        result = parse_identity(None)
        assert result["identity_type"] == "unknown"


# ── 4. Sensitive pattern detection ──────────────────────────────────────

class TestContainsSensitivePatterns:
    def test_detects_full_account_id(self) -> None:
        assert contains_sensitive_patterns("Account: 277731792560") is True

    def test_detects_access_key(self) -> None:
        assert contains_sensitive_patterns("Key: AKIAIOSFODNN7EXAMPLE") is True

    def test_detects_temporary_access_key(self) -> None:
        assert contains_sensitive_patterns("Key: ASIAIOSFODNN7EXAMPLE") is True

    def test_detects_full_arn(self) -> None:
        assert contains_sensitive_patterns("arn:aws:iam::277731792560:user/test") is True

    def test_safe_text_passes(self) -> None:
        assert contains_sensitive_patterns("Lifecycle policy: Unknown") is False

    def test_empty_string(self) -> None:
        assert contains_sensitive_patterns("") is False

    def test_resource_ids_are_not_flagged(self) -> None:
        # Instance IDs, volume IDs etc. should not be treated as sensitive
        assert contains_sensitive_patterns("i-1234567890abcdef0") is False
        assert contains_sensitive_patterns("vol-0a1b2c3d4e5f6g7h8") is False

    def test_detects_secret_key_pattern(self) -> None:
        assert contains_sensitive_patterns('secret_access_key="wJalrXUtnFEMI"') is True

    def test_detects_session_token_pattern(self) -> None:
        assert contains_sensitive_patterns('session_token=FwoGZX...') is True


# ── 5. Scrub sensitive text ─────────────────────────────────────────────

class TestScrubSensitiveText:
    def test_scrubs_access_key(self) -> None:
        result = scrub_sensitive_text("Error with key AKIAIOSFODNN7EXAMPLE in request")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED_KEY]" in result

    def test_scrubs_arn(self) -> None:
        result = scrub_sensitive_text("User arn:aws:iam::277731792560:user/test denied")
        assert "277731792560" not in result
        assert "[REDACTED_ARN]" in result

    def test_preserves_safe_text(self) -> None:
        text = "Lifecycle configuration could not be verified."
        assert scrub_sensitive_text(text) == text


# ── 6. Structured warning builder ──────────────────────────────────────

class TestBuildStructuredWarning:
    def test_s3_lifecycle_warning(self) -> None:
        warning = build_structured_warning(
            service="S3",
            resource_id="demo-test-beagle",
            operation="GetBucketLifecycleConfiguration",
            code="AccessDenied",
            permission="s3:GetLifecycleConfiguration",
        )
        assert warning["service"] == "S3"
        assert warning["resource_id"] == "demo-test-beagle"
        assert warning["permission"] == "s3:GetLifecycleConfiguration"
        assert warning["title"] == "Lifecycle configuration could not be verified"
        assert warning["severity"] == "warning"
        assert warning["resolution"]  # Non-empty

    def test_cost_explorer_warning(self) -> None:
        warning = build_structured_warning(
            service="Cost Explorer",
            operation="GetCostAndUsage",
            code="AccessDenied",
            permission="ce:GetCostAndUsage",
        )
        assert warning["title"] == "Billing data unavailable"

    def test_custom_message(self) -> None:
        warning = build_structured_warning(
            service="RDS",
            code="AccessDenied",
            title="Custom title",
            message="Custom message",
            resolution="Custom resolution",
        )
        assert warning["title"] == "Custom title"
        assert warning["message"] == "Custom message"
        assert warning["resolution"] == "Custom resolution"


# ── 7. Report sanitization ─────────────────────────────────────────────

class TestSanitizeReport:
    def test_masks_account_id_in_report(self) -> None:
        report = {"scan": {"account_id": "277731792560", "resources": []}}
        result = sanitize_report(report)
        assert result["scan"]["account_id"] == "********2560"
        # Original unchanged
        assert report["scan"]["account_id"] == "277731792560"

    def test_masks_arn_in_report(self) -> None:
        report = {"identity_arn": "arn:aws:iam::277731792560:user/test"}
        result = sanitize_report(report)
        assert "277731792560" not in result["identity_arn"]

    def test_scrubs_raw_error_messages(self) -> None:
        report = {"scan": {"errors": [{"message": "User arn:aws:iam::277731792560:user/test is not authorized"}]}}
        result = sanitize_report(report)
        assert "277731792560" not in json.dumps(result)

    def test_migrates_old_lifecycle_booleans(self) -> None:
        report = {
            "scan": {
                "resources": [{
                    "metrics": {
                        "has_lifecycle_policy": None,
                        "missing_lifecycle_policy": False,
                    }
                }]
            }
        }
        result = sanitize_report(report)
        metrics = result["scan"]["resources"][0]["metrics"]
        assert "has_lifecycle_policy" not in metrics
        assert "missing_lifecycle_policy" not in metrics
        assert metrics["lifecycle_status"]["status"] == "unknown"

    def test_preserves_existing_lifecycle_status(self) -> None:
        report = {"scan": {"resources": [{"metrics": {"lifecycle_status": {"status": "present"}}}]}}
        result = sanitize_report(report)
        assert result["scan"]["resources"][0]["metrics"]["lifecycle_status"]["status"] == "present"
        assert "has_lifecycle_policy" not in result["scan"]["resources"][0]["metrics"]


    def test_removes_raw_account_id_and_scrubs_nested_identifiers(self) -> None:
        report = {
            "scan": {
                "account_id_raw": "277731792560",
                "debug": {"nested_account_id": "123456789012"},
            },
            "resources": [
                {
                    "service": "EC2",
                    "canonical_resource_id": "resource:277731792560:regional:us-east-1:EC2:instance:i-123",
                    "notes": ["owned by account 277731792560"],
                }
            ],
        }

        result = sanitize_report(report)
        serialized = json.dumps(result)

        assert "account_id_raw" not in serialized
        assert result["scan"]["account_id"] == "********2560"
        assert "********2560" in result["resources"][0]["canonical_resource_id"]
        assert re.search(r"\b\d{12}\b", serialized) is None


# ── 8. Full API response assertion ──────────────────────────────────────

def test_api_response_contains_no_sensitive_patterns() -> None:
    """Recursively serialize a sample API response and confirm no sensitive data."""
    report = sanitize_report({
        "scan": {
            "account_id": "277731792560",
            "identity_arn": "arn:aws:iam::277731792560:user/budgetbeagle-app",
            "resources": [
                {
                    "service": "S3",
                    "id": "demo-bucket",
                    "metrics": {
                        "lifecycle_status": {"status": "unknown", "code": "AccessDenied"},
                        "has_lifecycle_policy": None,
                        "missing_lifecycle_policy": False,
                    },
                }
            ],
            "errors": [
                {"message": "User arn:aws:iam::277731792560:user/budgetbeagle-app denied access to AKIAIOSFODNN7EXAMPLE"}
            ],
        },
        "analysis": {
            "summary": "Test",
            "findings": [],
            "warnings": [],
        },
    })

    serialized = json.dumps(report)
    # Must not contain full account IDs
    assert "277731792560" not in serialized
    # Must not contain full ARNs
    assert "arn:aws:iam" not in serialized
    # Must not contain access keys
    assert "AKIAIOSFODNN7EXAMPLE" not in serialized
    # Must not contain has_lifecycle_policy or missing_lifecycle_policy
    assert "has_lifecycle_policy" not in serialized
    assert "missing_lifecycle_policy" not in serialized
