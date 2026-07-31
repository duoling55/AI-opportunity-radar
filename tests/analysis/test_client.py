from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

import opportunity_radar.analysis.client as client_module
from opportunity_radar.analysis.client import (
    OpenAICompatibleAnalyzer,
    StaticAnalyzer,
    validate_analysis,
)
from opportunity_radar.analysis.prompts import (
    USER_PROMPT_TEMPLATE,
    build_user_prompt,
    validate_user_prompt_template,
)
from opportunity_radar.models import PolicyAnalysis, PolicyDocument


def _document() -> PolicyDocument:
    return PolicyDocument(
        policy_id="policy-1",
        source_id="miit",
        source_name="工业和信息化部",
        region="全国",
        title="不应发送给模型的标题",
        detail_url="https://www.miit.gov.cn/policy/1",
        raw_text="不应发送给模型的原始页面文本",
        normalized_text="支持制造业设备更新。",
        collected_at=datetime(2026, 7, 29, tzinfo=UTC),
        content_hash="hash",
        snapshot_path="data/raw/policy-1.html",
    )


def _analysis_payload(
    *,
    section_code: str = "C",
    section_name: str = "制造业",
    division_code: str = "C34",
    division_name: str = "通用设备制造业",
    business_tags: list[str] | None = None,
    scenarios: list[str] | None = None,
    evidence_quote: str = "支持制造业设备更新",
) -> dict[str, object]:
    return {
        "is_benefit_policy": True,
        "summary": "设备更新",
        "support_direction": "更新",
        "opportunities": [
            {
                "section_code": section_code,
                "section_name": section_name,
                "division_code": division_code,
                "division_name": division_name,
                "business_tags": business_tags or ["节能环保"],
                "confidence": 0.8,
                "scenarios": scenarios or ["设备更新"],
                "evidence": [{"quote": evidence_quote, "location": "第1段"}],
                "leasing_relevance": "高",
                "recommended_action": "联系",
                "opening_script": "您好，近期政策支持设备更新。",
            }
        ],
    }


def test_validate_analysis_rejects_industry_code_not_in_local_table() -> None:
    analysis = PolicyAnalysis.model_validate(_analysis_payload(division_code="Z99"))

    assert (
        validate_analysis(analysis, {"C", "C34"}, "支持制造业设备更新。").opportunities
        == []
    )


@pytest.mark.parametrize(
    ("section_code", "division_code"),
    [
        ("C34", "C34"),
        ("C", "C341"),
        ("C", "A01"),
    ],
)
def test_validate_analysis_rejects_wrong_level_or_mismatched_industry_hierarchy(
    section_code: str, division_code: str
) -> None:
    analysis = PolicyAnalysis.model_validate(
        _analysis_payload(section_code=section_code, division_code=division_code)
    )

    result = validate_analysis(
        analysis,
        {"A", "A01", "C", "C34", "C341"},
        "支持制造业设备更新。",
    )

    assert result.opportunities == []


def test_validate_analysis_accepts_supported_evidence_after_whitespace_normalization() -> None:
    analysis = PolicyAnalysis.model_validate(
        _analysis_payload(evidence_quote="支持 制造业设备\n更新")
    )
    analysis.summary = "面向客户的自由概括，不要求逐字出现在正文"

    result = validate_analysis(
        analysis,
        {"C", "C34"},
        "第一段：支持\t制造业设备   更新。",
    )

    assert len(result.opportunities) == 1


def test_validate_analysis_overwrites_model_location_with_verified_quote_offset() -> None:
    payload = _analysis_payload(evidence_quote="支持制造业设备更新")
    payload["opportunities"][0]["evidence"][0]["location"] = "外部网页第99段"
    analysis = PolicyAnalysis.model_validate(payload)

    result = validate_analysis(
        analysis,
        {"C", "C34"},
        "政策导语。支持制造业设备更新。其他内容。",
    )

    assert result.opportunities[0].evidence[0].location == "正文字符6-14"
    assert result.opportunities[0].evidence[0].location != "外部网页第99段"


def test_validate_analysis_removes_opportunity_with_fabricated_evidence() -> None:
    analysis = PolicyAnalysis.model_validate(
        _analysis_payload(evidence_quote="按设备投资额给予百分之十补贴")
    )

    result = validate_analysis(analysis, {"C", "C34"}, "支持制造业设备更新。")

    assert result.opportunities == []


