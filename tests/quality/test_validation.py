import pytest

from opportunity_radar.quality.scripts import append_disclaimer, is_compliant_script


def test_script_rejects_approval_and_subsidy_promises() -> None:
    assert is_compliant_script("我们保证您一定获得补贴并审批通过") is False
    assert is_compliant_script("补贴保证到账") is False
    assert is_compliant_script("我们可以交流近期设备更新安排") is True


def test_script_rejects_government_endorsement_and_appends_mandated_disclaimer() -> None:
    assert is_compliant_script("该方案由政府背书") is False
    assert append_disclaimer("交流近期设备更新安排") == (
        "交流近期设备更新安排\n\n"
        "政策解读仅供业务参考，以政策原文及主管部门解释为准；"
        "融资方案及审批结果以正式评估为准。"
    )


@pytest.mark.parametrize(
    "script",
    [
        "承诺补贴必将到账",
        "保证\n客户获得补贴",
        "政府会为该融资方案兜底",
        "政府兜底本项目的融资",
        "政府将担保本方案",
    ],
)
def test_script_rejects_newline_guarantees_and_government_financing_backstops(
    script: str,
) -> None:
    assert is_compliant_script(script) is False
