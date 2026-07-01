# Phase Status

**Phase 1: Foundation is 100% Complete.**

- 1.1 Report correctness: DONE
- 1.2 Confidence model: DONE
- 1.3 Pricing semantics: DONE
- 1.4 Currency formatting: DONE
- 1.5 Resource redesign: DONE
- 1.6 Responsive UI: DONE
- 1.7 Accessibility: DONE
- 1.8 Export redesign: DONE (ZIP multiple CSVs)
- 1.9 JSON schema: DONE (v2.0 canonical format)
- 1.10 History compatibility: DONE
- 1.11 Analysis reliability: DONE
- 1.12 Documentation: DONE

## Phase 2A.1: Multi-Region Scanning Foundation

**Status: COMPLETE**

Completion evidence: local backend tests, frontend typecheck/tests/build/audit, Docker config, launcher check, documentation, branch push, and GitHub Actions passed on 2026-07-01.

### Verified Architecture Audit

- Scan creation endpoint: `POST /api/analyze` in `backend/main.py` creates an `Analysis` row, normalizes the scan request, starts `run_analysis_job`, and returns the progress WebSocket URL.
- Scan request models: `AnalyzeRequest` now accepts legacy `region`, optional `resource_group`, and multi-region `region_mode` plus `requested_regions`.
- Background execution: `run_analysis_job` in `backend/main.py` runs single-region scans through the existing path and multi-region scans through `backend/scan_orchestrator.py`.
- AWS sessions and clients: `backend/aws_scanner.py`, `backend/billing.py`, and `backend/region_discovery.py` create boto3 sessions/clients. Regional scanner calls are instantiated per resolved region. Global S3 inventory and Cost Explorer billing are called once per scan.
- Region selection: legacy region selection is normalized in `backend/multi_region.py`; all-enabled region resolution uses `backend/region_discovery.py` and `ec2:DescribeRegions`.
- Resource scanners: `AwsScanner.scan()` covers EC2, EBS, Elastic IP, NAT Gateway, ELB, RDS, and optional S3. Regional workers disable per-region billing and per-region S3 to avoid global duplication.
- Deterministic rules: `backend/cost_rules.py` remains the only source of live findings in this milestone and now preserves resource region, scope, and `budgetbeagle_rule` source metadata.
- Billing and Cost Explorer: `backend/billing.py` accepts selected regions, queries account and regional dimensions once, keeps scan regions separate from billed-region rows, and merges equivalent global aliases into `Global / No Region`.
- Pricing calls: existing pricing behavior remains deterministic and evidence-backed; no Phase 2A.2 AWS-native recommendation APIs are called.
- Progress manager: `backend/progress.py` remains the storage/replay layer. Multi-region progress adds structured `details` while preserving message-based Phase 1 behavior.
- WebSocket progress: `/ws/progress/{analysis_id}` in `backend/main.py` replays and streams progress events. Multi-region details include region counts, active regions, warnings, resources, findings, and a monotonic weighted percentage displayed as `Overall progress`.
- Polling fallback: frontend polling in `frontend/src/pages/Dashboard.tsx` still resumes active analyses when WebSocket delivery is interrupted.
- Cancellation: existing cancellation state is checked before and after scanner/analyzer stages; multi-region orchestration checks cancellation between regional completions.
- Report persistence: canonical report payloads are stored in the `Analysis.analysis_result` JSON column without destructive migrations.
- History loading: `/api/history` and `/api/analyses/{id}` continue returning saved reports; `backend/report_schema.py` adapts old reports to v2.1-compatible defaults at read/serialization time.
- Retry behavior: retrying a prior analysis creates a new `Analysis` row and reruns the normalized request without mutating the old report.
- Exports: `backend/export.py` creates recursively sanitized `report.json`, existing CSV files, and the new `regions.csv` with region status, counts, service telemetry, and safe error text; completed regions with no error export blank error cells.
- Frontend scan setup: `frontend/src/pages/Dashboard.tsx` now exposes single-region, selected-regions, and all-enabled-regions modes.
- Frontend report types: `frontend/src/lib/api.ts` includes v2.1 regional result, scan mode, `legacy_primary_region`, and region/scope metadata types.
- Frontend progress: `frontend/src/components/ProgressTracker.tsx` renders structured multi-region progress when present and the Phase 1 message list for legacy scans.
- Existing fixtures: backend tests use mocked AWS clients and frontend tests use mocked REST responses; no automated test should require real AWS credentials.
- Existing schema version: Phase 1 canonical reports used `2.0`; Phase 2A.1 reports use `2.1` with compatibility defaults for old payloads.
- Single-region assumptions found and addressed: request payloads, region discovery, legacy primary-region fields, scan result region fields, command region flags, billing selected-region labels, progress UI, report table columns, warnings, export headers, and report schema defaults.

### Implementation Plan

- Normalize all scan requests into canonical mode, requested regions, and resolved regions.
- Discover enabled regions with read-only `ec2:DescribeRegions`, structured safe errors, deterministic sorting, duplicate removal, and identifier validation.
- Add a bounded multi-region orchestration layer with deterministic aggregation, partial failure capture, S3/global billing single-call behavior, service telemetry accounting, and cancellation checks.
- Add canonical resource/finding identity helpers so retries and partial results do not duplicate identical resources or findings.
- Extend report schema and export formats to include per-region status, region metadata, global/regional resource splits, and partial failure warnings.
- Keep old Phase 1 reports readable as legacy `single_region` reports without destructive migrations.
- Update frontend scan setup, progress, and report surfaces for multi-region behavior while preserving the legacy single-region API path.
- Add the internal recommendation adapter foundation for future AWS-native recommendation sources without making Compute Optimizer or Cost Optimization Hub calls.
- Document IAM, schema, architecture, request flow, exports, concurrency, cancellation, partial success, and known limitations.