def test_validate_analysis_requires_every_evidence_quote_to_be_supported() -> None:
    payload = _analysis_payload()
    payload["opportunities"][0]["evidence"].append(
        {"quote": "另行给予百万元奖励", "location": "第2段"}
    )
    analysis = PolicyAnalysis.model_validate(payload)

    result = validate_analysis(analysis, {"C", "C34"}, "支持制造业设备更新。")

    assert result.opportunities == []


def test_static_analyzer_validates_codes_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("StaticAnalyzer must not make network calls")

    monkeypatch.setattr(httpx, "post", reject_network)
    analyzer = StaticAnalyzer(
        PolicyAnalysis.model_validate(_analysis_payload(division_code="Z99"))
    )

    result = analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert result.opportunities == []


def test_openai_analyzer_sends_only_normalized_text_and_allowed_local_values(
    caplog: pytest.LogCaptureFixture,
    httpx_mock,
) -> None:
    caplog.set_level("INFO")
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"is_benefit_policy":true,"summary":"设备更新",'
                            '"support_direction":"更新","opportunities":[]}'
                        )
                    }
                }
            ]
        },
    )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1/",
        api_key="runtime-secret",
        model="policy-model",
    )

    result = analyzer.analyze(_document(), {"C34", "C"}, ["节能环保"])

    request = httpx_mock.get_request()
    assert request is not None
    payload = request.read().decode()
    request_body = json.loads(payload)
    user_prompt = request_body["messages"][1]["content"]
    assert "支持制造业设备更新。" in payload
    assert "不应发送给模型的标题" not in payload
    assert "不应发送给模型的原始页面文本" not in payload
    assert "https://www.miit.gov.cn/policy/1" not in payload
    assert '"response_format":{"type":"json_object"}' in payload
    assert "authoritative JSON Schema" in user_prompt
    assert '"additionalProperties":false' in user_prompt
    assert "每条 evidence.quote" in user_prompt
    assert "summary 可概括" in user_prompt
    assert "C34" in payload
    assert "节能环保" in payload
    assert result.opportunities == []
    assert "LLM 请求开始" in caplog.text
    assert "status=200" in caplog.text
    assert "runtime-secret" not in caplog.text


def test_user_prompt_template_supports_runtime_placeholders() -> None:
    template = (
        "正文={{document_text}}\n行业={{industry_catalog}}\n"
        "标签={{business_tags}}\n结构={{json_schema}}"
    )

    prompt = build_user_prompt(
        "支持设备更新。",
        {"C": "制造业"},
        ["节能环保"],
        template,
    )

    assert "正文=支持设备更新。" in prompt
    assert "行业={'C': '制造业'}" in prompt
    assert "标签=['节能环保']" in prompt
    assert '"title":"PolicyAnalysis"' in prompt


def test_user_prompt_template_requires_all_safe_placeholders() -> None:
    with pytest.raises(ValueError, match="缺少占位符"):
        validate_user_prompt_template("只分析 {{document_text}}")


def test_openai_analyzer_uses_runtime_prompt_overrides(
    monkeypatch: pytest.MonkeyPatch,
    httpx_mock,
) -> None:
    custom_template = "自定义任务\n" + USER_PROMPT_TEMPLATE
    monkeypatch.setenv("OPPORTUNITY_RADAR_SYSTEM_PROMPT", "自定义系统角色")
    monkeypatch.setenv("OPPORTUNITY_RADAR_USER_PROMPT_TEMPLATE", custom_template)
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"is_benefit_policy":true,"summary":"设备更新",'
                            '"support_direction":"更新","opportunities":[]}'
                        )
                    }
                }
            ]
        },
    )

    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )
    analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    request = httpx_mock.get_request()
    assert request is not None
    request_body = json.loads(request.read().decode())
    assert request_body["messages"][0]["content"] == "自定义系统角色"
    assert request_body["messages"][1]["content"].startswith("自定义任务")


def test_openai_analyzer_does_not_return_fabricated_subsidy_opportunity(
    httpx_mock,
) -> None:
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            _analysis_payload(
                                evidence_quote="按设备投资额给予百分之十补贴"
                            ),
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
    )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    result = analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert result.opportunities == []


