from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from pricing import Ec2PriceResolver, PricingQuote


MONTHLY_HOURS = 730
GP3_BASELINE_IOPS = 3000
GP3_BASELINE_THROUGHPUT_MIBPS = 125
GP3_MIN_IOPS = 3000
GP3_MAX_IOPS = 80000
GP3_MIN_THROUGHPUT_MIBPS = 125
GP3_MAX_THROUGHPUT_MIBPS = 2000


def build_cost_report(
    scan_result: dict[str, Any],
    pricing_resolver: Any | None = None,
) -> dict[str, Any]:
    resolver = pricing_resolver or Ec2PriceResolver()
    region = str(scan_result.get("region") or "")
    resources = scan_result.get("resources", [])
    billing = scan_result.get("billing") if isinstance(scan_result.get("billing"), dict) else {}
    findings: list[dict[str, Any]] = []
    warnings = _scan_warnings(scan_result)

    for resource in resources:
        service = str(resource.get("service") or "").upper()
        if service == "EC2":
            findings.extend(_ec2_findings(resource, region, resolver))
        elif service == "EBS":
            findings.extend(_ebs_findings(resource, region))
        elif service == "S3":
            s3_findings, s3_warnings = _s3_findings_and_warnings(resource)
            findings.extend(s3_findings)
            warnings.extend(_new_warnings(warnings, s3_warnings))
        elif service == "ELASTICIP":
            findings.extend(_elastic_ip_findings(resource, region))
        elif service in {"ELB", "CLASSICELB"}:
            findings.extend(_load_balancer_findings(resource))
        elif service == "NATGATEWAY":
            findings.extend(_nat_gateway_findings(resource))
        elif service == "RDS":
            findings.extend(_rds_findings(resource))

    total = _total_savings(findings)
    max_avoidable = _total_maximum_avoidable_cost(findings)
    confirmed_issues = sum(1 for item in findings if item.get("category") == "Issue")
    recommendations = sum(1 for item in findings if item.get("category") == "Recommendation")
    observations = sum(1 for item in findings if item.get("category") == "Observation")
    confidence = _overall_confidence(findings, warnings, billing)
    yearly_savings = _annualized(total["amount_usd"])
    monthly_account_average = _period_average(billing.get("account_total_ytd_usd"), billing)
    monthly_region_average = _period_average(billing.get("selected_region_ytd_usd"), billing)
    status = "completed_with_warnings" if warnings else "completed"

    return {
        "status": status,
        "summary": _summary(len(resources), confirmed_issues, recommendations, len(warnings), total, max_avoidable),
        "issues": findings,
        "findings": findings,
        "warnings": warnings,
        "billing": billing,
        "notes": [],
        "estimated_monthly_savings": total["amount_usd"],
        "estimated_monthly_savings_display": total["display"],
        "potential_monthly_savings": total,
        "potential_maximum_avoidable_cost": max_avoidable,
        "yearly_savings": yearly_savings,
        "confidence": confidence,
        "metrics": {
            "account_total_ytd_usd": billing.get("account_total_ytd_usd"),
            "account_total_ytd_display": format_money(billing.get("account_total_ytd_usd")),
            "selected_region_ytd_usd": billing.get("selected_region_ytd_usd"),
            "selected_region_ytd_display": format_money(billing.get("selected_region_ytd_usd")),
            "monthly_account_average_usd": monthly_account_average,
            "monthly_account_average_display": format_monthly_savings(monthly_account_average),
            "monthly_region_average_usd": monthly_region_average,
            "monthly_region_average_display": format_monthly_savings(monthly_region_average),
            "monthly_savings_display": total["display"],
            "yearly_savings_display": yearly_savings["display"],
            "confidence_score": confidence["score"],
            "confidence_label": confidence["label"],
            "unutilized_count": confirmed_issues + recommendations,
        },
        "resources_scanned": len(resources),
        "issues_found": confirmed_issues,
        "confirmed_issues": confirmed_issues,
        "recommendations": recommendations,
        "observations": observations,
        "warnings_count": len(warnings),
    }


