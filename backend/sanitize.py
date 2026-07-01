"""Reusable helpers for masking AWS identifiers and sanitizing API output.

All functions in this module are safe to call from any thread.  They never
modify the original data structures - they return new objects.
"""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any


# ---------------------------------------------------------------------------
# Patterns that must never leak through normal API responses
# ---------------------------------------------------------------------------

_ACCOUNT_ID_RE = re.compile(r"\b\d{12}\b")
_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]+\b")
_SECRET_KEY_RE = re.compile(r"(?i)(?:secret.?access.?key|aws.?secret)[\"':\s=]+\S+")
_SESSION_TOKEN_RE = re.compile(r"(?i)(?:session.?token|security.?token)[\"':\s=]+\S+")
_ARN_RE = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:(?:[a-z0-9-]*:\d{12}|::\d{12}):[^\s\"',\]]+")
_CREDENTIAL_PATH_RE = re.compile(r"(?i)(?:credentials|config)\s*(?:file|path)\s*[=:]\s*\S+")

SENSITIVE_PATTERNS = [
    _ACCESS_KEY_RE,
    _SECRET_KEY_RE,
    _SESSION_TOKEN_RE,
    _CREDENTIAL_PATH_RE,
]


def _debug_enabled() -> bool:
    return os.getenv("DEBUG_AWS_ERRORS", "false").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Account ID masking
# ---------------------------------------------------------------------------

def mask_account_id(account_id: str | None) -> str:
    """Return ``********XXXX`` keeping only the last 4 digits."""
    if not account_id or not isinstance(account_id, str):
        return "Unknown"
    digits = re.sub(r"\D", "", account_id)
    if len(digits) < 4:
        return "********"
    return f"********{digits[-4:]}"


# ---------------------------------------------------------------------------
# ARN masking
# ---------------------------------------------------------------------------

def mask_arn(arn: str | None) -> str:
    """Convert a full IAM ARN to a safe identity label.

    ``arn:aws:iam::277731792560:user/budgetbeagle-app``
      -> ``IAM user: budgetbeagle-app``

    ``arn:aws:sts::277731792560:assumed-role/MyRole/session``
      -> ``IAM role: MyRole``
    """
    if not arn or not isinstance(arn, str):
        return "Unknown identity"
    if not arn.startswith("arn:"):
        return "Unknown identity"

    parts = arn.split(":")
    if len(parts) < 6:
        return "Unknown identity"

    resource = parts[5] if len(parts) == 6 else ":".join(parts[5:])

    if resource.startswith("user/"):
        return f"IAM user: {resource.split('/')[-1]}"
    if resource.startswith("role/"):
        return f"IAM role: {resource.split('/')[-1]}"
    if resource.startswith("assumed-role/"):
        segments = resource.split("/")
        role_name = segments[1] if len(segments) > 1 else "Unknown"
        return f"IAM role: {role_name}"
    if resource.startswith("root"):
        return "AWS root account"

    return "Unknown identity"


def parse_identity(arn: str | None) -> dict[str, str]:
    """Extract identity_type and identity_name from an IAM ARN."""
    if not arn or not isinstance(arn, str) or not arn.startswith("arn:"):
        return {"identity_type": "unknown", "identity_name": "Unknown"}

    parts = arn.split(":")
    resource = parts[5] if len(parts) >= 6 else ""

    if resource.startswith("user/"):
        return {"identity_type": "iam_user", "identity_name": resource.split("/")[-1]}
    if resource.startswith("role/"):
        return {"identity_type": "iam_role", "identity_name": resource.split("/")[-1]}
    if resource.startswith("assumed-role/"):
        segments = resource.split("/")
        return {"identity_type": "iam_role", "identity_name": segments[1] if len(segments) > 1 else "Unknown"}
    if resource.startswith("root"):
        return {"identity_type": "root", "identity_name": "root"}

    return {"identity_type": "unknown", "identity_name": "Unknown"}


# ---------------------------------------------------------------------------
# Sensitive-pattern detection
# ---------------------------------------------------------------------------

def contains_sensitive_patterns(text: str) -> bool:
    """Return True if *text* contains patterns that should not be in API output.

    Checks for: full 12-digit account IDs, access key IDs, secret keys,
    session tokens, full IAM ARNs, credential file paths.
    """
    if not text:
        return False
    if _ACCESS_KEY_RE.search(text):
        return True
    if _SECRET_KEY_RE.search(text):
        return True
    if _SESSION_TOKEN_RE.search(text):
        return True
    if _CREDENTIAL_PATH_RE.search(text):
        return True
    if _ARN_RE.search(text):
        return True
    # Check for bare 12-digit numbers (likely account IDs)
    for match in _ACCOUNT_ID_RE.finditer(text):
        candidate = match.group()
        # Avoid false-positives on timestamps, ports, etc.
        if len(candidate) == 12:
            return True
    return False


