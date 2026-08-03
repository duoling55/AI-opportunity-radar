from __future__ import annotations

from opportunity_radar.discovery.models import ComplianceReport, ScoreBreakdownItem, ScoreResult

_LEASE = ("设备租赁", "融资租赁", "绿色租赁", "售后回租", "设备直租", "租赁")
_OTHER_FIN = ("贴息", "担保", "信贷", "融资支持", "贷款", "再贷款")
_INDUSTRY = ("产业", "制造业", "新能源", "汽车", "化工", "医药", "装备")

_ADMIN = {"国家": 30, "省": 20, "市": 10}
_ACCESS = {"pass": 10, "needs_attention": 5, "not_recommended": 0}


class ImportanceScorer:
    def score(
        self, source: dict, samples: list[dict], compliance: ComplianceReport
    ) -> ScoreResult:
        breakdown: list[ScoreBreakdownItem] = [
            self._admin_level(source),
            self._industry_relevance(source, samples),
            self._signal_density(samples),
            self._update_freq(samples),
            self._accessibility(compliance),
            self._domain_authority(source),
        ]
        total = sum(b.score for b in breakdown)
        level = "高" if total >= 80 else "中" if total >= 60 else "低"
        return ScoreResult(priority_score=total, priority_level=level, score_breakdown=breakdown)

    def _admin_level(self, src: dict) -> ScoreBreakdownItem:
        s = _ADMIN.get(src["admin_level"], 10)
        return ScoreBreakdownItem(dimension="行政层级", score=s, max=30, reason=f"{src['admin_level']}级信源 +{s}")

    def _industry_relevance(self, src: dict, samples: list[dict]) -> ScoreBreakdownItem:
        blob = src.get("column_name", "") + "".join(p["title"] for p in samples)
        if any(k in blob for k in _LEASE):
            return ScoreBreakdownItem(dimension="行业相关性", score=25, max=25, reason="金融租赁直接相关 +25")
        if any(k in blob for k in _OTHER_FIN):
            return ScoreBreakdownItem(dimension="行业相关性", score=15, max=25, reason="其他金融 +15")
        if any(k in blob for k in _INDUSTRY):
            return ScoreBreakdownItem(dimension="行业相关性", score=10, max=25, reason="产业通用 +10")
        return ScoreBreakdownItem(dimension="行业相关性", score=5, max=25, reason="非金融 +5")

    def _signal_density(self, samples: list[dict]) -> ScoreBreakdownItem:
        if not samples:
            return ScoreBreakdownItem(dimension="融资信号密度", score=5, max=20, reason="无样例 +5")
        hit = sum(1 for p in samples if any(k in p["title"] for k in _LEASE + _OTHER_FIN))
        ratio = hit / len(samples)
        if ratio >= 0.6:
            return ScoreBreakdownItem(dimension="融资信号密度", score=20, max=20, reason=f"样例密度 {int(ratio * 100)}%（高）+20")
        if ratio >= 0.3:
            return ScoreBreakdownItem(dimension="融资信号密度", score=10, max=20, reason=f"样例密度 {int(ratio * 100)}%（中）+10")
        return ScoreBreakdownItem(dimension="融资信号密度", score=5, max=20, reason=f"样例密度 {int(ratio * 100)}%（低）+5")

    def _update_freq(self, samples: list[dict]) -> ScoreBreakdownItem:
        if len(samples) < 3:
            return ScoreBreakdownItem(dimension="政策更新频率", score=5, max=10, reason="样例不足 +5")
        return ScoreBreakdownItem(dimension="政策更新频率", score=5, max=10, reason="中频（月更）+5")

    def _accessibility(self, compliance: ComplianceReport) -> ScoreBreakdownItem:
        s = _ACCESS.get(compliance.check_result, 0)
        return ScoreBreakdownItem(dimension="合规可采集性", score=s, max=10, reason=f"{compliance.check_result} +{s}")

    def _domain_authority(self, src: dict) -> ScoreBreakdownItem:
        s = 5 if src["domain"].endswith(".gov.cn") else 0
        return ScoreBreakdownItem(
            dimension="域名权威性", score=s, max=5, reason=("gov.cn 官方 +5" if s else "非 gov.cn +0")
        )
