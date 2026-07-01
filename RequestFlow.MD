# Request Flow

```text
1. User -> React -> FastAPI auth -> JWT stored by the client.
2. Dashboard loads `/api/regions` and `/api/aws/status`.
3. User chooses a scan mode:
   - single_region
   - selected_regions
   - all_enabled_regions
4. React -> POST `/api/analyze` with legacy `region` fields or v2.1 scan-mode metadata.
5. FastAPI normalizes the request into requested regions and resolved regions.
6. Single-region scans use the existing scanner path; multi-region scans use the bounded orchestrator.
7. Regional boto3 scans read resources and CloudWatch metrics. Global S3 inventory and Cost Explorer billing run once per scan.
8. FastAPI -> WebSocket -> React progress tracker with message progress plus structured regional details.
9. Polling fallback checks `/api/analyses/{id}` if WebSocket delivery is interrupted or the browser refreshes.
10. Deterministic cost rules produce findings, warnings, billing summaries, confidence, savings status, and command templates.
11. Optional Groq wording rewrites already validated finding text only.
12. FastAPI persists the canonical report and regional results in the existing analysis history.
13. React displays the final report with overview, billing, findings, resources, commands, warnings, and regional status.
14. Export endpoints produce UTF-8 JSON/CSV/ZIP files with region metadata and safe error text.
```

The scanner uses read-only AWS calls such as `Describe*`, `List*`, and `Get*` plus CloudWatch and optional Cost Explorer reads. It does not modify AWS resources or execute generated AWS CLI commands.

## Partial Success

A failed region does not discard successful regional results. The report shows region-level status, safe error messages, warnings, and counts. Useful partial results complete as `completed_with_warnings`; all-region failure without useful results is `failed`.

## Cancellation

Cancellation is persisted and checked before analysis stages and between multi-region completions. A cancelled scan does not report false 100% completion.