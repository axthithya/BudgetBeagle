from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from fastapi.responses import StreamingResponse

from report_schema import normalize_analysis_result
from sanitize import sanitize_report, scrub_sensitive_text

ZIP_FILENAMES = [
    "report.json",
    "summary.csv",
    "resources.csv",
    "findings.csv",
    "billing-services.csv",
    "billing-regions.csv",
    "warnings.csv",
    "service-coverage.csv",
]


def generate_zip_export(analysis_record: dict[str, Any]) -> StreamingResponse:
    payload = build_export_payload(analysis_record)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("report.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8"))
        zip_file.writestr("summary.csv", _summary_csv(payload).encode("utf-8"))
        zip_file.writestr("resources.csv", _resources_csv(payload).encode("utf-8"))
        zip_file.writestr("findings.csv", _findings_csv(payload).encode("utf-8"))
        zip_file.writestr("billing-services.csv", _billing_csv(payload, "service_costs_ytd", ["Service", "Amount USD", "Display"]).encode("utf-8"))
        zip_file.writestr("billing-regions.csv", _billing_csv(payload, "region_costs_ytd", ["Region", "Amount USD", "Display"]).encode("utf-8"))
        zip_file.writestr("warnings.csv", _warnings_csv(payload).encode("utf-8"))
        zip_file.writestr("service-coverage.csv", _coverage_csv(payload).encode("utf-8"))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=budgetbeagle_export_{analysis_record.get('id', 'report')}.zip"},
    )


def build_export_payload(analysis_record: dict[str, Any]) -> dict[str, Any]:
    canonical = normalize_analysis_result(
        analysis_record.get("analysis_result", {}),
        region=analysis_record.get("region"),
        resource_group=analysis_record.get("scan_target"),
    )
    payload = {
        "schema_version": "2.0",
        "analysis_id": analysis_record.get("id"),
        "status": analysis_record.get("status"),
        "region": analysis_record.get("region"),
        "scan_target": analysis_record.get("scan_target"),
        "created_at": analysis_record.get("created_at"),
        **canonical,
    }
    return sanitize_report(payload)


def _summary_csv(payload: dict[str, Any]) -> str:
    report = payload.get("report", {})
    metrics = payload.get("metrics", {})
    confidence = payload.get("scan_confidence", {})
    rows = [
        ["Metric", "Value"],
        ["Status", payload.get("status", "Unknown")],
        ["Resources Scanned", report.get("resources_scanned", "Unknown")],
        ["Confirmed Issues", report.get("confirmed_issues", "Unknown")],
        ["Recommendations", report.get("recommendations", "Unknown")],
        ["Observations", report.get("observations", "Unknown")],
        ["Warnings", report.get("warnings_count", "Unknown")],
        ["Monthly Savings", report.get("estimated_monthly_savings_display") or metrics.get("monthly_savings_display") or "Not enough data"],
        ["Yearly Savings", (report.get("yearly_savings") or {}).get("display") or metrics.get("yearly_savings_display") or "Not enough data"],
        ["Scan Confidence", confidence.get("label", "Unknown")],
        ["Scan Confidence Score", confidence.get("score", "Unknown")],
    ]
    return _csv(rows)


def _resources_csv(payload: dict[str, Any]) -> str:
    rows = [["Service", "Resource ID", "Region", "State", "Type", "Assessment"]]
    region = payload.get("region", "")
    for resource in payload.get("resources", []):
        metrics = resource.get("metrics") if isinstance(resource.get("metrics"), dict) else {}
        signal = metrics.get("utilization_signal") if isinstance(metrics.get("utilization_signal"), dict) else {}
        rows.append([
            resource.get("service", "Unknown"),
            resource.get("id") or resource.get("resource_id") or "Unknown",
            resource.get("region") or region or "Unknown",
            resource.get("state", "Unknown"),
            resource.get("type_or_sku", "Unknown"),
            signal.get("assessment") or metrics.get("assessment") or "Unknown",
        ])
    return _csv(rows)


def _findings_csv(payload: dict[str, Any]) -> str:
    rows = [[
        "Category",
        "Service",
        "Resource ID",
        "Finding",
        "Severity",
        "Finding Confidence",
        "Savings Confidence",
        "Savings",
        "Pricing Status",
        "Evidence",
        "Recommendation",
        "Savings Basis",
        "Action Risk",
    ]]
    for finding in payload.get("findings", []):
        finding_confidence = finding.get("finding_confidence") or {}
        savings_confidence = finding.get("savings_confidence") or {}
        rows.append([
            finding.get("category", "Unknown"),
            finding.get("service", "Unknown"),
            finding.get("resource_id", "Unknown"),
            finding.get("issue_type", "Unknown"),
            finding.get("severity", "Unknown"),
            finding_confidence.get("label") or finding.get("confidence", "Unknown"),
            savings_confidence.get("label") or savings_confidence.get("level") or "Not applicable",
            finding.get("estimated_monthly_savings_display", "Not enough data"),
            finding.get("pricing_status", "Unknown"),
            _json_cell(finding.get("evidence", {})),
            finding.get("ai_recommendation") or finding.get("recommendation") or "Unknown",
            finding.get("savings_basis", "Unknown"),
            finding.get("action_risk", "Unknown"),
        ])
    return _csv(rows)


def _billing_csv(payload: dict[str, Any], key: str, header: list[str]) -> str:
    rows = [header]
    for item in (payload.get("billing", {}) or {}).get(key, []):
        rows.append([item.get("name") or item.get("label") or "Unknown", item.get("amount_usd", "Unknown"), item.get("display", "Unknown")])
    return _csv(rows)


def _warnings_csv(payload: dict[str, Any]) -> str:
    rows = [["Service", "Resource ID", "Code", "Message", "Permission", "Resolution"]]
    for warning in payload.get("warnings", []):
        rows.append([
            warning.get("service", "Unknown"),
            warning.get("resource_id", ""),
            warning.get("code", "Unknown"),
            warning.get("message", "Unknown"),
            warning.get("permission", ""),
            warning.get("resolution", ""),
        ])
    return _csv(rows)


def _coverage_csv(payload: dict[str, Any]) -> str:
    rows = [["Service", "Status", "Count"]]
    for item in payload.get("service_coverage", []):
        rows.append([item.get("service", "Unknown"), item.get("status", "Unknown"), item.get("count", 0)])
    return _csv(rows)


def _csv(rows: list[list[Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for row in rows:
        writer.writerow([_safe_cell(value) for value in row])
    return output.getvalue()


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _safe_cell(value: Any) -> str:
    if value is None:
        return "Unknown"
    return scrub_sensitive_text(str(value))
