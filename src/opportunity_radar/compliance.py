from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from opportunity_radar.discovery.models import DiscoveryMeta

PHASES = frozenset({"candidate", "verified", "retired"})
ORIGINS = frozenset({"manual", "discovery"})
REGISTRATION_STATUSES = frozenset(
    {"unknown", "not_required", "per_dataset", "required", "completed"}
)
ELIGIBLE_REGISTRATION_STATUSES = frozenset({"not_required", "completed"})
AUTHORIZATION_TYPES = frozenset(
    {"unknown", "none", "api_key", "agreement", "written_permission"}
)
ELIGIBLE_AUTHORIZATION_TYPES = frozenset(
    {"api_key", "agreement", "written_permission"}
)
PLACEHOLDERS = frozenset({"", "tbd", "pending", "n/a", "none", "null"})
ADAPTER_VERSION_PLACEHOLDERS = PLACEHOLDERS | {
    "unknown",
    "unassigned",
    "unregistered",
}


def _require_string(value: object, field: str, *, allow_unknown: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    disallowed = PLACEHOLDERS - ({"none"} if field == "authorization" else set())
    if not normalized or normalized.casefold() in disallowed:
        raise ValueError(f"{field} must not be blank or a placeholder")
    if not allow_unknown and normalized.casefold() == "unknown":
        raise ValueError(f"{field} must be confirmed")
    return normalized


def _require_optional_exact_bool(value: object, field: str) -> bool | None:
    if value is not None and type(value) is not bool:
        raise ValueError(f"{field} must be a JSON boolean or null")
    return value


def _require_date(value: object, field: str, *, optional: bool = False) -> date | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _require_https_url(value: object, field: str) -> str:
    url = _require_string(value, field)
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"{field} must be a valid HTTPS URL")
    return url


@dataclass(frozen=True)
class RateLimitPolicy:
    """Concrete official request-rate policy for an eligible source."""

    max_requests: int
    period_seconds: int
    minimum_interval_seconds: float

    def __post_init__(self) -> None:
        if type(self.max_requests) is not int or self.max_requests <= 0:
            raise ValueError("rate_limit.max_requests must be a positive integer")
        if type(self.period_seconds) is not int or self.period_seconds <= 0:
            raise ValueError("rate_limit.period_seconds must be a positive integer")
        if (
            isinstance(self.minimum_interval_seconds, bool)
            or not isinstance(self.minimum_interval_seconds, (int, float))
            or not math.isfinite(self.minimum_interval_seconds)
            or self.minimum_interval_seconds <= 0
        ):
            raise ValueError(
                "rate_limit.minimum_interval_seconds must be a positive number"
            )

    def required_adapter_interval_seconds(self) -> float:
        """Return the stricter interval from per-request and window rate limits."""
        window_interval = self.period_seconds / self.max_requests
        return max(float(self.minimum_interval_seconds), window_interval)

    def adapter_interval_blocking_reason(self, interval: object) -> str | None:
        """Explain why an adapter interval cannot enforce this verified policy."""
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or interval <= 0
        ):
            return "request_interval_seconds must be a finite positive number"
        required = self.required_adapter_interval_seconds()
        if interval < required:
            return (
                f"request_interval_seconds={interval:g} below required={required:g}"
            )
        return None


@dataclass(frozen=True)
class ComplianceAuditSnapshot:
    """Immutable compliance evidence attached to one participating adapter."""

    source_id: str
    verified_at: date
    evidence_url: str
    adapter_version: str

    def __post_init__(self) -> None:
        _require_string(self.source_id, "source_id")
        if not isinstance(self.verified_at, date):
            raise TypeError("verified_at must be a date")
        _require_https_url(self.evidence_url, "evidence_url")
        if (
            not isinstance(self.adapter_version, str)
            or self.adapter_version.strip().casefold() in ADAPTER_VERSION_PLACEHOLDERS
        ):
            raise ValueError("adapter_version must be non-placeholder")


