from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from botocore.exceptions import BotoCoreError, ClientError

from pricing import REGION_TO_PRICING_LOCATION
from sanitize import mask_account_id, scrub_sensitive_text


WarnFn = Callable[[str, str | None, str, str, str | None], None]


def scan_billing_context(
    session: Any,
    *,
    selected_region: str,
    account_id: str | None,
    warn: WarnFn,
) -> dict[str, Any]:
    if not _enabled():
        return _unavailable("disabled", "Cost Explorer collection is disabled by configuration.")

    today = datetime.now(timezone.utc).date()
    start = date(today.year, 1, 1)
    end = today if today > start else today + timedelta(days=1)
    region_values = _region_dimension_candidates(selected_region)
    context = {
        "status": "unavailable",
        "source": "AWS Cost Explorer",
        "account_id": mask_account_id(account_id),
        "selected_region": selected_region,
        "selected_region_label": region_label(selected_region),
        "period": {
            "label": f"YTD {today.year}",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "end_exclusive": True,
        },
        "account_total_ytd_usd": None,
        "selected_region_ytd_usd": None,
        "monthly_account_costs": [],
        "monthly_selected_region_costs": [],
        "service_costs_ytd": [],
        "region_costs_ytd": [],
        "insights": [],
        "error": None,
    }

    try:
        client = session.client("ce", region_name="us-east-1")
        account_months = _monthly_totals(client, start, end)
        region_months = _monthly_totals(client, start, end, _region_filter(region_values))
        service_costs = _grouped_ytd(client, start, end, "SERVICE")
        region_costs = _grouped_ytd(client, start, end, "REGION")

        account_total = round(sum(item["amount_usd"] for item in account_months), 2)
        selected_region_total = round(sum(item["amount_usd"] for item in region_months), 2)
        context.update(
            {
                "status": "available",
                "account_total_ytd_usd": account_total,
                "selected_region_ytd_usd": selected_region_total,
                "monthly_account_costs": account_months,
                "monthly_selected_region_costs": region_months,
                "service_costs_ytd": service_costs,
                "region_costs_ytd": region_costs,
                "insights": _billing_insights(selected_region, selected_region_total, account_total, region_costs),
            }
        )
        return context
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "CostExplorerError")
        safe_message = "Cost Explorer data could not be collected."
        warn("Cost Explorer", None, code, safe_message, "ce:GetCostAndUsage")
        context["error"] = {"code": code, "message": safe_message, "permission": "ce:GetCostAndUsage"}
        return context
    except (BotoCoreError, OSError) as exc:
        code = exc.__class__.__name__
        safe_message = "Cost Explorer data could not be collected."
        warn("Cost Explorer", None, code, safe_message, "ce:GetCostAndUsage")
        context["error"] = {"code": code, "message": safe_message, "permission": "ce:GetCostAndUsage"}
        return context


def region_label(region: str | None) -> str:
    if not region:
        return "Unknown region"
    location = REGION_TO_PRICING_LOCATION.get(region)
    return f"{region} - {location}" if location else region


def _monthly_totals(
    client: Any,
    start: date,
    end: date,
    expression: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    request: dict[str, Any] = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
    }
    if expression:
        request["Filter"] = expression
    response = client.get_cost_and_usage(**request)
    months: list[dict[str, Any]] = []
    for item in response.get("ResultsByTime", []):
        amount = _amount(item.get("Total", {}).get("UnblendedCost", {}))
        months.append(
            {
                "start": item.get("TimePeriod", {}).get("Start"),
                "end": item.get("TimePeriod", {}).get("End"),
                "label": _month_label(item.get("TimePeriod", {}).get("Start")),
                "amount_usd": amount,
                "display": _money(amount),
            }
        )
    return months


def _grouped_ytd(client: Any, start: date, end: date, dimension: str) -> list[dict[str, Any]]:
    response = client.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": dimension}],
    )
    totals: dict[str, float] = {}
    for period in response.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            key = str((group.get("Keys") or ["Unknown"])[0] or "Unknown")
            amount = _amount(group.get("Metrics", {}).get("UnblendedCost", {}))
            totals[key] = round(totals.get(key, 0.0) + amount, 2)
    result = []
    for key, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        if key == "NoRegion":
            key = "Global / No Region"
        result.append({"name": key, "amount_usd": amount, "display": _money(amount)})
    return result


def _billing_insights(
    selected_region: str,
    selected_region_total: float,
    account_total: float,
    region_costs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if account_total <= 0 or selected_region_total > 0:
        return []
    billed_regions = [item for item in region_costs if item["amount_usd"] > 0]
    if not billed_regions:
        return []
    return [
        {
            "type": "no_spend_in_selected_region",
            "severity": "medium",
            "title": "No spend in this region",
            "message": (
                f"AWS Cost Explorer reports $0.00 for {region_label(selected_region)} in the selected period, "
                f"while account-wide billing is {_money(account_total)}."
            ),
            "regions": billed_regions[:8],
        }
    ]


def _region_filter(values: list[str]) -> dict[str, Any]:
    return {"Dimensions": {"Key": "REGION", "Values": values}}


def _region_dimension_candidates(region: str) -> list[str]:
    values = [region]
    location = REGION_TO_PRICING_LOCATION.get(region)
    if location:
        values.append(location)
    return values


def _amount(metric: dict[str, Any]) -> float:
    try:
        return round(float(metric.get("Amount") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float | None) -> str:
    if value is None:
        return "Not enough data"
    return f"${value:.2f}"


def _month_label(value: str | None) -> str:
    if not value:
        return "Unknown"
    try:
        return datetime.fromisoformat(value).strftime("%b %Y")
    except ValueError:
        return value


def _enabled() -> bool:
    import os

    return os.getenv("BUDGETBEAGLE_ENABLE_COST_EXPLORER", "true").lower() not in {"0", "false", "no"}


def _unavailable(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "source": "AWS Cost Explorer",
        "period": {},
        "account_total_ytd_usd": None,
        "selected_region_ytd_usd": None,
        "monthly_account_costs": [],
        "monthly_selected_region_costs": [],
        "service_costs_ytd": [],
        "region_costs_ytd": [],
        "insights": [],
        "error": {"code": code, "message": message},
    }
