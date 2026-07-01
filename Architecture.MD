# AI Cloud Cost Detective - Architecture

```text
                              +-------------+
                              |    USER     |
                              +------+------+ 
                                     |
                                     v
                         +----------------------+
                         | React frontend       |
                         | Vite + TS + Tailwind |
                         +----------+-----------+
                                    |
                                    | JWT auth, REST, WebSocket
                                    v
                         +----------------------+
                         | FastAPI backend      |
                         | Custom JWT auth      |
                         +----+----------+------+
                              |          |
                    boto3 scan|          | optional Groq wording
                              v          v
+-------------------+   +-------------------+   +------------------+
| AWS account       |   | Progress WebSocket|   | Groq API          |
| regional services |   | /ws/progress/{id} |   | explanation text  |
| S3, Cost Explorer |   |                   |   |                  |
| CloudWatch        |   +---------+---------+   +---------+--------+
+---------+---------+             |                       |
          |                       v                       |
          |              +-------------------+             |
          |              | React progress UI |             |
          |              +-------------------+             |
          |                                               |
          +-----------------------+-----------------------+
                                  v
                         +----------------------+
                         | SQLAlchemy database  |
                         | SQLite or Postgres   |
                         | users, analyses      |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | React report/history |
                         | regions, issues, CLI |
                         +----------------------+
```

## What Changed From The Azure Original

| Layer | Original Azure version | AWS edition |
| --- | --- | --- |
| Cloud data | Azure CLI subprocess calls | boto3 native AWS SDK |
| Scan unit | Azure Resource Group | AWS single region, selected regions, or all enabled regions |
| Cost analysis | OpenAI API | deterministic AWS rule engine, optional Groq wording |
| Database | Managed PostgreSQL | SQLite by default, Postgres-ready |
| Setup | Manual backend/frontend setup | `./start.sh`, `py run.py`, or `docker compose up --build` |

## Backend Responsibilities

- Authenticate app users with custom JWTs.
- Normalize legacy and multi-region scan requests.
- Discover enabled AWS regions with read-only `ec2:DescribeRegions`.
- Scan AWS resources through the standard AWS credential chain.
- Run bounded multi-region orchestration without duplicating global APIs.
- Pull CloudWatch utilization metrics for resource-aware recommendations.
- Pull Cost Explorer account and selected scan-region billing context once per scan when `ce:GetCostAndUsage` is allowed.
- Degrade gracefully when one AWS service or one AWS region denies read access.
- Generate findings, savings, yearly estimates, confidence scores, warnings, pricing status, billing summaries, and AWS command templates deterministically in backend code.
- Optionally send validated findings to Groq for explanation wording only.
- Persist every analysis for the signed-in user with schema v2.1 regional metadata and v2.0 compatibility defaults.
- Replay progress messages to late WebSocket subscribers.

## Read-Only Boundary

BudgetBeagle never executes generated AWS CLI commands and does not call AWS write APIs. Future AWS-native recommendation sources must integrate through the adapter layer and remain read-only.