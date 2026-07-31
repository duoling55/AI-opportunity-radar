from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationInfo, field_validator


class PolicyCandidate(BaseModel):
    source_id: str
    title: str
    detail_url: HttpUrl
    published_at: date | None = None


class PolicyDocument(BaseModel):
    policy_id: str
    source_id: str
    source_name: str
    region: str
    title: str
    detail_url: HttpUrl
    publisher: str | None = None
    document_number: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    application_start_date: date | None = None
    application_end_date: date | None = None
    raw_text: str
    normalized_text: str
    attachment_urls: list[HttpUrl] = Field(default_factory=list)
    attachment_snapshot_paths: list[str] = Field(default_factory=list)
    attachment_errors: list[str] = Field(default_factory=list)
    supplementary_urls: list[HttpUrl] = Field(default_factory=list)
    collected_at: datetime
    content_hash: str
    snapshot_path: str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quote: str = Field(min_length=2, max_length=240)
    location: str = Field(min_length=1, max_length=80)


class IndustryOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section_code: str
    section_name: str
    division_code: str
    division_name: str
    business_tags: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    scenarios: list[str] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    leasing_relevance: str
    recommended_action: str
    opening_script: str


class PolicyAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    is_benefit_policy: bool
    summary: str
    support_direction: str
    eligible_conditions: str | None = None
    risk_notes: str | None = None
    opportunities: list[IndustryOpportunity] = Field(default_factory=list)

    @field_validator("opportunities")
    @classmethod
    def non_benefit_policy_has_no_opportunities(
        cls, value: list[IndustryOpportunity], info: ValidationInfo
    ) -> list[IndustryOpportunity]:
        if info.data.get("is_benefit_policy") is False and value:
            raise ValueError("non-benefit policy cannot contain opportunities")
        return value