@pytest.mark.parametrize(
    "payload",
    [
        {**_analysis_payload(), "unexpected_root_field": "discarding this is unsafe"},
        {
            **_analysis_payload(),
            "opportunities": [
                {
                    **_analysis_payload()["opportunities"][0],
                    "unexpected_opportunity_field": "discarding this is unsafe",
                }
            ],
        },
        {
            **_analysis_payload(),
            "opportunities": [
                {
                    **_analysis_payload()["opportunities"][0],
                    "evidence": [
                        {
                            "quote": "支持制造业设备更新",
                            "location": "第1段",
                            "unexpected_evidence_field": "discarding this is unsafe",
                        }
                    ],
                }
            ],
        },
    ],
)
def test_openai_analyzer_rejects_unknown_json_fields(httpx_mock, payload) -> None:
    for _ in range(2):
        httpx_mock.add_response(
            url="https://ai.example/v1/chat/completions",
            json={
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            },
        )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])


@pytest.mark.parametrize(
    "payload",
    [
        {**_analysis_payload(), "is_benefit_policy": "true"},
        {
            **_analysis_payload(),
            "opportunities": [
                {
                    **_analysis_payload()["opportunities"][0],
                    "confidence": "0.8",
                }
            ],
        },
    ],
)
def test_openai_analyzer_rejects_schema_invalid_coerced_types(
    httpx_mock, payload
) -> None:
    for _ in range(2):
        httpx_mock.add_response(
            url="https://ai.example/v1/chat/completions",
            json={
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            },
        )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    with pytest.raises(ValidationError):
        analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])


@pytest.mark.parametrize(
    "content, expected_exception",
    [
        ("not json", ValueError),
        ('{"is_benefit_policy": true}', ValidationError),
    ],
)
def test_openai_analyzer_rejects_invalid_output(
    httpx_mock, content: str, expected_exception: type[Exception]
) -> None:
    for _ in range(2):
        httpx_mock.add_response(
            url="https://ai.example/v1/chat/completions",
            json={"choices": [{"message": {"content": content}}]},
        )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    with pytest.raises(expected_exception):
        analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])


@pytest.mark.parametrize(
    "payload",
    [
        _analysis_payload(section_name="虚构制造业"),
        _analysis_payload(division_name="虚构大类"),
        _analysis_payload(business_tags=["未配置标签"]),
        _analysis_payload(scenarios=["授信审批"]),
    ],
)
def test_validate_analysis_rejects_noncanonical_names_tags_and_scenarios(payload) -> None:
    analysis = PolicyAnalysis.model_validate(payload)

    result = validate_analysis(
        analysis,
        {"C": "制造业", "C34": "通用设备制造业"},
        ["节能环保"],
        "支持制造业设备更新。",
    )

    assert result.opportunities == []


@pytest.mark.parametrize(
    "first_content",
    [
        "not json",
        '{"is_benefit_policy": true}',
    ],
)
def test_openai_analyzer_retries_invalid_json_or_schema_once(
    httpx_mock, first_content: str
) -> None:
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={"choices": [{"message": {"content": first_content}}]},
    )
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"is_benefit_policy":true,"summary":"设备更新",'
                            '"support_direction":"更新","opportunities":[]}'
                        )
                    }
                }
            ]
        },
    )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    result = analyzer.analyze(
        _document(),
        {"C": "制造业", "C34": "通用设备制造业"},
        ["节能环保"],
    )

    assert result.summary == "设备更新"
    assert len(httpx_mock.get_requests()) == 2


def test_openai_analyzer_retries_timeout_once(httpx_mock) -> None:
    httpx_mock.add_exception(
        httpx.ReadTimeout("model timed out"),
        url="https://ai.example/v1/chat/completions",
    )
    httpx_mock.add_response(
        url="https://ai.example/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"is_benefit_policy":true,"summary":"设备更新",'
                            '"support_direction":"更新","opportunities":[]}'
                        )
                    }
                }
            ]
        },
    )
    analyzer = OpenAICompatibleAnalyzer(
        base_url="https://ai.example/v1",
        api_key="runtime-secret",
        model="policy-model",
    )

    result = analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert result.summary == "设备更新"
    assert len(httpx_mock.get_requests()) == 2


