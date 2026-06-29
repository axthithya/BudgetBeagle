from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError


@dataclass(frozen=True)
class PricingQuote:
    status: str
    hourly_usd: float | None
    source: str | None
    basis: str
    region: str
    operating_system: str
    tenancy: str
    purchase_option: str = "OnDemand"


REGION_TO_PRICING_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "af-south-1": "Africa (Cape Town)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-south-2": "Asia Pacific (Hyderabad)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-southeast-4": "Asia Pacific (Melbourne)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ca-central-1": "Canada (Central)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-central-2": "Europe (Zurich)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-south-1": "Europe (Milan)",
    "eu-south-2": "Europe (Spain)",
    "eu-north-1": "Europe (Stockholm)",
    "il-central-1": "Israel (Tel Aviv)",
    "me-central-1": "Middle East (UAE)",
    "me-south-1": "Middle East (Bahrain)",
    "sa-east-1": "South America (Sao Paulo)",
}


class Ec2PriceResolver:
    def quote_ec2_on_demand(
        self,
        *,
        region: str,
        instance_type: str,
        operating_system: str = "Linux",
        tenancy: str = "Shared",
    ) -> PricingQuote:
        location = REGION_TO_PRICING_LOCATION.get(region)
        if not location:
            return _unavailable(region, operating_system, tenancy, "AWS pricing location is not mapped for this region.")
        if not _credentials_likely_available():
            return _unavailable(region, operating_system, tenancy, "Current regional EC2 price could not be verified.")

        try:
            client = boto3.client(
                "pricing",
                region_name="us-east-1",
                config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
            )
            response = client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": tenancy},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                ],
                MaxResults=100,
            )
            hourly = _extract_hourly_usd(response.get("PriceList", []))
            if hourly is None:
                return _unavailable(region, operating_system, tenancy, "AWS Pricing API returned no On-Demand hourly price.")
            return PricingQuote(
                status="verified",
                hourly_usd=hourly,
                source="AWS Pricing API",
                basis=(
                    f"{region} {operating_system} On-Demand price for {instance_type}, "
                    f"{tenancy.lower()} tenancy, from AWS Pricing API."
                ),
                region=region,
                operating_system=operating_system,
                tenancy=tenancy,
            )
        except (BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError, OSError):
            return _unavailable(region, operating_system, tenancy, "Current regional EC2 price could not be verified.")


def _extract_hourly_usd(price_list: list[str]) -> float | None:
    for item in price_list:
        product = json.loads(item)
        for term in product.get("terms", {}).get("OnDemand", {}).values():
            for dimension in term.get("priceDimensions", {}).values():
                unit = str(dimension.get("unit", "")).lower()
                price = dimension.get("pricePerUnit", {}).get("USD")
                if price is not None and unit in {"hrs", "hours"}:
                    return float(price)
    return None


def _credentials_likely_available() -> bool:
    names = [
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ]
    return any(os.environ.get(name) for name in names)


def _unavailable(region: str, operating_system: str, tenancy: str, basis: str) -> PricingQuote:
    return PricingQuote(
        status="unavailable",
        hourly_usd=None,
        source=None,
        basis=basis,
        region=region,
        operating_system=operating_system,
        tenancy=tenancy,
    )
