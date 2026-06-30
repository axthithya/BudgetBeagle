# BudgetBeagle Canonical JSON Schema v2.0

The canonical JSON export format is heavily documented below. It is produced by `_safe_serialize` and exported via `/api/analyses/{id}/export/zip` as `report.json`.

```json
{
  "schema_version": "2.0",
  "id": 1,
  "user_id": 1,
  "region": "us-east-1",
  "scan_target": "whole-region",
  "resources_scanned": 150,
  "issues_found": 5,
  "estimated_savings": "$125.00/month",
  "status": "completed",
  "created_at": "2026-06-29T12:00:00Z",
  "analysis_result": {
    "region": "us-east-1",
    "resource_group": null,
    "scan": { ... },
    "findings": [
      {
        "id": "ec2:i-1234:low-utilization",
        "category": "Recommendation",
        "service": "EC2",
        "resource_id": "i-1234",
        "issue_type": "Low Utilization",
        "severity": "medium",
        "confidence": "high",
        "confidence_score": 85,
        "evidence": { ... },
        "ai_explanation": "..."
      }
    ],
    "warnings": [ ... ],
    "billing": { ... },
    "metrics": { ... },
    "scan_confidence": {
      "score": 85,
      "label": "High",
      "factors": [ ... ]
    },
    "ai_enrichment_status": "completed"
  }
}
```
