# Architecture

BudgetBeagle is designed as an evidence-first AWS FinOps application.

## Core Philosophy

1. **Evidence-First**: BudgetBeagle never modifies your AWS environment automatically. It only provides read-only analysis and clear, reversible CLI commands.
2. **Deterministic Rules**: All findings are generated using deterministic python rules based on AWS CloudWatch metrics and resource state.
3. **AI Enhancement**: Optional Groq LLM integration is only used to rewrite explanations and summarize the deterministic findings. It cannot invent new findings or modify data.

## Components

- **Frontend**: React, Tailwind CSS, Vite. Connects via WebSocket for real-time progress.
- **Backend**: FastAPI, SQLAlchemy (SQLite/Postgres). Runs scans asynchronously via `AwsScanner` and `ai_analyzer`.
- **Authentication**: JWT-based stateless authentication.
- **Data Export**: ZIP-based bulk export for CSVs and JSON (`export.py`).