@dataclass(frozen=True)
class ComplianceSource:
    source_id: str
    display_name: str
    phase: str
    enabled: bool
    terms: str
    terms_confirmed: bool | None
    registration: str
    registration_completed: bool | None
    authorization: str
    rate_limit: RateLimitPolicy | None
    selected_data_scope: str
    field_permission_confirmed: bool | None
    evidence_url: str
    verified_at: date | None
    review_due_at: date
    owner: str
    available_fields: tuple[str, ...]
    origin: str = "manual"  # manual | discovery
    discovery: DiscoveryMeta | None = None  # 仅 origin=discovery 填充

    def __post_init__(self) -> None:
        _require_string(self.source_id, "source_id")
        _require_string(self.display_name, "display_name")
        if self.phase not in PHASES:
            raise ValueError(f"phase must be one of {sorted(PHASES)}")
        if self.origin not in ORIGINS:
            raise ValueError(f"origin must be one of {sorted(ORIGINS)}")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a JSON boolean")
        _require_string(self.terms, "terms", allow_unknown=self.phase != "verified")
        _require_optional_exact_bool(self.terms_confirmed, "terms_confirmed")
        if self.registration not in REGISTRATION_STATUSES:
            raise ValueError(
                f"registration must be one of {sorted(REGISTRATION_STATUSES)}"
            )
        _require_optional_exact_bool(
            self.registration_completed, "registration_completed"
        )
        if self.authorization not in AUTHORIZATION_TYPES:
            raise ValueError(
                f"authorization must be one of {sorted(AUTHORIZATION_TYPES)}"
            )
        if self.rate_limit is not None and not isinstance(
            self.rate_limit, RateLimitPolicy
        ):
            raise ValueError("rate_limit must be a structured policy or null")
        _require_string(
            self.selected_data_scope,
            "selected_data_scope",
            allow_unknown=self.phase != "verified",
        )
        _require_optional_exact_bool(
            self.field_permission_confirmed, "field_permission_confirmed"
        )
        _require_https_url(self.evidence_url, "evidence_url")
        _require_string(self.owner, "owner", allow_unknown=self.phase != "verified")
        for field in self.available_fields:
            _require_string(field, "available_fields")

        if self.verified_at is not None and not isinstance(self.verified_at, date):
            raise TypeError("verified_at must be a date or null")
        if not isinstance(self.review_due_at, date):
            raise TypeError("review_due_at must be a date")
        if self.verified_at is not None:
            if self.review_due_at <= self.verified_at:
                raise ValueError("review_due_at must be later than verified_at")
            if self.review_due_at > self.verified_at + timedelta(days=90):
                raise ValueError(
                    "review_due_at must be no later than 90 days after verified_at"
                )

        if self.phase == "verified":
            self._validate_verified_dimensions()

    def _validate_verified_dimensions(self) -> None:
        if not self.enabled:
            raise ValueError("enabled must be true for phase=verified")
        if self.terms_confirmed is not True:
            raise ValueError("terms_confirmed must be true for phase=verified")
        if self.registration not in ELIGIBLE_REGISTRATION_STATUSES:
            raise ValueError("registration must be completed or not_required")
        if self.registration_completed is not True:
            raise ValueError(
                "registration_completed must be true for phase=verified"
            )
        if self.authorization not in ELIGIBLE_AUTHORIZATION_TYPES:
            raise ValueError("authorization is not eligible for automatic access")
        if self.rate_limit is None:
            raise ValueError("rate_limit must be concrete for phase=verified")
        if self.field_permission_confirmed is not True:
            raise ValueError(
                "field_permission_confirmed must be true for phase=verified"
            )
        if not self.available_fields:
            raise ValueError("available_fields must be nonempty for phase=verified")
        if self.verified_at is None:
            raise ValueError("verified_at must be set for phase=verified")
        if self.owner.strip().casefold() in {"unassigned", "unknown"}:
            raise ValueError("owner must be assigned for phase=verified")

    def blocking_reason(self, today: date) -> str | None:
        if self.phase != "verified":
            return f"phase={self.phase}"
        if self.verified_at is None:
            return "verified_at=missing"
        if self.verified_at > today:
            return "verified_at=future"
        if self.review_due_at <= today:
            return "review_due_at=expired"
        return None

    def audit_snapshot(
        self, adapter_version: str, today: date
    ) -> ComplianceAuditSnapshot:
        """Build evidence only after repeating the source eligibility gate."""
        reason = self.blocking_reason(today)
        if reason is not None:
            raise ValueError(reason)
        if self.verified_at is None:  # defensive: verified model validation requires it
            raise ValueError("verified_at=missing")
        if (
            not isinstance(adapter_version, str)
            or adapter_version.strip().casefold() in ADAPTER_VERSION_PLACEHOLDERS
        ):
            rendered_version = adapter_version or "missing"
            raise ValueError(f"adapter_version={rendered_version}")
        return ComplianceAuditSnapshot(
            source_id=self.source_id,
            verified_at=self.verified_at,
            evidence_url=self.evidence_url,
            adapter_version=adapter_version,
        )


