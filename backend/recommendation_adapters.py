from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


RECOMMENDATION_SOURCES = {
    "budgetbeagle_rule",
    "aws_compute_optimizer",
    "aws_cost_optimization_hub",
}


@dataclass(frozen=True)
class NormalizedRecommendation:
    source: str
    source_recommendation_id: str | None
    account: str | None
    region: str | None
    scope: str
    service: str
    resource_id: str
    resource_type: str | None
    recommendation_type: str
    current_configuration: dict[str, Any] = field(default_factory=dict)
    recommended_configuration: dict[str, Any] = field(default_factory=dict)
    estimated_monthly_savings: float | None = None
    currency: str = "USD"
    confidence: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    source_timestamp: str | None = None
    generated_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RecommendationAdapter(Protocol):
    source: str

    def normalize(self, payload: dict[str, Any]) -> NormalizedRecommendation:
        ...


class BudgetBeagleRuleAdapter:
    source = "budgetbeagle_rule"

    def normalize(self, payload: dict[str, Any]) -> NormalizedRecommendation:
        return NormalizedRecommendation(
            source=self.source,
            source_recommendation_id=payload.get("id") or payload.get("canonical_finding_id"),
            account=payload.get("account_id"),
            region=payload.get("region"),
            scope=str(payload.get("scope") or "regional"),
            service=str(payload.get("service") or "AWS"),
            resource_id=str(payload.get("resource_id") or "unknown"),
            resource_type=payload.get("resource_type"),
            recommendation_type=str(payload.get("issue_type") or payload.get("category") or "finding"),
            current_configuration=payload.get("current_configuration") or {},
            recommended_configuration=payload.get("recommended_configuration") or {},
            estimated_monthly_savings=payload.get("estimated_monthly_savings")
            if isinstance(payload.get("estimated_monthly_savings"), (int, float))
            else None,
            confidence=payload.get("confidence"),
            evidence=payload.get("evidence") or {},
            source_timestamp=payload.get("source_timestamp"),
        )


__all__ = [
    "BudgetBeagleRuleAdapter",
    "NormalizedRecommendation",
    "RecommendationAdapter",
    "RECOMMENDATION_SOURCES",
]
