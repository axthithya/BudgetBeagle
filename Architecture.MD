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
                    boto3 scan|          | Groq chat completion
                              v          v
+-------------------+   +-------------------+   +------------------+
| AWS account       |   | Progress WebSocket|   | Groq API          |
| EC2, EBS, RDS, S3 |   | /ws/progress/{id} |   | Cost analysis     |
| ELB, EIP, NAT, CW |   +---------+---------+   +---------+--------+
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
                         | issues, savings, CLI |
                         +----------------------+
```

## What Changed From The Azure Original

| Layer | Original Azure version | AWS edition |
| --- | --- | --- |
| Cloud data | Azure CLI subprocess calls | boto3 native AWS SDK |
| Scan unit | Azure Resource Group | AWS region, optional AWS Resource Group |
| AI analysis | OpenAI API | Groq API |
| Database | Managed PostgreSQL | SQLite by default, Postgres-ready |
| Setup | Manual backend/frontend setup | `./start.sh` or `docker compose up --build` |

## Backend Responsibilities

- Authenticate app users with custom JWTs.
- Scan AWS resources through the standard AWS credential chain.
- Pull CloudWatch utilization metrics for resource-aware recommendations.
- Degrade gracefully when one AWS service denies read access.
- Send resource and metric payloads to Groq for structured JSON analysis.
- Persist every analysis for the signed-in user.
- Replay progress messages to late WebSocket subscribers.