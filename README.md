# BudgetBeagle - AI Cloud Cost Detective for AWS

BudgetBeagle is a local web app that scans your AWS account and uses deterministic backend rules to produce evidence-backed cost findings, savings, warnings, and reviewable `aws` CLI fix commands. Groq AI is optional and may only rewrite validated explanations; it does not decide findings, savings, pricing, resource IDs, or commands.

It is built for people who want to understand where AWS money may be leaking without manually checking EC2, EBS, RDS, S3, load balancers, Elastic IPs, NAT Gateways, and CloudWatch metrics one service at a time.

BudgetBeagle is read-only by default. It scans and analyzes your AWS account, but it does not automatically change, stop, resize, or delete AWS resources. Any fix command shown in the report must be reviewed and run by you.

## Table of Contents

- [What Problem This Solves](#what-problem-this-solves)
- [How It Works](#how-it-works)
- [Features](#features)
- [Before You Start](#before-you-start)
- [Windows Quick Start](#windows-quick-start)
- [How To Fill `backend/.env`](#how-to-fill-backendenv)
- [How To Get A Groq API Key](#how-to-get-a-groq-api-key)
- [How To Get AWS Access Keys](#how-to-get-aws-access-keys)
- [How To Use The App](#how-to-use-the-app)
- [What The Report Means](#what-the-report-means)
- [AWS Permissions](#aws-permissions)
- [Other Ways To Run](#other-ways-to-run)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

## What Problem This Solves

AWS bills can grow because resources stay running, storage is forgotten, or services are over-provisioned. BudgetBeagle helps you catch common waste such as:

- EC2 instances with low CPU utilization
- RDS databases that look idle or oversized
- Unattached EBS volumes
- Elastic IPs that are allocated but not attached
- Idle Application, Network, or Classic Load Balancers
- NAT Gateways that may be costing money every hour
- S3 buckets missing lifecycle policies
- Dev/test RDS instances using expensive Multi-AZ settings

The goal is not to blindly delete things. The goal is to give you an evidence-first checklist so you can review real resources, real metrics, and suggested next actions.

## How It Works

```text
You open the React app
  -> sign up or log in
  -> choose an AWS region and optional AWS Resource Group
  -> FastAPI backend scans AWS with boto3
  -> CloudWatch metrics and optional AWS Cost Explorer billing data are collected where available
  -> deterministic backend rules analyze inventory, metrics, billing, pricing, confidence, and warnings
  -> optional Groq wording improves validated explanations
  -> the report is saved in SQLite
  -> the frontend shows savings, issues, notes, and copyable commands
```

The app has two parts:

| Part | What it does |
| --- | --- |
| Frontend | React, Vite, TypeScript, Tailwind UI; defaults to `http://localhost:5173` |
| Backend | FastAPI API; defaults to `http://localhost:8000` |
| AWS Scanner | Uses `boto3` and your AWS credentials to read inventory, CloudWatch metrics, and optional Cost Explorer billing context |
| Cost Analyzer | Uses deterministic rules for findings, savings, confidence, billing summaries, pricing status, warnings, and command templates; optional Groq wording can clarify validated explanations |
| Database | SQLite by default, with optional Postgres/RDS through `DATABASE_URL` |

More architecture notes are in [Architecture.MD](./Architecture.MD), and the request flow is in [RequestFlow.MD](./RequestFlow.MD).

## Features

- Login and signup with JWT authentication
- AWS region picker
- Optional AWS Resource Group scan filter
- Live progress updates through WebSocket
- Scan history for each signed-in user
- Saved reports you can reopen later
- Account-wide and selected-region YTD billing summaries when Cost Explorer is available
- Monthly account billing, service-cost, and billed-region tables
- Evidence-backed monthly and yearly savings displays
- Explicit category labels: Confirmed issue, Recommendation, Observation
- Severity and finding-level confidence scores based on evidence quality
- Overall scan confidence derived from evidence, warnings, and billing availability
- Pricing Coverage tracking (Fully priced, Partially priced, Unavailable, Not applicable)
- Tabbed report views for overview, billing, findings, resources, commands, and warnings
- Comprehensive Resources table with detailed expandable service properties and metrics
- Human-readable explanations
- Copyable `aws` CLI fix commands only when backend validation passes
- Formatted CSV finding export and canonical JSON history export
- Read-only AWS scanning behavior
- SQLite local database by default
- Docker option for users who prefer containers

## Before You Start

Install these first:

1. [Python 3.10 or newer](https://www.python.org/downloads/windows/)
2. [Node.js 18 or newer](https://nodejs.org/)
3. Optional: a [Groq API key](https://console.groq.com/keys) for clearer wording
4. AWS credentials with read-only permissions

On Windows, use the Python launcher command:

```powershell
py run.py
```

Important Windows note: in this project, `py run.py` is the recommended command. `python run.py` and `start.bat` may fail on Windows if the `python` command is not correctly mapped in PATH. The current `start.bat` runs `python run.py`, so if `python run.py` fails for you, `start.bat` will probably fail too.

## Windows Quick Start

From PowerShell or Windows Terminal:

```powershell
git clone https://github.com/axthithya/BudgetBeagle.git
cd BudgetBeagle
py run.py
```

On the first run, the launcher will:

1. Create a backend Python virtual environment.
2. Install backend dependencies.
3. Install frontend dependencies.
4. Create `backend/.env`.
5. Stop and ask you to fill in the required secrets.

Open this file:

```text
backend/.env
```

Fill in your values, save the file, then run:

```powershell
py run.py
```

That second `py run.py` starts both servers and opens the app at:

```text
http://localhost:5173
```

If `5173` or `8000` is already in use, the launcher prints the fallback ports it selected and opens the matching URL.

Keep that terminal open while using BudgetBeagle. Press `Ctrl+C` in the terminal to stop the backend and frontend.

## How To Fill `backend/.env`

The first run creates `backend/.env` from `backend/.env.example`.

Example:

```env
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=your-secret-access-key
AWS_DEFAULT_REGION=us-east-1
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-120b
JWT_SECRET=replace-this-with-a-long-random-secret
DATABASE_URL=sqlite:///./cost_detective.db
BUDGETBEAGLE_ENABLE_COST_EXPLORER=true
# Optional: BUDGETBEAGLE_BACKEND_PORT=8000
# Optional: BUDGETBEAGLE_FRONTEND_PORT=5173
```

What each value means:

| Variable | Required? | What to put |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | Usually yes for local beginners | Your IAM user's access key ID |
| `AWS_SECRET_ACCESS_KEY` | Usually yes for local beginners | Your IAM user's secret access key |
| `AWS_DEFAULT_REGION` | Yes | The default AWS region, for example `us-east-1`, `us-west-2`, or `ap-south-1` |
| `GROQ_API_KEY` | No | Optional Groq API key for explanation rewriting only |
| `GROQ_MODEL` | No | Optional model override when `GROQ_API_KEY` is set |
| `JWT_SECRET` | Yes | Any long random secret string used to sign local login tokens |
| `DATABASE_URL` | No for normal local use | Keep SQLite unless you want Postgres |
| `BUDGETBEAGLE_ENABLE_COST_EXPLORER` | No | Keep `true` to collect account billing context when IAM allows `ce:GetCostAndUsage`; set `false` to skip billing collection |
| `BUDGETBEAGLE_BACKEND_PORT` | No | Optional local backend port; the launcher uses the next open port if this one is busy |
| `BUDGETBEAGLE_FRONTEND_PORT` | No | Optional local frontend port; the launcher opens the actual selected URL |

You can generate a `JWT_SECRET` with this PowerShell command:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not commit `backend/.env` to GitHub. It contains secrets.

## How To Get A Groq API Key

1. Go to [Groq Console API Keys](https://console.groq.com/keys).
2. Sign in or create a Groq account.
3. Create a new API key.
4. Copy the key.
5. Paste it into `backend/.env`:

```env
GROQ_API_KEY=your-groq-api-key
```

The default model is:

```env
GROQ_MODEL=openai/gpt-oss-120b
```

If Groq changes model availability, check [Groq model documentation](https://console.groq.com/docs/models), choose an available model, and update `GROQ_MODEL`.

## How To Get AWS Access Keys

Recommended beginner path:

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/).
2. Open [IAM Users](https://console.aws.amazon.com/iam/home#/users).
3. Create a new IAM user, or choose an existing non-root IAM user.
4. Attach read-only permissions. For testing, [ReadOnlyAccess](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ReadOnlyAccess.html) is simple. For tighter permissions, use the custom policy in [AWS Permissions](#aws-permissions).
5. Open the IAM user.
6. Go to the user's security credentials.
7. Create an access key for local application or CLI use.
8. Copy the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
9. Paste both into `backend/.env`.

Use these official AWS references if you want the detailed AWS screens:

- [Create an IAM user](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html)
- [Manage access keys for IAM users](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html)
- [AWS IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [AWS shared credentials file](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)

Security tips:

- Do not use your AWS root account access keys.
- Prefer a dedicated IAM user or IAM role for this app.
- Give the app read-only permissions.
- Delete or rotate keys you no longer use.
- Never paste AWS keys into chat, screenshots, GitHub issues, or commits.

## How To Use The App

1. Run the app:

```powershell
py run.py
```

2. Open the frontend URL printed by the launcher if it does not open automatically. It is normally `http://localhost:5173`.
3. Create an account on the signup page. This is local app authentication, not your AWS account.
4. Choose an AWS region.
5. Optionally choose an AWS Resource Group.
6. Start the scan.
7. Watch the progress messages.
8. Open the generated report.
9. Review every issue, estimated saving, explanation, and fix command.
10. Copy a command only after you understand what it will do.

## What The Report Means

Each report is organized into tabs:

| Report area | Meaning |
| --- | --- |
| Overview | Account/region scan summary, confidence score, warning summary, and top-level optimization counts |
| Billing | Cost Explorer YTD account total, selected-region spend, monthly account costs, service costs, and billed regions when available |
| Findings | Deterministic issues, recommendations, and observations with evidence, pricing basis, savings basis, confidence, and action risk |
| Resources | The scanned AWS inventory with service, resource ID, type, state, and key scalar metrics |
| Commands | Backend-validated `aws` CLI commands only when enough evidence exists and service constraints are satisfied |
| Warnings | Permission or inspection gaps such as denied lifecycle or Cost Explorer checks |

Savings are shown only when the backend has numeric, evidence-backed data. Unknown or unsupported savings are displayed as `Not enough data`. Confidence scores are derived from finding confidence, scan warnings, and whether billing context was available.

Treat the report as a decision aid. For example, an "idle" resource might still be important if it is used during month-end processing, disaster recovery, demos, or low-traffic production windows.

## AWS Permissions

BudgetBeagle needs permission to describe and list resources. It does not need write permissions to scan.

### Minimal Core Scan Policy

This is the minimum policy required for BudgetBeagle to scan resources, collect CloudWatch metrics, and generate findings:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BudgetBeagleCoreScan",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:Describe*",
        "rds:Describe*",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "elasticloadbalancing:Describe*",
        "resource-groups:ListGroups",
        "resource-groups:ListGroupResources",
        "tag:GetResources"
      ],
      "Resource": "*"
    }
  ]
}
```

### Extended Read-Only Enrichment Policy (Recommended)

This adds optional permissions that improve report quality. Missing optional permissions produce **warnings, not failures** — your scan will still complete.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BudgetBeagleCoreScan",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:Describe*",
        "rds:Describe*",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "elasticloadbalancing:Describe*",
        "resource-groups:ListGroups",
        "resource-groups:ListGroupResources",
        "tag:GetResources"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BudgetBeagleOptionalEnrichment",
      "Effect": "Allow",
      "Action": [
        "s3:GetLifecycleConfiguration",
        "ce:GetCostAndUsage"
      ],
      "Resource": "*"
    }
  ]
}
```

### What each optional permission does

| Permission | What it enables | If missing |
| --- | --- | --- |
| `s3:GetLifecycleConfiguration` | Verifies whether S3 buckets have lifecycle policies configured | Lifecycle status shows as "Unknown" with a warning |
| `ce:GetCostAndUsage` | Retrieves AWS Cost Explorer billing data for account and region spend summaries | Billing tab shows "unavailable" with a warning |

### How to add optional permissions

1. Open the [IAM Console](https://console.aws.amazon.com/iam/).
2. Find the IAM user or role used by BudgetBeagle.
3. Open the attached policy (or create a new inline policy).
4. Add the optional actions listed above to the policy's `Action` array.
5. Save the policy.
6. Run the scan again in BudgetBeagle — the dashboard will show updated permission status.

### Scoped S3 permissions

If you want to restrict lifecycle checks to specific buckets:

```json
{
  "Sid": "BudgetBeagleScopedS3Lifecycle",
  "Effect": "Allow",
  "Action": "s3:GetLifecycleConfiguration",
  "Resource": "arn:aws:s3:::your-bucket-name"
}
```

If a service is denied, BudgetBeagle tries to keep scanning the services it can access and records the scanner error or warning in the analysis payload. If Cost Explorer is denied, inventory scanning still works and the Billing tab explains that account spend could not be verified.

### Debug mode

Set `DEBUG_AWS_ERRORS=true` in `backend/.env` to log detailed AWS error information to the server console during development. Secrets are never logged regardless of this setting. The default is `false`.

## Other Ways To Run

### Docker

Create `backend/.env` first:

```powershell
Copy-Item backend\.env.example backend\.env
```

Fill in `backend/.env`, then run:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:5173
```

### Manual Backend And Frontend

Backend:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Fill in .env before starting the API
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Frontend, in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `python run.py` does not work on Windows | Use `py run.py` instead. Your Windows Python launcher works even when the `python` alias is broken. |
| `start.bat` does not work | Use `py run.py`. The batch file calls `python run.py`, so it has the same PATH problem. |
| `Node.js 18+ is required` | Install Node.js from [nodejs.org](https://nodejs.org/), close the terminal, open a new terminal, and run `py run.py` again. |
| Optional AI wording is missing | Add `GROQ_API_KEY` to `backend/.env` only if you want Groq-generated explanation rewrites. |
| `JWT_SECRET is not configured` | Replace the placeholder `JWT_SECRET` in `backend/.env` with a long random string. |
| AWS authentication error | Check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, region, and IAM permissions. |
| Region list fails to load | Your AWS credentials may not have `ec2:DescribeRegions`, or the credentials are invalid. |
| Port already in use | The launcher now checks `5173` and `8000`, then uses the next open ports and prints the exact URLs. To force a port, set `BUDGETBEAGLE_FRONTEND_PORT` or `BUDGETBEAGLE_BACKEND_PORT` in `backend/.env`. |
| Groq model error | Check [Groq model documentation](https://console.groq.com/docs/models) and update `GROQ_MODEL` in `backend/.env`. |

## Project Structure

```text
BudgetBeagle/
  run.py                  # Recommended launcher. On Windows run: py run.py
  start.bat               # Uses python run.py; may fail if python is not on PATH
  docker-compose.yml      # Docker backend/frontend setup
  backend/
    main.py               # FastAPI routes, auth, scan jobs, WebSocket progress
    aws_scanner.py        # boto3 AWS inventory, CloudWatch, and billing scanner
    billing.py            # AWS Cost Explorer billing context collector
    cost_rules.py         # deterministic findings, confidence, totals, warnings, and commands
    pricing.py            # AWS Pricing API resolver
    ai_analyzer.py        # deterministic report entry point plus optional Groq wording
    db.py                 # SQLAlchemy models and persistence
    .env.example          # Template used to create backend/.env
  frontend/
    src/                  # React app pages and components
```

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT. See [LICENSE](./LICENSE).