def _parse_rate_limit(value: object) -> RateLimitPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("rate_limit must be a structured policy or null")
    expected_keys = {
        "max_requests",
        "period_seconds",
        "minimum_interval_seconds",
    }
    if set(value) != expected_keys:
        raise ValueError(f"rate_limit must contain exactly {sorted(expected_keys)}")
    return RateLimitPolicy(
        max_requests=value["max_requests"],
        period_seconds=value["period_seconds"],
        minimum_interval_seconds=value["minimum_interval_seconds"],
    )


def _parse_source(item: object) -> ComplianceSource:
    if not isinstance(item, dict):
        raise TypeError("each compliance source must be a JSON object")
    source_id = item.get("source_id", "<missing>")
    try:
        if type(item["enabled"]) is not bool:
            raise ValueError("enabled must be a JSON boolean")
        terms_confirmed = _require_optional_exact_bool(
            item["terms_confirmed"], "terms_confirmed"
        )
        registration_completed = _require_optional_exact_bool(
            item["registration_completed"], "registration_completed"
        )
        field_permission_confirmed = _require_optional_exact_bool(
            item["field_permission_confirmed"], "field_permission_confirmed"
        )
        verified_at = _require_date(item["verified_at"], "verified_at", optional=True)
        review_due_at = _require_date(item["review_due_at"], "review_due_at")
        assert isinstance(review_due_at, date)
        available_fields = item["available_fields"]
        if not isinstance(available_fields, list):
            raise TypeError("available_fields must be a JSON array")
        discovery_data = item.get("discovery")
        discovery = (
            DiscoveryMeta.model_validate(discovery_data) if discovery_data else None
        )
        return ComplianceSource(
            source_id=item["source_id"],
            display_name=item["display_name"],
            phase=item["phase"],
            enabled=item["enabled"],
            terms=item["terms"],
            terms_confirmed=terms_confirmed,
            registration=item["registration"],
            registration_completed=registration_completed,
            authorization=item["authorization"],
            rate_limit=_parse_rate_limit(item["rate_limit"]),
            selected_data_scope=item["selected_data_scope"],
            field_permission_confirmed=field_permission_confirmed,
            evidence_url=item["evidence_url"],
            verified_at=verified_at,
            review_due_at=review_due_at,
            owner=item["owner"],
            available_fields=tuple(available_fields),
            origin=item.get("origin", "manual"),
            discovery=discovery,
        )
    except KeyError as error:
        raise ValueError(f"{error.args[0]} is required for source {source_id}") from error
    except (TypeError, ValueError) as error:
        raise ValueError(f"source {source_id}: {error}") from error


def load_compliance_sources(path: Path) -> dict[str, ComplianceSource]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("compliance registry must be a JSON array")
    sources: dict[str, ComplianceSource] = {}
    for item in payload:
        source = _parse_source(item)
        if source.source_id in sources:
            raise ValueError(f"duplicate source_id: {source.source_id}")
        sources[source.source_id] = source
    return sources
