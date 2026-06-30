# BudgetBeagle Canonical JSON Schema v2.0

The canonical JSON export format is produced by `_safe_serialize` and exported via `/api/analyses/{id}/export/zip` as `report.json`.

```json
{
  "schema_version": "2.0",
  "analysis_result": {
    "report": {
      "resources_scanned": 3,
      "confirmed_issues": 0,
      "recommendations": 1,
      "observations": 1,
      "actionable_findings": 1,
      "service_coverage_summary": {
        "services_scanned": 7,
        "total_supported_services": 7,
        "services_containing_resources": 3,
        "resources_discovered": 3
      },
      "estimated_monthly_savings_display": "Not enough data",
      "savings_confidence": { "label": "Not applicable", "level": "not_applicable" }
    },
    "findings": [
      {
        "category": "recommendation",
        "category_label": "Recommendation",
        "finding_confidence": { "score": 55, "label": "Low" }
      }
    ],
    "scan_confidence": { "score": 95, "label": "High" },
    "service_coverage": [
      { "service": "RDS", "status": "no_resources", "count": 0, "scanned": true }
    ]
  }
}
```

Finding category semantics are exact:

- `confirmed_issues`: findings whose `category` is exactly `confirmed_issue`
- `recommendations`: findings whose `category` is exactly `recommendation`
- `observations`: findings whose `category` is exactly `observation`
- `actionable_findings`: `confirmed_issues + recommendations`

Service coverage separates scan completion from resource presence:

- `services_scanned`: `completed`, `completed_with_warnings`, and `no_resources`
- `services_containing_resources`: scanned services where `count > 0`
- `resources_discovered`: total resources returned across supported services
- `failed` and `skipped` services do not count as scanned

Confidence fields are separate:

- `scan_confidence`: scan completeness, service coverage, warnings, metric retrieval coverage, and billing availability
- `finding_confidence`: evidence quality for each finding
- `savings_confidence`: present only for numeric savings; otherwise `Not applicable`

Exports normalize near-zero monetary values before display. Values whose absolute value is below half a cent serialize as `$0.00`, never `$-0.00`, `-$0.00`, or `-0.00 USD`.
