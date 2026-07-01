# IAM Permissions

BudgetBeagle uses read-only AWS access to identify cost savings. It never creates IAM resources, enables paid recommendation services, or modifies AWS infrastructure.

## Required Core Permissions

- `sts:GetCallerIdentity`
- `ec2:DescribeRegions`
- `ec2:DescribeInstances`
- `ec2:DescribeVolumes`
- `ec2:DescribeAddresses`
- `ec2:DescribeNatGateways`
- `elasticloadbalancing:DescribeLoadBalancers`
- `elasticloadbalancing:DescribeTargetGroups`
- `elasticloadbalancing:DescribeTags`
- `rds:DescribeDBInstances`
- `rds:ListTagsForResource`
- `s3:ListAllMyBuckets`
- `s3:GetBucketLocation`
- `cloudwatch:GetMetricStatistics`
- `cloudwatch:GetMetricData`
- `cloudwatch:ListMetrics`

`ec2:DescribeRegions` is required for the all-enabled-regions selector and for refreshing the region list. If it is denied, single-region scans can still work when a valid region is supplied, but all-enabled region resolution is blocked and the UI shows a permission-denied state.

## Optional Read-Only Permissions

- `s3:GetLifecycleConfiguration`: verifies whether S3 buckets have lifecycle policies.
- `ce:GetCostAndUsage`: fetches YTD account, service, selected scan-region, and billed-region Cost Explorer data.
- `resource-groups:ListGroups`, `resource-groups:ListGroupResources`, `tag:GetResources`: enable optional AWS Resource Group filtering for single-region scans.

Missing optional permissions produce warnings, not automatic remediation.

## Least-Privilege Example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BudgetBeagleCoreReadOnlyScan",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeNatGateways",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTags",
        "rds:DescribeDBInstances",
        "rds:ListTagsForResource",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BudgetBeagleOptionalReadOnlyEnrichment",
      "Effect": "Allow",
      "Action": [
        "s3:GetLifecycleConfiguration",
        "ce:GetCostAndUsage",
        "resource-groups:ListGroups",
        "resource-groups:ListGroupResources",
        "tag:GetResources"
      ],
      "Resource": "*"
    }
  ]
}
```

## Safety Boundary

BudgetBeagle does not request or use permissions such as `ec2:StopInstances`, `ec2:TerminateInstances`, `rds:ModifyDBInstance`, `s3:PutLifecycleConfiguration`, `iam:*`, or any write action. CLI commands in reports are examples for human review and are never executed by BudgetBeagle.