from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import ValidationError

from opportunity_radar.analysis.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    build_user_prompt,
    validate_user_prompt_template,
)
from opportunity_radar.diagnostics import safe_url
from opportunity_radar.models import Evidence, IndustryOpportunity, PolicyAnalysis, PolicyDocument
from opportunity_radar.normalization import normalize_text

LOGGER = logging.getLogger(__name__)

_SECTION_CODE = re.compile(r"[A-Z]")
_DIVISION_CODE = re.compile(r"[A-Z]\d{2}")
OPPORTUNITY_SCENARIOS = frozenset(
    {
        "设备采购",
        "设备更新",
        "技术改造",
        "扩产",
        "生产线建设",
        "车辆更新",
        "绿色转型",
        "数字化转型",
    }
)
_RETRYABLE_ANALYSIS_ERRORS = (
    TimeoutError,
    httpx.TimeoutException,
    json.JSONDecodeError,
    ValidationError,
    KeyError,
    TypeError,
)


class Analyzer(Protocol):
    def analyze(
        self,
        document: PolicyDocument,
        valid_codes: Mapping[str, str] | set[str],
        business_tags: list[str],
    ) -> PolicyAnalysis: ...


class StaticAnalyzer:
    def __init__(self, analysis: PolicyAnalysis) -> None:
        self.analysis = analysis

    def analyze(
        self,
        document: PolicyDocument,
        valid_codes: Mapping[str, str] | set[str],
        business_tags: list[str],
    ) -> PolicyAnalysis:
        return validate_analysis(
            self.analysis,
            valid_codes,
            business_tags,
            document.normalized_text,
        )


class OpenAICompatibleAnalyzer:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = (
            os.getenv("OPPORTUNITY_RADAR_SYSTEM_PROMPT", SYSTEM_PROMPT).strip()
            or SYSTEM_PROMPT
        )
        self.user_prompt_template = validate_user_prompt_template(
            os.getenv("OPPORTUNITY_RADAR_USER_PROMPT_TEMPLATE", USER_PROMPT_TEMPLATE)
        )

    def analyze(
        self,
        document: PolicyDocument,
        valid_codes: Mapping[str, str] | set[str],
        business_tags: list[str],
    ) -> PolicyAnalysis:
        retry_note = ""
        for attempt in range(2):
            endpoint = f"{self.base_url}/chat/completions"
            started_at = perf_counter()
            LOGGER.info(
                "LLM 请求开始 provider=openai model=%s endpoint=%s policy_id=%s "
                "attempt=%d/2 text_chars=%d",
                self.model,
                safe_url(endpoint),
                document.policy_id,
                attempt + 1,
                len(document.normalized_text),
            )
            try:
                response = httpx.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": self.system_prompt},
                            {
                                "role": "user",
                                "content": build_user_prompt(
                                    document.normalized_text,
                                    valid_codes,
                                    business_tags,
                                    self.user_prompt_template,
                                )
                                + retry_note,
                            },
                        ],
                    },
                    timeout=60,
                )
                LOGGER.info(
                    "LLM 收到响应 provider=openai policy_id=%s attempt=%d/2 "
                    "status=%d elapsed_seconds=%.2f response_bytes=%d",
                    document.policy_id,
                    attempt + 1,
                    response.status_code,
                    perf_counter() - started_at,
                    len(response.content),
                )
                if response.is_error:
                    LOGGER.error(
                        "LLM HTTP 错误 provider=openai policy_id=%s status=%d "
                        "response_preview=%r",
                        document.policy_id,
                        response.status_code,
                        response.text[:500],
                    )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                # Extract JSON from potential markdown wrappers
                json_content = _extract_json_from_text(content)
                analysis = PolicyAnalysis.model_validate(json.loads(json_content))
                validated = validate_analysis(
                    analysis,
                    valid_codes,
                    business_tags,
                    document.normalized_text,
                )
                LOGGER.info(
                    "LLM 解析成功 provider=openai policy_id=%s benefit=%s "
                    "raw_opportunities=%d valid_opportunities=%d elapsed_seconds=%.2f",
                    document.policy_id,
                    analysis.is_benefit_policy,
                    len(analysis.opportunities),
                    len(validated.opportunities),
                    perf_counter() - started_at,
                )
                return validated
            except _RETRYABLE_ANALYSIS_ERRORS as error:
                LOGGER.warning(
                    "LLM 输出校验失败 provider=openai policy_id=%s attempt=%d/2 "
                    "error=%s: %s elapsed_seconds=%.2f%s",
                    document.policy_id,
                    attempt + 1,
                    type(error).__name__,
                    error,
                    perf_counter() - started_at,
                    "，准备重试" if attempt == 0 else "",
                )
                if attempt == 1:
                    raise
                retry_note = (
                    "\n\n上次输出未通过 JSON/Schema 校验，请完整重写 JSON。"
                    f"校验错误：{type(error).__name__}: {error}"
                )
            except Exception:
                LOGGER.exception(
                    "LLM 请求失败 provider=openai model=%s endpoint=%s policy_id=%s "
                    "attempt=%d/2 elapsed_seconds=%.2f",
                    self.model,
                    safe_url(endpoint),
                    document.policy_id,
                    attempt + 1,
                    perf_counter() - started_at,
                )
                raise
        raise AssertionError("analysis retry loop exhausted")


