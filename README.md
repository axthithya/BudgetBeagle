# AI Cloud Cost Detective - AWS Edition

An AI agent that scans your own AWS account, finds concrete cost-saving opportunities, and uses Groq to turn real resource inventory plus CloudWatch metrics into prioritized findings and reviewable `aws` CLI fix commands.

This tool only reads AWS data. It never changes your account automatically; generated fix commands are shown for you to review and run yourself.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | React, Vite, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI |
| Auth | Custom JWT auth, bcrypt, PyJWT |
| Cloud Data | AWS SDK for Python, boto3 |
| AI Analysis | Groq API, default `openai/gpt-oss-120b` |
| Database | SQLite by default, Postgres/RDS via `DATABASE_URL` |
| Live Updates | FastAPI WebSocket |

## Architecture

```text
User
  |
  v
React frontend
  |  login/signup, JWT
  v
FastAPI backend
  |-- boto3 scanner -> AWS account
  |-- WebSocket progress -> React progress tracker
  |-- Groq analysis -> structured cost report
  `-- SQLAlchemy -> SQLite or Postgres
                         |
                         v
              History and final report UI
```

See [Architecture.MD](./Architecture.MD) for the full architecture notes.

## Request Flow

```text
1. User signs up or logs in, receiving a JWT.
2. User selects an AWS region and optionally an AWS Resource Group.
3. FastAPI scans EC2, EBS, RDS, S3, ELB, EIP, NAT Gateway, and CloudWatch metrics with boto3.
4. Progress streams to React over WebSocket.
5. The resource and metrics payload is analyzed by Groq.
6. SQLAlchemy stores the full analysis result.
7. React renders the report, issue cards, estimated savings, history, and copyable fix commands.
```

See [RequestFlow.MD](./RequestFlow.MD) for the short flow reference.

## What It Detects

- Idle or low-utilization EC2 instances and RDS databases
- Unattached EBS volumes
- Unassociated Elastic IPs
- Idle load balancers
- Always-on NAT Gateway cost exposure
- Dev/test RDS instances with unnecessary Multi-AZ
- Storage tier and database configuration concerns
- S3 buckets missing lifecycle policies

## Quick Start

Repository: [axthithya/BudgetBeagle](https://github.com/axthithya/BudgetBeagle)

```bash
git clone https://github.com/axthithya/BudgetBeagle.git
cd BudgetBeagle
```

### Option A: native launcher

Mac/Linux:

```bash
./start.sh
```

Windows CMD or PowerShell:

```bat
start.bat
```

Any platform with Python on PATH:

```bash
python run.py
```

On the first run, the launcher creates `backend/.env` and exits. Fill in `GROQ_API_KEY`, replace `JWT_SECRET`, and add AWS credentials if you are not using an existing AWS profile or IAM role. Then run the same launcher command again.

### Option B: Docker

```bash
cp backend/.env.example backend/.env
# edit backend/.env first
docker compose up --build
```

The frontend runs at `http://localhost:5173` and the API runs at `http://localhost:8000`.

### Option C: manual

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

Root and backend examples are provided in `.env.example` and `backend/.env.example`.

| Variable | Purpose |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | Optional AWS credential, if not using profile/role |
| `AWS_SECRET_ACCESS_KEY` | Optional AWS credential, if not using profile/role |
| `AWS_DEFAULT_REGION` | Default region for SDK calls |
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Groq model name |
| `JWT_SECRET` | Secret used to sign app JWTs |
| `DATABASE_URL` | SQLAlchemy URL, defaults to SQLite |

## AWS Permissions

Use a read-only IAM user or role. A practical least-privilege starting point:

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

## Screenshots

Add screenshots or a GIF after your first real account scan.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT. See [LICENSE](./LICENSE).