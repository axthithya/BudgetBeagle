# BudgetBeagle - AI Cloud Cost Detective for AWS

BudgetBeagle is a local web app that scans your AWS account, finds practical cost-saving opportunities, and asks Groq AI to turn the scan results into a clear report with estimated monthly savings and reviewable `aws` CLI fix commands.

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
  -> CloudWatch metrics are collected where available
  -> Groq analyzes the inventory and metrics
  -> the report is saved in SQLite
  -> the frontend shows savings, issues, notes, and copyable commands
```

The app has two parts:

| Part | What it does |
| --- | --- |
| Frontend | React, Vite, TypeScript, Tailwind UI at `http://localhost:5173` |
| Backend | FastAPI API at `http://localhost:8000` |
| AWS Scanner | Uses `boto3` and your AWS credentials to read inventory and CloudWatch metrics |
| AI Analyzer | Uses your Groq API key to generate a structured cost report |
| Database | SQLite by default, with optional Postgres/RDS through `DATABASE_URL` |

More architecture notes are in [Architecture.MD](./Architecture.MD), and the request flow is in [RequestFlow.MD](./RequestFlow.MD).

## Features

- Login and signup with JWT authentication
- AWS region picker
- Optional AWS Resource Group scan filter
- Live progress updates through WebSocket
- Scan history for each signed-in user
- Saved reports you can reopen later
- Estimated monthly savings
- Severity labels for each issue
- Human-readable explanations
- Copyable `aws` CLI fix commands
- Read-only AWS scanning behavior
- SQLite local database by default
- Docker option for users who prefer containers

## Before You Start

Install these first:

1. [Python 3.10 or newer](https://www.python.org/downloads/windows/)
2. [Node.js 18 or newer](https://nodejs.org/)
3. A [Groq API key](https://console.groq.com/keys)
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
```

What each value means:

| Variable | Required? | What to put |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | Usually yes for local beginners | Your IAM user's access key ID |
| `AWS_SECRET_ACCESS_KEY` | Usually yes for local beginners | Your IAM user's secret access key |
| `AWS_DEFAULT_REGION` | Yes | The default AWS region, for example `us-east-1`, `us-west-2`, or `ap-south-1` |
| `GROQ_API_KEY` | Yes | Your Groq API key from [Groq Console](https://console.groq.com/keys) |
| `GROQ_MODEL` | Yes | Keep the default unless Groq model availability changes |
| `JWT_SECRET` | Yes | Any long random secret string used to sign local login tokens |
| `DATABASE_URL` | No for normal local use | Keep SQLite unless you want Postgres |

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

2. Open `http://localhost:5173` if it does not open automatically.
3. Create an account on the signup page. This is local app authentication, not your AWS account.
4. Choose an AWS region.
5. Optionally choose an AWS Resource Group.
6. Start the scan.
7. Watch the progress messages.
8. Open the generated report.
9. Review every issue, estimated saving, explanation, and fix command.
10. Copy a command only after you understand what it will do.

## What The Report Means

Each report can include:

| Report field | Meaning |
| --- | --- |
| Summary | Short explanation of the main findings |
| Resources scanned | Count of AWS resources included in the analysis |
| Issues found | Number of possible savings opportunities |
| Estimated savings | Conservative estimated monthly savings when possible |
| Severity | High, medium, or low priority |
| Explanation | Why the resource may be wasting money |
| Fix command | A suggested `aws` CLI command for you to review |
| Notes | Extra context from the AI analyzer |

Treat the report as a decision aid. For example, an "idle" resource might still be important if it is used during month-end processing, disaster recovery, demos, or low-traffic production windows.

## AWS Permissions

BudgetBeagle needs permission to describe and list resources. It does not need write permissions to scan.

A practical least-privilege starting policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "rds:Describe*",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "s3:GetBucketLifecycleConfiguration",
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

If a service is denied, BudgetBeagle tries to keep scanning the services it can access and records the scanner error in the analysis payload.

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
| `GROQ_API_KEY is not configured` | Add `GROQ_API_KEY` to `backend/.env`, save it, then run `py run.py` again. |
| `JWT_SECRET is not configured` | Replace the placeholder `JWT_SECRET` in `backend/.env` with a long random string. |
| AWS authentication error | Check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, region, and IAM permissions. |
| Region list fails to load | Your AWS credentials may not have `ec2:DescribeRegions`, or the credentials are invalid. |
| Port already in use | Stop the old terminal/server or free ports `5173` and `8000`. |
| Groq model error | Check [Groq model documentation](https://console.groq.com/docs/models) and update `GROQ_MODEL` in `backend/.env`. |

## Project Structure

```text
BudgetBeagle/
  run.py                  # Recommended launcher. On Windows run: py run.py
  start.bat               # Uses python run.py; may fail if python is not on PATH
  docker-compose.yml      # Docker backend/frontend setup
  backend/
    main.py               # FastAPI routes, auth, scan jobs, WebSocket progress
    aws_scanner.py        # boto3 AWS inventory and CloudWatch scanner
    ai_analyzer.py        # Groq analysis logic
    db.py                 # SQLAlchemy models and persistence
    .env.example          # Template used to create backend/.env
  frontend/
    src/                  # React app pages and components
```

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT. See [LICENSE](./LICENSE).
