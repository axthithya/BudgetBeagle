# IAM Permissions

BudgetBeagle uses read-only access to AWS to identify cost savings.
No mutation or auto-remediation permissions are used or requested.

### Required Core Permissions
- `sts:GetCallerIdentity`
- `ec2:DescribeInstances`
- `ec2:DescribeVolumes`
- `ec2:DescribeAddresses`
- `ec2:DescribeNatGateways`
- `ec2:DescribeRegions`
- `elasticloadbalancing:DescribeLoadBalancers`
- `rds:DescribeDBInstances`
- `s3:ListAllMyBuckets`
- `s3:GetBucketLocation`
- `cloudwatch:GetMetricStatistics`

### Optional Permissions
- `s3:GetLifecycleConfiguration`: Used for detailed S3 lifecycle metrics.
- `ce:GetCostAndUsage`: Used to fetch YTD account and service-level billing data.
