# Architecture

BudgetBeagle is an evidence-first AWS FinOps application. It reads AWS inventory, CloudWatch metrics, and optional Cost Explorer billing data, then generates deterministic findings and reviewable CLI examples without modifying AWS resources.

## Core Philosophy

1. **Read-only by design**: BudgetBeagle never starts, stops, resizes, deletes, tags, or remediates AWS resources automatically.
2. **Evidence-first findings**: Deterministic Python rules generate findings from observed resources, metrics, pricing, billing, and warnings.
3. **Optional AI wording**: Groq may rewrite validated explanation text, but it cannot invent findings, savings, resources, or commands.
4. **Graceful degradation**: Missing permissions and regional failures are represented as warnings or regional failures instead of hidden behind a successful report.

## Components

- **Frontend**: React, TypeScript, Tailwind CSS, Vite. The dashboard exposes single-region, selected-regions, and all-enabled-regions scan modes. The report UI displays regional status, region-aware resources, warnings, and progress.
- **Backend API**: FastAPI, SQLAlchemy, JWT auth. `POST /api/analyze` normalizes scan requests and starts asynchronous analysis jobs.
- **Region discovery**: `backend/region_discovery.py` uses read-only `ec2:DescribeRegions`, validates region identifiers, sorts deterministically, removes duplicates, and returns structured safe errors.
- **Scan normalization and identity**: `backend/multi_region.py` owns scan mode normalization, bounded concurrency validation, resource/finding metadata, canonical identity, deduplication, and final regional aggregation helpers.
- **Scanner**: `backend/aws_scanner.py` creates regional boto3 clients for inventory and metrics. It can skip global S3 and billing when used by multi-region workers.
- **Orchestrator**: `backend/scan_orchestrator.py` runs resolved regions through a bounded thread pool, preserves partial results, avoids per-region global calls, and emits structured progress details.
- **Billing**: `backend/billing.py` calls Cost Explorer once per scan and keeps scan regions separate from AWS billed-region dimensions.
- **Rules and adapters**: `backend/cost_rules.py` produces current findings with source `budgetbeagle_rule`. `backend/recommendation_adapters.py` defines the internal normalization shape for future `aws_compute_optimizer` and `aws_cost_optimization_hub` sources without calling them in Phase 2A.1.
- **Progress**: `backend/progress.py` stores progress events with TTL cleanup. WebSocket progress and polling fallback both consume the same persisted events.
- **Persistence**: Reports are stored as canonical JSON in the existing analysis table. v2.1 metadata is added without destructive database migrations; old v2.0 reports are adapted on read.
- **Exports**: `backend/export.py` produces UTF-8 JSON/CSV/ZIP exports, including per-region status in `regions.csv`.

## Multi-Region Flow

```text
Dashboard scan mode
  -> POST /api/analyze
  -> normalize mode/requested regions/resolved regions
  -> single_region uses existing scanner path
  -> selected_regions/all_enabled_regions use scan_orchestrator
  -> regional inventory workers run with bounded concurrency
  -> global S3 inventory runs once
  -> Cost Explorer billing runs once
  -> deterministic rules generate findings
  -> schema v2.1 report persists regional results and compatibility fields
  -> WebSocket and polling expose progress and terminal status
```

## Global Versus Regional APIs

Regional APIs are called once per resolved region. Global/account APIs are called once per scan:

- S3 bucket listing is global and filtered by bucket location.
- Cost Explorer billing is account-level and queried once for the selected scan regions.
- Account identity is captured once and masked in persisted/exported outputs.

This prevents duplicated resources, findings, and billing totals when multiple regions are scanned.

## Cancellation And Partial Success

Cancellation is checked before expensive stages and between regional completions. If one region fails, successful regional results remain in the report and the overall status becomes `completed_with_warnings` when useful results exist. If all regions fail and no useful resources or findings exist, the scan fails with safe error metadata.

## Known Limitations

- Phase 2A.1 does not call AWS Compute Optimizer or AWS Cost Optimization Hub.
- Multi-region scans currently disable Resource Group filtering because AWS Resource Groups are selected from the single-region setup flow.
- Per-service progress is best effort; existing scanner internals still emit coarse service/stage messages.
- Manual AWS validation is still required before marking Phase 2A.1 complete.