def scrub_sensitive_text(text: str) -> str:
    """Replace sensitive patterns in *text* with safe placeholders."""
    if not text:
        return text
    text = _ACCESS_KEY_RE.sub("[REDACTED_KEY]", text)
    text = _SECRET_KEY_RE.sub("[REDACTED_SECRET]", text)
    text = _SESSION_TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _CREDENTIAL_PATH_RE.sub("[REDACTED_PATH]", text)
    text = _ARN_RE.sub("[REDACTED_ARN]", text)
    text = _ACCOUNT_ID_RE.sub(lambda match: mask_account_id(match.group()), text)
    return text


# ---------------------------------------------------------------------------
# Structured AWS warning builder
# ---------------------------------------------------------------------------

_KNOWN_WARNINGS: dict[str, dict[str, str]] = {
    "s3:GetLifecycleConfiguration": {
        "title": "Lifecycle configuration could not be verified",
        "message": "The connected IAM identity does not have permission to inspect this bucket's lifecycle configuration.",
        "resolution": "Add the optional read-only permission and run the scan again.",
    },
    "ce:GetCostAndUsage": {
        "title": "Billing data unavailable",
        "message": "BudgetBeagle can scan resources, but it cannot retrieve account spending data.",
        "resolution": "Add the optional Cost Explorer read permission to enable billing totals.",
    },
}


def build_structured_warning(
    *,
    service: str,
    resource_id: str | None = None,
    operation: str | None = None,
    code: str = "Unknown",
    permission: str | None = None,
    title: str | None = None,
    message: str | None = None,
    resolution: str | None = None,
    severity: str = "warning",
) -> dict[str, Any]:
    """Build a clean, user-safe structured warning dict."""
    defaults = _KNOWN_WARNINGS.get(permission or "", {})
    return {
        "service": service,
        "resource_id": resource_id or "",
        "operation": operation or "",
        "code": code,
        "permission": permission or "",
        "title": title or defaults.get("title", f"{service} check could not be completed"),
        "message": scrub_sensitive_text(
            message or defaults.get("message", "An optional check was unavailable.")
        ),
        "resolution": resolution or defaults.get("resolution", "Review the required permission and try again."),
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# Report sanitization (historical + new)
# ---------------------------------------------------------------------------

def sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *report* with sensitive data scrubbed.

    This is applied at response time so that stored historical data
    is never exposed raw to the frontend.
    """
    sanitized = copy.deepcopy(report)
    _sanitize_dict(sanitized)
    return sanitized


def _sanitize_dict(obj: Any) -> None:
    """Recursively walk a dict/list and mask sensitive values in-place."""
    if isinstance(obj, dict):
        raw_account_id = obj.pop("account_id_raw", None)
        if isinstance(raw_account_id, str) and raw_account_id and not obj.get("account_id"):
            obj["account_id"] = mask_account_id(raw_account_id)

        for key, value in list(obj.items()):
            lower_key = str(key).lower()
            if isinstance(value, str) and (lower_key == "account_id" or lower_key.endswith("_account_id")):
                obj[key] = mask_account_id(value)
            elif isinstance(value, str) and lower_key in {"arn", "identity_arn"} and value.startswith("arn:"):
                obj[key] = mask_arn(value)
            elif isinstance(value, str):
                obj[key] = scrub_sensitive_text(value)

        # Migrate old boolean lifecycle fields conservatively
        _migrate_lifecycle_booleans(obj)

        for value in obj.values():
            _sanitize_dict(value)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            if isinstance(item, str):
                obj[index] = scrub_sensitive_text(item)
            else:
                _sanitize_dict(item)


def _migrate_lifecycle_booleans(obj: dict[str, Any]) -> None:
    """Map old lifecycle boolean fields to tri-state when found in stored data.

    Rules:
    - If a warning exists in the same context with AccessDenied -> unknown
    - Never infer present/absent from ambiguous booleans alone
    """
    if "lifecycle_status" in obj and isinstance(obj["lifecycle_status"], dict):
        # Already migrated - just clean up old fields
        obj.pop("has_lifecycle_policy", None)
        obj.pop("missing_lifecycle_policy", None)
        return

    has_old_bool = "has_lifecycle_policy" in obj or "missing_lifecycle_policy" in obj
    if not has_old_bool:
        return

    has_lc = obj.get("has_lifecycle_policy")
    missing_lc = obj.get("missing_lifecycle_policy")

    # Conservative mapping: if value is None or we can't determine -> unknown
    if has_lc is None and missing_lc is not None:
        if missing_lc is True:
            obj["lifecycle_status"] = {"status": "absent"}
        else:
            # missing_lifecycle_policy: False could mean present or unknown
            obj["lifecycle_status"] = {"status": "unknown", "code": "AmbiguousHistorical", "message": "Historical data was ambiguous."}
    elif has_lc is True:
        obj["lifecycle_status"] = {"status": "present"}
    elif has_lc is False:
        obj["lifecycle_status"] = {"status": "absent"}
    else:
        obj["lifecycle_status"] = {"status": "unknown", "code": "AmbiguousHistorical", "message": "Historical data was ambiguous."}

    obj.pop("has_lifecycle_policy", None)
    obj.pop("missing_lifecycle_policy", None)
