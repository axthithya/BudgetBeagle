# Request Flow

```text
1. User -> React -> FastAPI auth -> JWT stored by the client.
2. User selects an AWS region and optionally an AWS Resource Group.
3. FastAPI -> boto3 -> AWS resources, CloudWatch metrics, and optional Cost Explorer billing data.
4. FastAPI -> WebSocket -> React progress tracker.
5. FastAPI -> deterministic cost rules -> validated findings, warnings, billing summaries, confidence, savings status, and command templates.
6. Optional FastAPI -> Groq API -> wording for already validated findings.
7. FastAPI -> database -> persisted analysis history.
8. React -> tabbed final report with overview, billing, findings, resources, commands, and scan warnings.
```

The scanner uses read-only AWS calls such as `Describe*`, `List*`, and `Get*` plus CloudWatch and Cost Explorer reads. It does not modify AWS resources.