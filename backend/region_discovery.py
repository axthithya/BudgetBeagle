from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError

from sanitize import scrub_sensitive_text


REGION_PATTERN = re.compile(r"^(?:[a-z]{2}|cn|us-gov|us-iso|us-isob|us-isof)-[a-z0-9-]+-\d+$")
DISCOVERY_PERMISSION = "ec2:DescribeRegions"
PERMISSION_DENIED_CODES = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedException"}
AUTH_CODES = {"AuthFailure", "UnrecognizedClientException", "InvalidClientTokenId", "ExpiredToken", "ExpiredTokenException"}


@dataclass(frozen=True)
class RegionDiscoveryError:
    code: str
    message: str
    category: str
    permission: str | None = DISCOVERY_PERMISSION

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "permission": self.permission,
        }


@dataclass(frozen=True)
class RegionDiscoveryResult:
    status: str
    regions: list[str]
    error: RegionDiscoveryError | None = None

    @property
    def available(self) -> bool:
        return self.status == "available"

    def as_api_response(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "regions": self.regions,
            "error": self.error.as_dict() if self.error else None,
            "permission": DISCOVERY_PERMISSION,
        }


def is_valid_region_identifier(value: str) -> bool:
    return bool(REGION_PATTERN.fullmatch(value.strip()))


def normalize_region_values(values: list[str]) -> list[str]:
    normalized: set[str] = set()
    invalid: list[str] = []
    for value in values:
        region = str(value or "").strip()
        if not is_valid_region_identifier(region):
            invalid.append(region or "<empty>")
            continue
        normalized.add(region)
    if invalid:
        joined = ", ".join(invalid)
        raise ValueError(f"Malformed AWS region identifier: {joined}")
    return sorted(normalized)


def discover_enabled_regions(*, session: Any | None = None, base_region: str | None = None) -> RegionDiscoveryResult:
    """Discover enabled AWS regions with a safe, structured result."""
    try:
        client = (session or boto3.Session(region_name=base_region or os.getenv("AWS_DEFAULT_REGION", "us-east-1"))).client("ec2")
        response = client.describe_regions(AllRegions=False)
        regions = sorted({
            item.get("RegionName", "").strip()
            for item in response.get("Regions", [])
            if is_valid_region_identifier(str(item.get("RegionName", "")).strip())
        })
        if not regions:
            return RegionDiscoveryResult(
                status="empty",
                regions=[],
                error=RegionDiscoveryError(
                    code="NoEnabledRegions",
                    message="AWS returned no enabled regions for this account.",
                    category="empty",
                    permission=None,
                ),
            )
        return RegionDiscoveryResult(status="available", regions=regions)
    except (NoCredentialsError, PartialCredentialsError):
        return RegionDiscoveryResult(
            status="unavailable",
            regions=[],
            error=RegionDiscoveryError(
                code="MissingCredentials",
                message="AWS credentials are missing or incomplete.",
                category="auth",
                permission=None,
            ),
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code") or "RegionDiscoveryFailed")
        if code in PERMISSION_DENIED_CODES:
            return RegionDiscoveryResult(
                status="permission_denied",
                regions=[],
                error=RegionDiscoveryError(
                    code=code,
                    message="Region discovery requires ec2:DescribeRegions.",
                    category="permission_denied",
                ),
            )
        if code in AUTH_CODES:
            return RegionDiscoveryResult(
                status="unavailable",
                regions=[],
                error=RegionDiscoveryError(
                    code=code,
                    message="AWS credentials could not be authenticated.",
                    category="auth",
                    permission=None,
                ),
            )
        return RegionDiscoveryResult(
            status="unavailable",
            regions=[],
            error=RegionDiscoveryError(
                code=code,
                message=scrub_sensitive_text(str(error.get("Message") or "Region discovery failed.")),
                category="aws_error",
            ),
        )
    except (BotoCoreError, OSError, TimeoutError) as exc:
        return RegionDiscoveryResult(
            status="unavailable",
            regions=[],
            error=RegionDiscoveryError(
                code=exc.__class__.__name__,
                message="Region discovery is temporarily unavailable.",
                category="unavailable",
            ),
        )
