from dataclasses import asdict, dataclass
from typing import Literal

from kh_agent.core.canonical import ContentHash, canonical_hash
from kh_agent.core.errors import DomainError, ErrorCode


@dataclass(frozen=True)
class FactorRule:
    name: str
    weight: int
    normalization: Literal["COUNT", "PERCENT", "INVERSE_PERCENT", "BOOLEAN"]
    count_cap: int = 1

    def __post_init__(self) -> None:
        if (
            not self.name
            or type(self.weight) is not int
            or not 1 <= self.weight <= 100
            or type(self.count_cap) is not int
            or self.count_cap <= 0
            or self.normalization not in ("COUNT", "PERCENT", "INVERSE_PERCENT", "BOOLEAN")
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid risk factor rule")

    def severity(self, value: int | bool) -> int:
        if self.normalization == "BOOLEAN":
            if type(value) is not bool:
                raise DomainError(ErrorCode.INVALID_INPUT, "Boolean risk evidence required")
            return 100 if value else 0
        if type(value) is not int or value < 0:
            raise DomainError(ErrorCode.INVALID_INPUT, "Nonnegative integer risk evidence required")
        if self.normalization == "COUNT":
            return min(100, (value * 100 + self.count_cap - 1) // self.count_cap)
        if value > 100:
            raise DomainError(ErrorCode.INVALID_INPUT, "Percentage risk evidence out of range")
        return 100 - value if self.normalization == "INVERSE_PERCENT" else value


@dataclass(frozen=True)
class RiskPolicy:
    rule_version: str
    threshold_version: str
    factors: tuple[FactorRule, ...]
    medium_at: int = 40
    high_at: int = 70

    def __post_init__(self) -> None:
        if (
            not self.rule_version
            or not self.threshold_version
            or type(self.factors) is not tuple
            or type(self.medium_at) is not int
            or type(self.high_at) is not int
            or sum(rule.weight for rule in self.factors) != 100
            or len({rule.name for rule in self.factors}) != len(self.factors)
            or not 0 < self.medium_at < self.high_at <= 100
        ):
            raise DomainError(ErrorCode.INVALID_INPUT, "Invalid versioned risk policy")

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "rule_version": self.rule_version,
                "threshold_version": self.threshold_version,
                "factors": [asdict(factor) for factor in self.factors],
                "medium_at": self.medium_at,
                "high_at": self.high_at,
                "missing_rule": "INTERVAL_ZERO_TO_MAX_CONSERVATIVE_UPPER",
                "rounding": "CEILING_WEIGHTED_INTEGER",
            },
            "risk-policy-v1",
        ).digest


@dataclass(frozen=True)
class FactorEvidence:
    value: int | bool | None
    evidence_reference: str | None


def score_risk(
    policy: RiskPolicy,
    evidence: dict[str, FactorEvidence],
    *,
    phase: Literal["PRELIMINARY", "FINAL"],
    basis_hash: str,
    canonical_change_set_complete: bool = False,
) -> dict:
    ContentHash(basis_hash, "risk-basis-v1")
    if phase not in ("PRELIMINARY", "FINAL"):
        raise DomainError(ErrorCode.INVALID_INPUT)
    if phase == "FINAL" and canonical_change_set_complete is not True:
        raise DomainError(
            ErrorCode.INVALID_INPUT, "Final risk requires a complete actual change set"
        )
    if evidence.keys() - {rule.name for rule in policy.factors}:
        raise DomainError(ErrorCode.INVALID_INPUT, "Unregistered risk factor")
    lower = upper = 0
    factors, missing = [], []
    for rule in policy.factors:
        item = evidence.get(rule.name)
        if item is None or item.value is None or not item.evidence_reference:
            missing.append(rule.name)
            upper += rule.weight * 100
            factors.append(
                {
                    "name": rule.name,
                    "status": "UNAVAILABLE",
                    "weight": rule.weight,
                    "severity": None,
                    "evidence_reference": None,
                }
            )
        else:
            severity = rule.severity(item.value)
            lower += rule.weight * severity
            upper += rule.weight * severity
            factors.append(
                {
                    "name": rule.name,
                    "status": "AVAILABLE",
                    "weight": rule.weight,
                    "severity": severity,
                    "evidence_reference": item.evidence_reference,
                }
            )
    lower_score, upper_score = (lower + 99) // 100, (upper + 99) // 100
    level = (
        "HIGH"
        if upper_score >= policy.high_at
        else "MEDIUM"
        if upper_score >= policy.medium_at
        else "LOW"
    )
    result = {
        "phase": phase,
        "basis_hash": basis_hash,
        "score": None if missing else upper_score,
        "score_lower_bound": lower_score,
        "score_upper_bound": upper_score,
        "risk_level": level,
        "level_basis": "CONSERVATIVE_UPPER_BOUND",
        "missing_evidence": missing,
        "factors": factors,
        "risk_rule_version": policy.rule_version,
        "threshold_version": policy.threshold_version,
        "risk_policy_hash": policy.fingerprint,
        "broaden_verification": bool(missing),
    }
    return {**result, "risk_hash": canonical_hash(result, "risk-result-v1").digest}