def _extract_json_from_text(text: str) -> str:
    """Extract JSON from text that may contain markdown code blocks."""
    stripped = text.strip()
    # Try direct parse first
    if stripped.startswith("{"):
        return stripped
    # Extract from markdown code blocks
    json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", stripped, re.DOTALL)
    if json_match:
        return json_match.group(1)
    # Fallback: find first { to last }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


class MiniMaxAnthropicAnalyzer:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = (
            os.getenv("OPPORTUNITY_RADAR_SYSTEM_PROMPT", SYSTEM_PROMPT).strip()
            or SYSTEM_PROMPT
        )
        self.user_prompt_template = validate_user_prompt_template(
            os.getenv("OPPORTUNITY_RADAR_USER_PROMPT_TEMPLATE", USER_PROMPT_TEMPLATE)
        )

    def analyze(
        self,
        document: PolicyDocument,
        valid_codes: Mapping[str, str] | set[str],
        business_tags: list[str],
    ) -> PolicyAnalysis:
        retry_note = ""
        for attempt in range(2):
            endpoint = f"{self.base_url}/v1/messages"
            started_at = perf_counter()
            LOGGER.info(
                "LLM 请求开始 provider=minimax model=%s endpoint=%s policy_id=%s "
                "attempt=%d/2 text_chars=%d",
                self.model,
                safe_url(endpoint),
                document.policy_id,
                attempt + 1,
                len(document.normalized_text),
            )
            try:
                response = httpx.post(
                    endpoint,
                    headers={"X-Api-Key": self.api_key},
                    json={
                        "model": self.model,
                        "max_tokens": 8192,
                        "system": self.system_prompt,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": build_user_prompt(
                                            document.normalized_text,
                                            valid_codes,
                                            business_tags,
                                            self.user_prompt_template,
                                        )
                                        + retry_note,
                                    }
                                ],
                            }
                        ],
                    },
                    timeout=60,
                )
                LOGGER.info(
                    "LLM 收到响应 provider=minimax policy_id=%s attempt=%d/2 "
                    "status=%d elapsed_seconds=%.2f response_bytes=%d",
                    document.policy_id,
                    attempt + 1,
                    response.status_code,
                    perf_counter() - started_at,
                    len(response.content),
                )
                if response.is_error:
                    LOGGER.error(
                        "LLM HTTP 错误 provider=minimax policy_id=%s status=%d "
                        "response_preview=%r",
                        document.policy_id,
                        response.status_code,
                        response.text[:500],
                    )
                response.raise_for_status()
                content = "".join(
                    block["text"]
                    for block in response.json()["content"]
                    if block["type"] == "text"
                )
                # Extract JSON from potential markdown wrappers
                json_content = _extract_json_from_text(content)
                analysis = PolicyAnalysis.model_validate(json.loads(json_content))
                validated = validate_analysis(
                    analysis,
                    valid_codes,
                    business_tags,
                    document.normalized_text,
                )
                LOGGER.info(
                    "LLM 解析成功 provider=minimax policy_id=%s benefit=%s "
                    "raw_opportunities=%d valid_opportunities=%d elapsed_seconds=%.2f",
                    document.policy_id,
                    analysis.is_benefit_policy,
                    len(analysis.opportunities),
                    len(validated.opportunities),
                    perf_counter() - started_at,
                )
                return validated
            except _RETRYABLE_ANALYSIS_ERRORS as error:
                LOGGER.warning(
                    "LLM 输出校验失败 provider=minimax policy_id=%s attempt=%d/2 "
                    "error=%s: %s elapsed_seconds=%.2f%s",
                    document.policy_id,
                    attempt + 1,
                    type(error).__name__,
                    error,
                    perf_counter() - started_at,
                    "，准备重试" if attempt == 0 else "",
                )
                if attempt == 1:
                    raise
                retry_note = (
                    "\n\n上次输出未通过 JSON/Schema 校验，请完整重写 JSON。"
                    f"校验错误：{type(error).__name__}: {error}"
                )
            except Exception:
                LOGGER.exception(
                    "LLM 请求失败 provider=minimax model=%s endpoint=%s policy_id=%s "
                    "attempt=%d/2 elapsed_seconds=%.2f",
                    self.model,
                    safe_url(endpoint),
                    document.policy_id,
                    attempt + 1,
                    perf_counter() - started_at,
                )
                raise
        raise AssertionError("analysis retry loop exhausted")