def test_minimax_anthropic_analyzer_uses_messages_protocol_and_text_blocks(
    httpx_mock,
) -> None:
    assert hasattr(client_module, "MiniMaxAnthropicAnalyzer")
    response_json = json.dumps(
        {
            "is_benefit_policy": True,
            "summary": "设备更新",
            "support_direction": "更新",
            "opportunities": [],
        },
        ensure_ascii=False,
    )
    httpx_mock.add_response(
        url="https://api.minimaxi.com/anthropic/v1/messages",
        json={
            "content": [
                {"type": "thinking", "thinking": "internal reasoning"},
                {"type": "text", "text": response_json[:35]},
                {"type": "text", "text": response_json[35:]},
            ]
        },
    )
    analyzer = client_module.MiniMaxAnthropicAnalyzer(
        base_url="https://api.minimaxi.com/anthropic/",
        api_key="runtime-secret",
        model="MiniMax-M3",
    )

    result = analyzer.analyze(
        _document(),
        {"C": "制造业", "C34": "通用设备制造业"},
        ["节能环保"],
    )

    request = httpx_mock.get_request()
    assert request is not None
    request_body = json.loads(request.read())
    assert request.headers["X-Api-Key"] == "runtime-secret"
    assert request_body["model"] == "MiniMax-M3"
    assert request_body["system"] == (
        "你是政策商机分析助手。只依据提供的政策正文，不得浏览、搜索或使用任何外部来源，"
        "不得编造文号、日期、补贴、企业事实或政策资格。每条行业机会必须给出不超过240字"
        "的原文短摘录和定位。禁止承诺补贴获得、融资审批或政府背书。只输出与给定 JSON "
        "Schema 匹配的 JSON。"
    )
    assert request_body["messages"][0]["role"] == "user"
    user_prompt = request_body["messages"][0]["content"][0]["text"]
    assert "支持制造业设备更新。" in user_prompt
    assert "C34" in user_prompt
    assert "节能环保" in user_prompt
    serialized_request = json.dumps(request_body, ensure_ascii=False)
    assert "不应发送给模型的标题" not in serialized_request
    assert "不应发送给模型的原始页面文本" not in serialized_request
    assert "https://www.miit.gov.cn/policy/1" not in serialized_request
    assert result.summary == "设备更新"


@pytest.mark.parametrize(
    "first_content",
    [
        "not json",
        '{"is_benefit_policy": true}',
    ],
)
def test_minimax_anthropic_analyzer_retries_invalid_json_or_schema_once(
    httpx_mock, first_content: str
) -> None:
    httpx_mock.add_response(
        url="https://api.minimaxi.com/anthropic/v1/messages",
        json={"content": [{"type": "text", "text": first_content}]},
    )
    httpx_mock.add_response(
        url="https://api.minimaxi.com/anthropic/v1/messages",
        json={
            "content": [
                {
                    "type": "text",
                    "text": (
                        '{"is_benefit_policy":true,"summary":"设备更新",'
                        '"support_direction":"更新","opportunities":[]}'
                    ),
                }
            ]
        },
    )
    analyzer = client_module.MiniMaxAnthropicAnalyzer(
        base_url="https://api.minimaxi.com/anthropic",
        api_key="runtime-secret",
        model="MiniMax-M3",
    )

    result = analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert result.summary == "设备更新"
    assert len(httpx_mock.get_requests()) == 2


def test_minimax_anthropic_analyzer_retries_timeout_once(httpx_mock) -> None:
    httpx_mock.add_exception(
        httpx.ReadTimeout("model timed out"),
        url="https://api.minimaxi.com/anthropic/v1/messages",
    )
    httpx_mock.add_response(
        url="https://api.minimaxi.com/anthropic/v1/messages",
        json={
            "content": [
                {
                    "type": "text",
                    "text": (
                        '{"is_benefit_policy":true,"summary":"设备更新",'
                        '"support_direction":"更新","opportunities":[]}'
                    ),
                }
            ]
        },
    )
    analyzer = client_module.MiniMaxAnthropicAnalyzer(
        base_url="https://api.minimaxi.com/anthropic",
        api_key="runtime-secret",
        model="MiniMax-M3",
    )

    result = analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert result.summary == "设备更新"
    assert len(httpx_mock.get_requests()) == 2


def test_minimax_anthropic_analyzer_stops_after_one_retry(httpx_mock) -> None:
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api.minimaxi.com/anthropic/v1/messages",
            json={"content": [{"type": "text", "text": "not json"}]},
        )
    analyzer = client_module.MiniMaxAnthropicAnalyzer(
        base_url="https://api.minimaxi.com/anthropic",
        api_key="runtime-secret",
        model="MiniMax-M3",
    )

    with pytest.raises(json.JSONDecodeError):
        analyzer.analyze(_document(), {"C", "C34"}, ["节能环保"])

    assert len(httpx_mock.get_requests()) == 2
