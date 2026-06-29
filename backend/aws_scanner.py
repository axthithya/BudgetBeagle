from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
)


class ScannerError(Exception):
    """Base scanner exception that is safe to expose to API clients."""


class ScannerAuthError(ScannerError):
    """Raised when AWS credentials are missing or incomplete."""


class ScannerRegionError(ScannerError):
    """Raised when AWS rejects the requested region."""


def _safe_tags(tags: Any) -> dict[str, str]:
    if not tags:
        return {}
    if isinstance(tags, dict):
        return {str(k): str(v) for k, v in tags.items()}
    normalized: dict[str, str] = {}
    for tag in tags:
        key = tag.get("Key") or tag.get("key")
        value = tag.get("Value") or tag.get("value") or ""
        if key:
            normalized[str(key)] = str(value)
    return normalized


def _name_from_tags(tags: dict[str, str]) -> str:
    return tags.get("Name", "")


def _average(datapoints: list[dict[str, Any]], field: str = "Average") -> float | None:
    values = [point.get(field) for point in datapoints if point.get(field) is not None]
    if not values:
        return None
    return round(float(mean(values)), 2)


class AwsScanner:
    def __init__(self, region: str, resource_group: str | None = None):
        self.region = region
        self.resource_group = resource_group
        self.session = boto3.Session(region_name=region)
        self.errors: list[dict[str, str]] = []
        self._resource_group_arns: set[str] | None = None

    @staticmethod
    def enabled_regions() -> list[str]:
        try:
            client = boto3.client("ec2", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
            regions = client.describe_regions(AllRegions=False).get("Regions", [])
            return sorted(region["RegionName"] for region in regions)
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ScannerAuthError("AWS credentials are missing or incomplete.") from exc
        except ClientError as exc:
            raise _client_error_to_scanner_error(exc) from exc

    @staticmethod
    def resource_groups(region: str | None = None) -> list[dict[str, str]]:
        try:
            client = boto3.Session(region_name=region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")).client("resource-groups")
            groups: list[dict[str, str]] = []
            paginator = client.get_paginator("list_groups")
            for page in paginator.paginate():
                for group in page.get("Groups", []):
                    groups.append(
                        {
                            "name": group.get("Name", ""),
                            "arn": group.get("GroupArn", ""),
                            "description": group.get("Description", ""),
                        }
                    )
            return groups
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ScannerAuthError("AWS credentials are missing or incomplete.") from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedException"}:
                return []
            raise _client_error_to_scanner_error(exc) from exc

    def scan(self) -> dict[str, Any]:
        self._validate_credentials()
        self._load_resource_group_scope()

        resources: list[dict[str, Any]] = []
        resources.extend(self._scan_ec2_instances())
        resources.extend(self._scan_ebs_volumes())
        resources.extend(self._scan_elastic_ips())
        resources.extend(self._scan_load_balancers())
        resources.extend(self._scan_rds_instances())
        resources.extend(self._scan_s3_buckets())
        resources.extend(self._scan_nat_gateways())

        return {
            "region": self.region,
            "resource_group": self.resource_group,
            "resources": resources,
            "errors": self.errors,
        }

    def _validate_credentials(self) -> None:
        try:
            self.session.client("sts").get_caller_identity()
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ScannerAuthError("AWS credentials are missing or incomplete.") from exc
        except ClientError as exc:
            raise _client_error_to_scanner_error(exc) from exc

    def _client(self, service: str):
        return self.session.client(service)

    def _record_error(self, service: str, exc: Exception) -> None:
        message = "Unable to scan this service."
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            code = error.get("Code", "ClientError")
            message = error.get("Message", message)
            self.errors.append({"service": service, "code": code, "message": message})
            return
        if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
            self.errors.append(
                {"service": service, "code": "MissingCredentials", "message": "AWS credentials are missing."}
            )
            return
        self.errors.append({"service": service, "code": exc.__class__.__name__, "message": message})

    def _load_resource_group_scope(self) -> None:
        if not self.resource_group:
            self._resource_group_arns = None
            return
        self._resource_group_arns = set()
        try:
            client = self._client("resource-groups")
            paginator = client.get_paginator("list_group_resources")
            for page in paginator.paginate(GroupName=self.resource_group):
                for resource in page.get("ResourceIdentifiers", []):
                    arn = resource.get("ResourceArn")
                    if arn:
                        self._resource_group_arns.add(arn)
        except Exception as exc:  # keep region-wide scans resilient to resource-group permissions
            self._record_error("resource-groups", exc)

    def _in_scope(self, resource_id: str | None = None, resource_arn: str | None = None) -> bool:
        if self._resource_group_arns is None:
            return True
        if not self._resource_group_arns:
            return False
        if resource_arn and resource_arn in self._resource_group_arns:
            return True
        if resource_id:
            return any(resource_id in arn for arn in self._resource_group_arns)
        return False

    def _metric_average(
        self,
        namespace: str,
        metric_name: str,
        dimensions: list[dict[str, str]],
        statistic: str = "Average",
    ) -> float | None:
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=14)
            response = self._client("cloudwatch").get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=[statistic],
            )
            return _average(response.get("Datapoints", []), statistic)
        except Exception as exc:
            self._record_error("cloudwatch", exc)
            return None

    def _scan_ec2_instances(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("ec2")
            paginator = client.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instance_id = instance.get("InstanceId", "")
                        if not self._in_scope(instance_id):
                            continue
                        tags = _safe_tags(instance.get("Tags"))
                        avg_cpu = self._metric_average(
                            "AWS/EC2",
                            "CPUUtilization",
                            [{"Name": "InstanceId", "Value": instance_id}],
                        )
                        state = instance.get("State", {}).get("Name", "unknown")
                        resources.append(
                            {
                                "service": "EC2",
                                "id": instance_id,
                                "name": _name_from_tags(tags),
                                "type_or_sku": instance.get("InstanceType", ""),
                                "state": state,
                                "tags": tags,
                                "metrics": {
                                    "avg_cpu_14d": avg_cpu,
                                    "low_utilization_candidate": state == "running" and avg_cpu is not None and avg_cpu < 10,
                                },
                            }
                        )
        except Exception as exc:
            self._record_error("ec2", exc)
        return resources

    def _scan_ebs_volumes(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("ec2")
            paginator = client.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for volume in page.get("Volumes", []):
                    volume_id = volume.get("VolumeId", "")
                    if not self._in_scope(volume_id):
                        continue
                    tags = _safe_tags(volume.get("Tags"))
                    state = volume.get("State", "unknown")
                    resources.append(
                        {
                            "service": "EBS",
                            "id": volume_id,
                            "name": _name_from_tags(tags),
                            "type_or_sku": volume.get("VolumeType", ""),
                            "state": state,
                            "tags": tags,
                            "metrics": {
                                "size_gb": volume.get("Size"),
                                "iops": volume.get("Iops"),
                                "unattached": state == "available",
                            },
                        }
                    )
        except Exception as exc:
            self._record_error("ebs", exc)
        return resources

    def _scan_elastic_ips(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("ec2")
            for address in client.describe_addresses().get("Addresses", []):
                allocation_id = address.get("AllocationId") or address.get("PublicIp", "")
                if not self._in_scope(allocation_id):
                    continue
                tags = _safe_tags(address.get("Tags"))
                associated = bool(address.get("AssociationId") or address.get("InstanceId") or address.get("NetworkInterfaceId"))
                resources.append(
                    {
                        "service": "ElasticIP",
                        "id": allocation_id,
                        "name": _name_from_tags(tags),
                        "type_or_sku": "public-ipv4",
                        "state": "associated" if associated else "unassociated",
                        "tags": tags,
                        "metrics": {
                            "public_ip": address.get("PublicIp"),
                            "unassociated": not associated,
                        },
                    }
                )
        except Exception as exc:
            self._record_error("elastic-ip", exc)
        return resources

    def _scan_load_balancers(self) -> list[dict[str, Any]]:
        return self._scan_elbv2_load_balancers() + self._scan_classic_load_balancers()

    def _scan_elbv2_load_balancers(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("elbv2")
            paginator = client.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    arn = lb.get("LoadBalancerArn", "")
                    if not self._in_scope(lb.get("LoadBalancerName"), arn):
                        continue
                    tags = self._load_balancer_tags(client, arn)
                    dimension = arn.split(":loadbalancer/")[-1]
                    request_count = self._metric_average(
                        "AWS/ApplicationELB" if lb.get("Type") == "application" else "AWS/NetworkELB",
                        "RequestCount" if lb.get("Type") == "application" else "ProcessedBytes",
                        [{"Name": "LoadBalancer", "Value": dimension}],
                        "Sum",
                    )
                    resources.append(
                        {
                            "service": "ELB",
                            "id": arn,
                            "name": lb.get("LoadBalancerName", ""),
                            "type_or_sku": lb.get("Type", ""),
                            "state": lb.get("State", {}).get("Code", "unknown"),
                            "tags": tags,
                            "metrics": {
                                "request_or_flow_sum_14d": request_count,
                                "idle_candidate": request_count is not None and request_count == 0,
                            },
                        }
                    )
        except Exception as exc:
            self._record_error("elbv2", exc)
        return resources

    def _scan_classic_load_balancers(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("elb")
            paginator = client.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancerDescriptions", []):
                    name = lb.get("LoadBalancerName", "")
                    if not self._in_scope(name):
                        continue
                    request_count = self._metric_average(
                        "AWS/ELB",
                        "RequestCount",
                        [{"Name": "LoadBalancerName", "Value": name}],
                        "Sum",
                    )
                    resources.append(
                        {
                            "service": "ClassicELB",
                            "id": name,
                            "name": name,
                            "type_or_sku": "classic",
                            "state": "active",
                            "tags": {},
                            "metrics": {
                                "request_count_sum_14d": request_count,
                                "idle_candidate": request_count is not None and request_count == 0,
                            },
                        }
                    )
        except Exception as exc:
            self._record_error("classic-elb", exc)
        return resources

    def _load_balancer_tags(self, client: Any, arn: str) -> dict[str, str]:
        try:
            descriptions = client.describe_tags(ResourceArns=[arn]).get("TagDescriptions", [])
            if not descriptions:
                return {}
            return _safe_tags(descriptions[0].get("Tags"))
        except Exception as exc:
            self._record_error("elbv2-tags", exc)
            return {}

    def _scan_rds_instances(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("rds")
            paginator = client.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    arn = db.get("DBInstanceArn", "")
                    identifier = db.get("DBInstanceIdentifier", "")
                    if not self._in_scope(identifier, arn):
                        continue
                    tags = self._rds_tags(client, arn)
                    avg_cpu = self._metric_average(
                        "AWS/RDS",
                        "CPUUtilization",
                        [{"Name": "DBInstanceIdentifier", "Value": identifier}],
                    )
                    resources.append(
                        {
                            "service": "RDS",
                            "id": identifier,
                            "name": identifier,
                            "type_or_sku": db.get("DBInstanceClass", ""),
                            "state": db.get("DBInstanceStatus", "unknown"),
                            "tags": tags,
                            "metrics": {
                                "avg_cpu_14d": avg_cpu,
                                "multi_az": db.get("MultiAZ", False),
                                "storage_type": db.get("StorageType"),
                                "allocated_storage_gb": db.get("AllocatedStorage"),
                                "low_utilization_candidate": avg_cpu is not None and avg_cpu < 10,
                            },
                        }
                    )
        except Exception as exc:
            self._record_error("rds", exc)
        return resources

    def _rds_tags(self, client: Any, arn: str) -> dict[str, str]:
        if not arn:
            return {}
        try:
            return _safe_tags(client.list_tags_for_resource(ResourceName=arn).get("TagList", []))
        except Exception as exc:
            self._record_error("rds-tags", exc)
            return {}

    def _scan_s3_buckets(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("s3")
            for bucket in client.list_buckets().get("Buckets", []):
                name = bucket.get("Name", "")
                bucket_region = self._bucket_region(client, name)
                if bucket_region != self.region or not self._in_scope(name):
                    continue
                has_lifecycle = self._bucket_has_lifecycle(client, name)
                size_bytes = self._metric_average(
                    "AWS/S3",
                    "BucketSizeBytes",
                    [
                        {"Name": "BucketName", "Value": name},
                        {"Name": "StorageType", "Value": "StandardStorage"},
                    ],
                )
                resources.append(
                    {
                        "service": "S3",
                        "id": name,
                        "name": name,
                        "type_or_sku": "bucket",
                        "state": "active",
                        "tags": {},
                        "metrics": {
                            "bucket_size_bytes": size_bytes,
                            "has_lifecycle_policy": has_lifecycle,
                            "missing_lifecycle_policy": not has_lifecycle,
                        },
                    }
                )
        except Exception as exc:
            self._record_error("s3", exc)
        return resources

    def _bucket_region(self, client: Any, bucket_name: str) -> str | None:
        try:
            location = client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
            if location in {None, ""}:
                return "us-east-1"
            if location == "EU":
                return "eu-west-1"
            return location
        except Exception as exc:
            self._record_error("s3-location", exc)
            return None

    def _bucket_has_lifecycle(self, client: Any, bucket_name: str) -> bool:
        try:
            client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchLifecycleConfiguration", "NoSuchLifecycle"}:
                return False
            self._record_error("s3-lifecycle", exc)
            return False

    def _scan_nat_gateways(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            client = self._client("ec2")
            paginator = client.get_paginator("describe_nat_gateways")
            for page in paginator.paginate():
                for nat in page.get("NatGateways", []):
                    nat_id = nat.get("NatGatewayId", "")
                    if not self._in_scope(nat_id):
                        continue
                    tags = _safe_tags(nat.get("Tags"))
                    resources.append(
                        {
                            "service": "NATGateway",
                            "id": nat_id,
                            "name": _name_from_tags(tags),
                            "type_or_sku": "nat-gateway",
                            "state": nat.get("State", "unknown"),
                            "tags": tags,
                            "metrics": {
                                "review_hourly_charge": True,
                                "subnet_id": nat.get("SubnetId"),
                                "vpc_id": nat.get("VpcId"),
                            },
                        }
                    )
        except Exception as exc:
            self._record_error("nat-gateway", exc)
        return resources


def _client_error_to_scanner_error(exc: ClientError) -> ScannerError:
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    message = error.get("Message", "AWS rejected the request.")
    if code in {"AuthFailure", "UnrecognizedClientException", "InvalidClientTokenId", "AccessDenied"}:
        return ScannerAuthError(message)
    if code in {"InvalidRegion", "InvalidEndpoint", "OptInRequired"}:
        return ScannerRegionError(message)
    return ScannerError(message)