def validate_analysis(
    analysis: PolicyAnalysis,
    valid_codes: Mapping[str, str] | set[str],
    business_tags_or_text: list[str] | str,
    normalized_policy_text: str | None = None,
) -> PolicyAnalysis:
    """Fail closed on AI values that are not in checked-in local enumerations.

    The three-argument form remains accepted for callers that only have a code set.
    Runtime callers use the canonical mapping and configured business tags.
    """
    if normalized_policy_text is None:
        business_tags: list[str] | None = None
        normalized_policy_text = str(business_tags_or_text)
    else:
        business_tags = list(business_tags_or_text)

    code_names = valid_codes if isinstance(valid_codes, Mapping) else None
    allowed_codes = set(valid_codes)
    policy_text = normalize_text(normalized_policy_text)
    kept = []
    for opportunity in analysis.opportunities:
        if not (
            _SECTION_CODE.fullmatch(opportunity.section_code)
            and _DIVISION_CODE.fullmatch(opportunity.division_code)
            and opportunity.section_code in allowed_codes
            and opportunity.division_code in allowed_codes
            and opportunity.division_code.startswith(opportunity.section_code)
        ):
            continue
        if code_names is not None and (
            code_names[opportunity.section_code] != opportunity.section_name
            or code_names[opportunity.division_code] != opportunity.division_name
        ):
            continue
        if business_tags is not None and (
            not opportunity.business_tags
            or any(tag not in business_tags for tag in opportunity.business_tags)
        ):
            continue
        if any(scenario not in OPPORTUNITY_SCENARIOS for scenario in opportunity.scenarios):
            continue
        if validated := _with_verified_evidence_locations(opportunity, policy_text):
            kept.append(validated)
    return analysis.model_copy(update={"opportunities": kept})


def _with_verified_evidence_locations(
    opportunity: IndustryOpportunity, policy_text: str
) -> IndustryOpportunity | None:
    verified: list[Evidence] = []
    for evidence in opportunity.evidence:
        quote = normalize_text(evidence.quote)
        start = policy_text.find(quote) if quote else -1
        if start < 0:
            return None
        verified.append(
            evidence.model_copy(
                update={"location": f"正文字符{start + 1}-{start + len(quote)}"}
            )
        )
    return opportunity.model_copy(update={"evidence": verified})
