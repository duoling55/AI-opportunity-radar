from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class PolicyItem(BaseModel):
    title: str
    url: str


class CrawlResult(BaseModel):
    fetch_mode: str  # "http" | "playwright"
    html: str
    text_content: str
    page_title: str
    policy_items: list[PolicyItem]
    snapshot_path: str
    final_url: str
    restricted: bool
    restricted_reason: str | None = None


class CheckDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain_owner: str  # "gov" | "other"
    accessibility: dict
    login_required: bool
    captcha_triggered: bool
    robots: dict
    rate_limit_hints: dict
    column_structure: dict


class ComplianceReport(BaseModel):
    check_result: str  # pass | needs_attention | not_recommended
    check_details: CheckDetails
    recommendation: str  # 建议启用 | 需人工关注 | 不建议


class ScoreBreakdownItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    score: int
    max: int
    reason: str


class ScoreResult(BaseModel):
    priority_score: int
    priority_level: str  # 高 | 中 | 低
    score_breakdown: list[ScoreBreakdownItem]


class SamplePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    matched_keywords: list[str]


class DiscoveryMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    keywords: list[str]
    discovered_at: date
    portal_seed_id: str
    admin_level: str  # 国家 | 省 | 市
    sample_policies: list[SamplePolicy]
    snapshots: list[str]
    check_result: str
    check_details: CheckDetails
    recommendation: str
    priority_score: int
    priority_level: str
    score_breakdown: list[ScoreBreakdownItem]


class SearchKeyword(BaseModel):
    text: str
    tag: str
    signal_strength: str | None = None


class DiscoveryReport(BaseModel):
    job_id: str
    started_at: str
    finished_at: str
    keywords_used: list[str]
    portals_scanned: list[dict]
    candidates: list[str]
    stats: dict
    errors: list[dict]
