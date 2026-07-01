# BudgetBeagle Canonical JSON Schema v2.1

The canonical JSON export format is produced by `_safe_serialize` and exported via `/api/analyses/{id}/export/zip` as `report.json`.

Schema v2.1 adds multi-region metadata while keeping Phase 1 v2.0 reports readable. Old reports are interpreted as legacy `single_region` scans with one resolved region and a synthetic regional result when they do not already contain v2.1 fields.

```json
{
  "schema_version": "2.1",
  "analysis_result": {
    "region": "us-east-1",
    "legacy_primary_region": "us-east-1",
    "region_mode": "selected_regions",
    "requested_regions": ["us-east-1", "us-west-2"],
    "resolved_regions": ["us-east-1", "us-west-2"],
    "region_count": 2,
    "regional_results": [
      {
        "region": "us-east-1",
        "status": "completed",
        "started_at": "2026-06-30T12:00:00Z",
        "finished_at": "2026-06-30T12:00:05Z",
        "elapsed_seconds": 5.0,
        "resources_discovered": 3,
        "findings_generated": 1,
        "warning_count": 0,
        "warnings": [],
        "error_category": null,
        "safe_error_message": null,
        "services_attempted": ["EC2", "EBS", "Elastic IP", "Load Balancing", "RDS", "NAT Gateway", "S3"],
        "services_completed": ["EC2", "EBS", "Elastic IP", "Load Balancing", "RDS", "NAT Gateway", "S3"],
        "services_failed": []
      }
    ],
    "partial_failure_warnings": [],
    "regional_resources": [
      { "service": "EC2", "id": "i-...", "region": "us-east-1", "scope": "regional" }
    ],
    "global_resources": [
      { "service": "S3", "id": "bucket-name", "region": "us-east-1", "scope": "global" }
    ],
    "regional_findings": [
      { "source": "budgetbeagle_rule", "service": "EC2", "resource_id": "i-...", "region": "us-east-1", "scope": "regional" }
    ],
    "global_findings": [],
    "report": {
      "status": "completed_with_warnings",
      "resources_scanned": 4,
      "confirmed_issues": 0,
      "recommendations": 1,
      "observations": 1,
      "actionable_findings": 1,
      "service_coverage_summary": {
        "services_scanned": 7,
        "total_supported_services": 7,
        "services_containing_resources": 3,
        "resources_discovered": 4
      },
      "estimated_monthly_savings_display": "Not enough data",
      "savings_confidence": { "label": "Not applicable", "level": "not_applicable" }
    },
    "findings": [
      {
        "category": "recommendation",
        "category_label": "Recommendation",
        "source": "budgetbeagle_rule",
        "region": "us-east-1",
        "scope": "regional",
        "finding_confidence": { "score": 55, "label": "Low" }
      }
    ],
    "scan": {
      "region": "us-east-1",
      "legacy_primary_region": "us-east-1",
      "region_mode": "selected_regions",
      "requested_regions": ["us-east-1", "us-west-2"],
      "resolved_regions": ["us-east-1", "us-west-2"],
      "regional_results": []
    },
    "scan_confidence": { "score": 95, "label": "High" },
    "service_coverage": [
      { "service": "RDS", "status": "no_resources", "count": 0, "scanned": true }
    ]
  }
}
```

## Scan Modes

- `single_region`: legacy-compatible mode. `requested_regions` and `resolved_regions` contain exactly the submitted region.
- `selected_regions`: the frontend submits a user-selected list. The backend validates identifiers, removes duplicates for execution, and stores the exact submitted list separately from resolved regions.
- `all_enabled_regions`: the backend resolves enabled AWS regions with `ec2:DescribeRegions`. If discovery fails, the scan is rejected with a structured safe error instead of inventing regions.

## Regional Result Status

Each resolved region can be `pending`, `running`, `completed`, `completed_with_warnings`, `failed`, `cancelled`, or `interrupted`. Failed regions remain visible in reports and exports. Overall status remains one of the existing terminal states: `completed`, `completed_with_warnings`, `failed`, `cancelled`, or `interrupted`. Regional service lists record attempted, completed, and failed services; a successful service with zero resources is still completed. The global-once S3 pass is attributed into regional service telemetry without duplicating S3 API calls or bucket resources.

## Identity And Scope

Regional resources include `region`, `scope`, masked `account_id`, and canonical identity metadata. Global resources use explicit global scope and are not copied into every region. Findings include `source`, `region` or global scope, service, resource ID, and rule/recommendation type so only truly identical items are deduplicated. `region` and `scan.region` are legacy primary-region compatibility fields; new consumers should use `requested_regions` and `resolved_regions` for scan coverage. `legacy_primary_region` repeats the compatibility value explicitly.

## Counters

Canonical report counters are derived from the canonical persisted resources and findings:

- `confirmed_issues`: findings whose `category` is exactly `confirmed_issue`
- `recommendations`: findings whose `category` is exactly `recommendation`
- `observations`: findings whose `category` is exactly `observation`
- `actionable_findings`: `confirmed_issues + recommendations`

Service coverage separates scan completion from resource presence:

- `services_scanned`: `completed`, `completed_with_warnings`, and `no_resources`
- `services_containing_resources`: scanned services where `count > 0`
- `resources_discovered`: total resources returned across supported services
- `failed` and `skipped` services do not count as scanned

## Billing Semantics

Cost Explorer rows are account-level billing context, not per-region scan inventory. Billing is collected once per scan. `selected_regions` records the scan regions used to filter selected-region spend, while `region_costs_ytd` records AWS billed-region dimensions. Equivalent global billing aliases such as `global`, `NoRegion`, and `Global / No Region` are normalized into one `Global / No Region` row and are not converted into scan regions.

Exports normalize near-zero monetary values before display. Values whose absolute value is below half a cent serialize as `$0.00`, never `$-0.00`, `-$0.00`, or `-0.00 USD`.

## ZIP Export Files

The ZIP export preserves the Phase 1 files and adds `regions.csv`:

- `report.json`
- `summary.csv`
- `resources.csv`
- `findings.csv`
- `billing-services.csv`
- `billing-regions.csv`
- `warnings.csv`
- `service-coverage.csv`
- `regions.csv`

All export files remain UTF-8 and must not contain `account_id_raw`, credentials, session tokens, full unmasked account IDs, full ARNs, or sensitive stack traces. `regions.csv` leaves completed-region error fields blank when there is no error.