def format_monthly_savings(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "Not enough data"
    return f"${numeric:.2f}/month"


def format_money(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "Not enough data"
    return f"${numeric:.2f}"


def build_gp3_modify_command(
    *,
    region: str,
    volume_id: str,
    target_iops: int,
    target_throughput_mibps: int,
) -> dict[str, Any] | None:
    if not _valid_gp3_iops(target_iops) or not _valid_gp3_throughput(target_throughput_mibps):
        return None
    return {
        "text": (
            f"aws ec2 modify-volume --region {region} --volume-id {volume_id} "
            f"--volume-type gp3 --iops {target_iops} --throughput {target_throughput_mibps}"
        ),
        "risk": "reversible",
        "risk_label": "Reversible, but may affect workload disk performance.",
        "operation": "modify",
        "valid": True,
    }


def _ec2_findings(resource: dict[str, Any], region: str, pricing_resolver: Any) -> list[dict[str, Any]]:
    state = str(resource.get("state") or "").lower()
    if state != "running":
        return []

    metrics = _metrics(resource)
    cpu = _cpu_summary(metrics)
    avg_cpu = _to_float(cpu.get("average"))
    datapoints = int(_to_float(cpu.get("datapoint_count")) or 0)
    observed_hours = _to_float(cpu.get("actual_duration_hours")) or 0.0
    threshold = _env_float("BUDGETBEAGLE_EC2_CPU_THRESHOLD_PERCENT", 10.0)
    min_datapoints = _env_int("BUDGETBEAGLE_EC2_MIN_DATAPOINTS", 24)
    min_hours = _env_float("BUDGETBEAGLE_EC2_MIN_OBSERVATION_HOURS", 24.0)

    if avg_cpu is None or datapoints == 0 or avg_cpu >= threshold:
        return []

    sufficient = datapoints >= min_datapoints and observed_hours >= min_hours
    confidence = "medium" if sufficient else "low"
    category = "Recommendation" if sufficient else "Observation"
    command = _ec2_stop_command(region, _resource_id(resource)) if sufficient else None
    quote = _quote_ec2(pricing_resolver, region, str(resource.get("type_or_sku") or ""))
    max_cost = round(quote.hourly_usd * MONTHLY_HOURS, 2) if quote.status == "verified" and quote.hourly_usd is not None else None
    observed_phrase = "based on available data since launch" if _recent_launch(cpu) else "based on available CloudWatch datapoints"

    return [
        _finding(
            category=category,
            service="EC2",
            resource_id=_resource_id(resource),
            issue_type="Low EC2 CPU utilization review candidate",
            severity="medium" if sufficient else "low",
            confidence=confidence,
            explanation=(
                f"Average CPU was {avg_cpu:.2f}% {observed_phrase}. This is a review candidate, "
                "not proof that stopping or downsizing is safe."
            ),
            evidence={
                "Metric source": cpu.get("metric_source") or "CloudWatch",
                "Metric name": cpu.get("metric_name") or "CPUUtilization",
                "Average value": f"{avg_cpu:.2f}%",
                "Minimum value": _percent_or_unknown(cpu.get("minimum")),
                "Maximum value": _percent_or_unknown(cpu.get("maximum")),
                "Datapoint count": datapoints,
                "Start timestamp": cpu.get("actual_start") or "No datapoints",
                "End timestamp": cpu.get("actual_end") or "No datapoints",
                "Instance launch time": cpu.get("instance_launch_time") or metrics.get("launch_time") or "Unknown",
                "Requested analysis window": f"{cpu.get('requested_window_days') or _env_int('BUDGETBEAGLE_EC2_ANALYSIS_WINDOW_DAYS', 14)} days",
                "Actual covered duration": _format_hours(observed_hours),
                "Threshold used": f"Average CPU below {threshold:.2f}%",
                "Confidence level": confidence.capitalize(),
            },
            pricing_status=quote.status,
            pricing_source=quote.source,
            pricing_basis=quote.basis,
            savings_basis="Likely savings are unknown because expected stopped or downsized hours are unknown.",
            estimated_monthly_savings=None,
            recommendation=(
                "Continue monitoring before stopping or downsizing this instance."
                if not sufficient
                else "Review workload ownership and schedules before stopping or downsizing this instance."
            ),
            action_risk=command["risk_label"] if command else "No command generated because observation evidence is insufficient.",
            command=command,
            extra={
                "maximum_monthly_avoidable_cost_usd": max_cost,
                "maximum_monthly_avoidable_cost_display": format_monthly_savings(max_cost),
            },
        )
    ]


def _ebs_findings(resource: dict[str, Any], region: str) -> list[dict[str, Any]]:
    metrics = _metrics(resource)
    volume_id = _resource_id(resource)
    volume_type = str(resource.get("type_or_sku") or "").lower()
    state = str(resource.get("state") or "").lower()
    unattached = state == "available" or bool(metrics.get("unattached"))

    if unattached:
        command = {
            "text": f"aws ec2 delete-volume --region {region} --volume-id {volume_id}",
            "risk": "destructive",
            "risk_label": "Destructive. Create and verify a snapshot first.",
            "operation": "delete",
            "valid": True,
        }
        return [
            _finding(
                category="Issue",
                service="EBS",
                resource_id=volume_id,
                issue_type="Unattached EBS volume",
                severity="high",
                confidence="high",
                explanation="The volume is in available state and is not attached to an instance.",
                evidence={
                    "Volume type": volume_type or "Unknown",
                    "Volume state": state or "Unknown",
                    "Size": _gb_or_unknown(metrics.get("size_gb")),
                    "Attached": "No",
                },
                pricing_status="unavailable",
                pricing_source=None,
                pricing_basis="Current regional EBS storage price could not be verified.",
                savings_basis="Unattached storage is deterministic waste, but monthly storage cost was not priced.",
                estimated_monthly_savings=None,
                recommendation="Create and verify a snapshot, then delete the unattached volume if it is no longer needed.",
                action_risk=command["risk_label"],
                command=command,
            )
        ]

    if volume_type != "gp3":
        return []

    iops = _to_int(metrics.get("iops"))
    throughput = _to_int(metrics.get("throughput_mibps") or metrics.get("throughput"))
    additional_iops = max((iops or GP3_BASELINE_IOPS) - GP3_BASELINE_IOPS, 0)
    additional_throughput = max((throughput or GP3_BASELINE_THROUGHPUT_MIBPS) - GP3_BASELINE_THROUGHPUT_MIBPS, 0)
    if additional_iops == 0 and additional_throughput == 0:
        return []

    target_iops = max(GP3_MIN_IOPS, min(iops or GP3_MIN_IOPS, GP3_BASELINE_IOPS))
    target_throughput = max(
        GP3_MIN_THROUGHPUT_MIBPS,
        min(throughput or GP3_MIN_THROUGHPUT_MIBPS, GP3_BASELINE_THROUGHPUT_MIBPS),
    )
    command = build_gp3_modify_command(
        region=region,
        volume_id=volume_id,
        target_iops=target_iops,
        target_throughput_mibps=target_throughput,
    )
    return [
        _finding(
            category="Recommendation",
            service="EBS",
            resource_id=volume_id,
            issue_type="Additional gp3 provisioned performance",
            severity="low",
            confidence="medium",
            explanation=(
                "This gp3 volume is configured above the included 3,000 IOPS or 125 MiB/s baseline. "
                "The additional performance should be reviewed against workload disk metrics."
            ),
            evidence={
                "Volume type": "gp3",
                "Volume state": state or "Unknown",
                "Size": _gb_or_unknown(metrics.get("size_gb")),
                "Configured IOPS": iops if iops is not None else "Unknown",
                "Included IOPS baseline": GP3_BASELINE_IOPS,
                "Additional IOPS": additional_iops,
                "Configured throughput": f"{throughput} MiB/s" if throughput is not None else "Unknown",
                "Included throughput baseline": f"{GP3_BASELINE_THROUGHPUT_MIBPS} MiB/s",
                "Additional throughput": f"{additional_throughput} MiB/s",
            },
            pricing_status="unavailable",
            pricing_source=None,
            pricing_basis="Regional gp3 provisioned-performance pricing was not verified.",
            savings_basis="Additional gp3 performance was detected, but no savings are claimed without verified pricing and utilization.",
            estimated_monthly_savings=None,
            recommendation="Review disk throughput and IOPS metrics before reducing provisioned gp3 performance.",
            action_risk=command["risk_label"] if command else "No valid gp3 modify command was generated.",
            command=command,
        )
    ]


def _s3_findings_and_warnings(resource: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metrics = _metrics(resource)
    status = _lifecycle_status(metrics)
    bucket = _resource_id(resource)
    if status == "unknown":
        return [], [_s3_lifecycle_unknown_warning(bucket, metrics)]
    if status == "present":
        return [], []
    if status != "absent":
        return [], []

    size_bytes = _to_float(metrics.get("bucket_size_bytes"))
    object_count = _to_float(metrics.get("object_count"))
    empty = object_count == 0 or (object_count is None and size_bytes == 0)
    savings = 0.0 if empty else None
    return [
        _finding(
            category="Recommendation",
            service="S3",
            resource_id=bucket,
            issue_type="S3 lifecycle policy review",
            severity="low",
            confidence="high" if empty else "low",
            explanation=(
                "The bucket is empty, so there is currently no storage cost to optimize. "
                "A lifecycle policy may be useful if objects are added later."
                if empty
                else "No lifecycle policy was found, but savings cannot be calculated without object age, storage class, and transition data."
            ),
            evidence={
                "Lifecycle status": "Absent",
                "Stored bytes": int(size_bytes) if size_bytes is not None else "Unknown",
                "Object count": int(object_count) if object_count is not None else "Unknown",
                "Current storage state": "Empty" if empty else "Data incomplete",
            },
            pricing_status="not_applicable" if empty else "unavailable",
            pricing_source=None,
            pricing_basis="No current S3 storage savings exist for an empty bucket." if empty else "S3 savings require storage class, age distribution, region, and transition cost data.",
            savings_basis="Bucket is empty." if empty else "Not enough data to calculate lifecycle transition savings.",
            estimated_monthly_savings=savings,
            recommendation="Consider adding a lifecycle policy only when object retention requirements are known.",
            action_risk="No command generated because no validated lifecycle transition was selected.",
            command=None,
        )
    ], []


def _elastic_ip_findings(resource: dict[str, Any], region: str) -> list[dict[str, Any]]:
    metrics = _metrics(resource)
    if not metrics.get("unassociated"):
        return []
    command = {
        "text": f"aws ec2 release-address --region {region} --allocation-id {_resource_id(resource)}",
        "risk": "destructive",
        "risk_label": "Destructive. Releasing an Elastic IP may make the public IP unrecoverable.",
        "operation": "release",
        "valid": True,
    }
    return [
        _finding(
            category="Issue",
            service="ElasticIP",
            resource_id=_resource_id(resource),
            issue_type="Unassociated Elastic IP",
            severity="medium",
            confidence="high",
            explanation="The Elastic IP is allocated but not associated with an instance or network interface.",
            evidence={"Associated": "No", "Public IP": metrics.get("public_ip") or "Unknown"},
            pricing_status="unavailable",
            pricing_source=None,
            pricing_basis="Current public IPv4 hourly price was not verified.",
            savings_basis="The IP is unused, but no savings are claimed without verified pricing.",
            estimated_monthly_savings=None,
            recommendation="Release the address only after confirming it is not reserved for failover or DNS.",
            action_risk=command["risk_label"],
            command=command,
        )
    ]


def _load_balancer_findings(resource: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = _metrics(resource)
    if not metrics.get("idle_candidate"):
        return []
    return [
        _finding(
            category="Recommendation",
            service=str(resource.get("service") or "ELB"),
            resource_id=_resource_id(resource),
            issue_type="Idle load balancer review",
            severity="medium",
            confidence="medium",
            explanation="CloudWatch traffic metrics indicate no recent traffic for this load balancer.",
            evidence={"Request or flow metric": metrics.get("request_or_flow_sum_14d", metrics.get("request_count_sum_14d", "Unknown"))},
            pricing_status="unavailable",
            pricing_source=None,
            pricing_basis="Current load balancer pricing was not verified.",
            savings_basis="No savings are claimed without verified pricing.",
            estimated_monthly_savings=None,
            recommendation="Review target groups, DNS, and traffic history before deleting or consolidating this load balancer.",
            action_risk="No command generated because delete impact was not validated.",
            command=None,
        )
    ]


def _nat_gateway_findings(resource: dict[str, Any]) -> list[dict[str, Any]]:
    if not _metrics(resource).get("review_hourly_charge"):
        return []
    return [
        _finding(
            category="Observation",
            service="NATGateway",
            resource_id=_resource_id(resource),
            issue_type="NAT Gateway hourly charge review",
            severity="low",
            confidence="low",
            explanation="NAT Gateways have hourly and data processing charges. No waste is confirmed without traffic and architecture context.",
            evidence={"State": resource.get("state") or "Unknown"},
            pricing_status="unavailable",
            pricing_source=None,
            pricing_basis="Current NAT Gateway pricing was not verified.",
            savings_basis="No savings are claimed without traffic and architecture evidence.",
            estimated_monthly_savings=None,
            recommendation="Review whether private subnets need this NAT Gateway and whether endpoints can reduce data processing charges.",
            action_risk="No command generated because deleting NAT can break outbound connectivity.",
            command=None,
        )
    ]


def _rds_findings(resource: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = _metrics(resource)
    findings: list[dict[str, Any]] = []
    avg_cpu = _to_float(metrics.get("avg_cpu_14d"))
    if avg_cpu is not None and avg_cpu < 10:
        findings.append(
            _finding(
                category="Recommendation",
                service="RDS",
                resource_id=_resource_id(resource),
                issue_type="Low RDS CPU utilization review",
                severity="medium",
                confidence="low",
                explanation="Average database CPU is low, but storage, memory, connection count, and maintenance windows were not fully evaluated.",
                evidence={"Average CPU": f"{avg_cpu:.2f}%", "Multi-AZ": "Yes" if metrics.get("multi_az") else "No"},
                pricing_status="unavailable",
                pricing_source=None,
                pricing_basis="Current RDS pricing was not verified.",
                savings_basis="No savings are claimed without verified database pricing and workload evidence.",
                estimated_monthly_savings=None,
                recommendation="Review database metrics before resizing or changing availability settings.",
                action_risk="No command generated because database changes can cause downtime or data risk.",
                command=None,
            )
        )
    return findings


def _finding(
    *,
    category: str,
    service: str,
    resource_id: str,
    issue_type: str,
    severity: str,
    confidence: str,
    explanation: str,
    evidence: dict[str, Any],
    pricing_status: str,
    pricing_source: str | None,
    pricing_basis: str,
    savings_basis: str,
    estimated_monthly_savings: float | None,
    recommendation: str,
    action_risk: str,
    command: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": f"{service.lower()}:{resource_id}:{issue_type.lower().replace(' ', '-')}",
        "category": category,
        "service": service,
        "resource_id": resource_id,
        "issue_type": issue_type,
        "severity": severity,
        "confidence": confidence,
        "confidence_score": _confidence_score(confidence),
        "explanation": explanation,
        "evidence": evidence,
        "pricing_status": pricing_status,
        "pricing_source": pricing_source,
        "pricing_basis": pricing_basis,
        "savings_basis": savings_basis,
        "estimated_monthly_savings": estimated_monthly_savings,
        "estimated_monthly_savings_display": format_monthly_savings(estimated_monthly_savings),
        "recommendation": recommendation,
        "action_risk": action_risk,
        "command": command,
        "fix_command": command["text"] if command else "",
    }
    if extra:
        payload.update(extra)
    return payload


def _scan_warnings(scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = [dict(item) for item in scan_result.get("warnings", [])]
    for error in scan_result.get("errors", []):
        warnings.append(
            {
                "service": error.get("service", "unknown"),
                "resource_id": error.get("resource_id"),
                "code": error.get("code", "ScanWarning"),
                "message": error.get("message", "A service check could not be completed."),
            }
        )
    return warnings


def _s3_lifecycle_unknown_warning(bucket: str, metrics: dict[str, Any]) -> dict[str, Any]:
    lifecycle = metrics.get("lifecycle_status") if isinstance(metrics.get("lifecycle_status"), dict) else {}
    code = lifecycle.get("code") or metrics.get("lifecycle_error_code") or "Unknown"
    permission = lifecycle.get("permission") or metrics.get("lifecycle_permission") or "s3:GetLifecycleConfiguration"
    return {
        "service": "S3",
        "resource_id": bucket,
        "code": code,
        "permission": permission,
        "message": (
            "BudgetBeagle could not verify the bucket lifecycle configuration because "
            f"the IAM identity lacks permission or inspection failed. Required permission: {permission}."
        ),
    }


def _new_warnings(existing: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {_warning_key(item) for item in existing}
    return [item for item in additions if _warning_key(item) not in keys]


def _warning_key(item: dict[str, Any]) -> tuple[Any, Any, Any]:
    return item.get("service"), item.get("resource_id"), item.get("code")


def _total_savings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        float(item["estimated_monthly_savings"])
        for item in findings
        if isinstance(item.get("estimated_monthly_savings"), (int, float))
    ]
    if not values:
        return {"amount_usd": None, "display": "Not enough data", "basis": "No evidence-backed numeric savings were available."}
    total = round(sum(values), 2)
    return {
        "amount_usd": total,
        "display": format_monthly_savings(total),
        "basis": "Only numeric, evidence-backed savings are included.",
    }


def _total_maximum_avoidable_cost(findings: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        float(item["maximum_monthly_avoidable_cost_usd"])
        for item in findings
        if isinstance(item.get("maximum_monthly_avoidable_cost_usd"), (int, float))
    ]
    if not values:
        return {"amount_usd": None, "display": "Not enough data", "basis": "No verified maximum avoidable cost was available."}
    total = round(sum(values), 2)
    return {
        "amount_usd": total,
        "display": format_monthly_savings(total),
        "basis": "Maximum avoidable cost is shown separately from likely savings.",
    }

def _annualized(monthly_amount: Any) -> dict[str, Any]:
    monthly = _to_float(monthly_amount)
    if monthly is None:
        return {"amount_usd": None, "display": "Not enough data", "basis": "Monthly savings are not numeric."}
    amount = round(monthly * 12, 2)
    return {"amount_usd": amount, "display": f"${amount:.2f}/year", "basis": "12 x evidence-backed monthly savings."}


def _period_average(amount: Any, billing: dict[str, Any]) -> float | None:
    numeric = _to_float(amount)
    if numeric is None:
        return None
    months = len(billing.get("monthly_account_costs") or [])
    if months <= 0:
        return None
    average = Decimal(str(numeric)) / Decimal(months)
    return float(average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _overall_confidence(findings: list[dict[str, Any]], warnings: list[dict[str, Any]], billing: dict[str, Any]) -> dict[str, Any]:
    if findings:
        score = round(sum(_confidence_score(str(item.get("confidence") or "low")) for item in findings) / len(findings))
    else:
        score = 90
    score -= min(len(warnings) * 5, 25)
    if billing.get("status") not in {"available", None}:
        score -= 10
    score = max(35, min(95, score))
    label = "High" if score >= 80 else "Medium" if score >= 65 else "Low"
    return {
        "score": score,
        "label": label,
        "basis": "Derived from finding evidence confidence, scan warnings, and billing data availability.",
    }


def _confidence_score(value: str) -> int:
    level = value.lower()
    if level == "high":
        return 90
    if level == "medium":
        return 75
    return 55

def _summary(
    resources: int,
    confirmed_issues: int,
    recommendations: int,
    warnings: int,
    total: dict[str, Any],
    max_avoidable: dict[str, Any],
) -> str:
    warning_text = " Scan completed with warnings." if warnings else ""
    if total.get("amount_usd") is not None:
        return (
            f"Scanned {resources} resources. Found {confirmed_issues} confirmed issues and "
            f"{recommendations} recommendations. Potential monthly savings: {total['display']}.{warning_text}"
        )
    if max_avoidable.get("amount_usd") is not None:
        return (
            f"Scanned {resources} resources. Found {confirmed_issues} confirmed issues and "
            f"{recommendations} recommendations. Potential maximum avoidable cost: {max_avoidable['display']}.{warning_text}"
        )
    return (
        f"Scanned {resources} resources. Found {confirmed_issues} confirmed issues and "
        f"{recommendations} recommendations. Potential monthly savings: Not enough data.{warning_text}"
    )


def _quote_ec2(pricing_resolver: Any, region: str, instance_type: str) -> PricingQuote:
    if not instance_type:
        return PricingQuote("unavailable", None, None, "Instance type was not available for pricing.", region, "Linux", "Shared")
    try:
        return pricing_resolver.quote_ec2_on_demand(region=region, instance_type=instance_type, operating_system="Linux", tenancy="Shared")
    except Exception:
        return PricingQuote("unavailable", None, None, "Current regional EC2 price could not be verified.", region, "Linux", "Shared")


def _cpu_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    summary = metrics.get("cpu_utilization")
    if isinstance(summary, dict):
        return summary
    return {
        "metric_source": "CloudWatch",
        "metric_name": "CPUUtilization",
        "average": metrics.get("avg_cpu_14d"),
        "minimum": metrics.get("avg_cpu_14d"),
        "maximum": metrics.get("avg_cpu_14d"),
        "datapoint_count": 1 if metrics.get("avg_cpu_14d") is not None else 0,
        "requested_window_days": _env_int("BUDGETBEAGLE_EC2_ANALYSIS_WINDOW_DAYS", 14),
        "actual_duration_hours": 0,
        "instance_launch_time": metrics.get("launch_time"),
    }


def _lifecycle_status(metrics: dict[str, Any]) -> str:
    status = metrics.get("lifecycle_status")
    if isinstance(status, dict):
        return str(status.get("status") or "unknown").lower()
    if isinstance(status, str):
        return status.lower()
    if metrics.get("has_lifecycle_policy") is True:
        return "present"
    if metrics.get("has_lifecycle_policy") is False or metrics.get("missing_lifecycle_policy") is True:
        return "absent"
    return "unknown"


def _ec2_stop_command(region: str, instance_id: str) -> dict[str, Any]:
    return {
        "text": f"aws ec2 stop-instances --region {region} --instance-ids {instance_id}",
        "risk": "reversible",
        "risk_label": "Reversible, but causes workload downtime.",
        "operation": "stop",
        "valid": True,
    }


def _recent_launch(cpu: dict[str, Any]) -> bool:
    launch = _parse_datetime(cpu.get("instance_launch_time"))
    requested_start = _parse_datetime(cpu.get("requested_start"))
    if not launch or not requested_start:
        return False
    return launch > requested_start


def _metrics(resource: dict[str, Any]) -> dict[str, Any]:
    value = resource.get("metrics")
    return value if isinstance(value, dict) else {}


def _resource_id(resource: dict[str, Any]) -> str:
    return str(resource.get("id") or resource.get("resource_id") or "unknown")


def _valid_gp3_iops(value: int) -> bool:
    return GP3_MIN_IOPS <= value <= GP3_MAX_IOPS


def _valid_gp3_throughput(value: int) -> bool:
    return GP3_MIN_THROUGHPUT_MIBPS <= value <= GP3_MAX_THROUGHPUT_MIBPS


def _format_hours(value: float) -> str:
    if value < 1:
        return "less than 1 hour"
    if value == 1:
        return "1 hour"
    return f"{value:.1f} hours"


def _percent_or_unknown(value: Any) -> str:
    numeric = _to_float(value)
    return "Unknown" if numeric is None else f"{numeric:.2f}%"


def _gb_or_unknown(value: Any) -> str:
    numeric = _to_float(value)
    return "Unknown" if numeric is None else f"{numeric:g} GiB"


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    numeric = _to_float(value)
    return None if numeric is None else int(numeric)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
