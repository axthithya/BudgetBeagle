# BudgetBeagle Master Development Roadmap

BudgetBeagle's goal is to become an open-source, evidence-first AWS FinOps assistant.

## Phase 1: Foundation (Completed)

- 1.1 Report correctness and counter consistency.
- 1.2 Confidence model correction.
- 1.3 Pricing coverage semantics.
- 1.4 Currency and billing formatting.
- 1.5 Resources page redesign.
- 1.6 Responsive UI.
- 1.7 Accessibility.
- 1.8 CSV/ZIP export redesign.
- 1.9 Canonical JSON schema.
- 1.10 History compatibility and migrations.
- 1.11 Analysis job reliability.
- 1.12 Documentation and branding audit.

## Phase 2A: Multi-Region And Native Recommendation Foundation

- 2A.1 Multi-region scanning foundation: COMPLETE.
  - Single-region legacy compatibility.
  - Selected-regions and all-enabled-regions scan modes.
  - Structured region discovery with `ec2:DescribeRegions`.
  - Bounded multi-region orchestration and partial regional failure reporting.
  - Schema v2.1, sanitized regional exports, service telemetry accounting, and future recommendation adapter foundation.
- 2A.2 AWS-native recommendations: NOT STARTED.
  - Future work may integrate Compute Optimizer and Cost Optimization Hub through the adapter interface.
  - Do not make live AWS-native recommendation calls until Phase 2A.2 is explicitly started.
- 2A.3 Top Savings page: NOT STARTED.

## Phase 2B: Open Source Polish

- Setup CI/CD.
- Add broad test coverage.
- Community guidelines.

## Phase 3: Advanced FinOps

- Tag-based chargeback reports.
- Machine learning anomaly detection.
- Spot instance viability checks.