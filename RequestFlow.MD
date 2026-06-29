# Request Flow

```text
1. User -> React -> FastAPI auth -> JWT stored by the client.
2. User selects an AWS region and optionally an AWS Resource Group.
3. FastAPI -> boto3 -> AWS resources and CloudWatch metrics.
4. FastAPI -> WebSocket -> React progress tracker.
5. FastAPI -> Groq API -> structured cost analysis.
6. FastAPI -> database -> persisted analysis history.
7. React -> final report with suggestions and copyable `aws` CLI commands.
```

The scanner uses read-only AWS calls such as `Describe*`, `List*`, and `Get*` plus CloudWatch metric reads. It does not modify AWS resources.