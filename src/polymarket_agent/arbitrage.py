from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Sequence

DEFAULT_SETTLEMENT_FEE_RATE = 0.02
DEFAULT_TAKER_FEE_RATE = 0.001
MIN_PROFIT_THRESHOLD = 0.0005  # 0.05% buffer so we ignore dust-sized windows


@dataclass(slots=True)
class OutcomeQuote:
    label: str
    price: float
    max_size: float
    token_id: str | None = None


@dataclass(slots=True)
class ArbitrageOpportunity:
    event_id: str
    event_title: str
    market_id: str
    closes_at: str | None
    source: str
    unit_cost: float
    unit_expected_payout: float
    unit_profit: float
    profit_rate: float
    suggested_size: float
    suggested_investment: float
    expected_profit: float
    outcomes: List[OutcomeQuote] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class ArbitrageDataProvider:
    """Simple interface so we can swap mock data with live scanners later."""

    def list_candidates(self) -> Sequence[dict]:  # pragma: no cover - interface
        raise NotImplementedError


class MockArbitrageDataProvider(ArbitrageDataProvider):
    """Hard-coded dataset representing plausible internal Polymarket arbitrage windows."""

    def list_candidates(self) -> Sequence[dict]:
        return [
            {
                "event_id": "EVT-2025-001",
                "event_title": "Will ETH ETFs gather more than $20B AUM by 2025?",
                "market_id": "120345",
                "closes_at": "2025-12-31",
                "outcomes": [
                    {"label": "Yes", "price": 0.47, "max_size": 900, "token_id": "0xeth_yes"},
                    {"label": "No", "price": 0.47, "max_size": 860, "token_id": "0xeth_no"},
                    {"label": "Tie/Push", "price": 0.03, "max_size": 600, "token_id": "0xeth_push"},
                ],
                "settlement_fee_rate": 0.02,
                "trading_fee_rate": 0.0015,
                "notes": ["Gamma order book引用 Coinbase/MMX 做市价"],
                "risk_notes": ["Push outcome 流动性最弱，需关注新增挂单"],
            },
            {
                "event_id": "EVT-2025-042",
                "event_title": "Who will win the 2028 US Presidential Election?",
                "market_id": "119876",
                "closes_at": "2028-11-05",
                "outcomes": [
                    {"label": "Democrat", "price": 0.44, "max_size": 1500, "token_id": "0xdem"},
                    {"label": "Republican", "price": 0.43, "max_size": 1325, "token_id": "0xgop"},
                    {"label": "Independent", "price": 0.08, "max_size": 420, "token_id": "0xind"},
                    {"label": "Other", "price": 0.02, "max_size": 380, "token_id": "0xoth"},
                ],
                "settlement_fee_rate": 0.015,
                "trading_fee_rate": 0.001,
                "notes": ["盘口价来自 top-of-book depth 1000 USDC"],
                "risk_notes": [
                    "竞选周期跨度较长，期间波动可能导致追加保证金",
                    "独立/Other 报价相对稀薄，超额下单会吞吃深度"
                ],
            },
            {
                "event_id": "EVT-2025-089",
                "event_title": "Total BTC price on 1 Dec 2025 (Bucketed)",
                "market_id": "118222",
                "closes_at": "2025-12-01",
                "outcomes": [
                    {"label": "< $65k", "price": 0.24, "max_size": 700, "token_id": "0xbtc_low"},
                    {"label": "$65k - $80k", "price": 0.32, "max_size": 640, "token_id": "0xbtc_mid"},
                    {"label": "$80k - $95k", "price": 0.28, "max_size": 620, "token_id": "0xbtc_upper"},
                    {"label": "> $95k", "price": 0.14, "max_size": 500, "token_id": "0xbtc_high"},
                ],
                "settlement_fee_rate": 0.02,
                "trading_fee_rate": 0.001,
                "notes": ["区间市场常见内部错价案例"],
                "risk_notes": ["部分区间报价共享相同做市商，撤单风险相关"],
            },
        ]


def _normalize_outcome(raw: dict) -> OutcomeQuote | None:
    try:
        price = float(raw.get("price"))
        max_size = float(raw.get("max_size"))
    except (TypeError, ValueError):
        return None
    label = str(raw.get("label") or "").strip()
    if not label or price <= 0 or max_size <= 0:
        return None
    token_id = raw.get("token_id")
    return OutcomeQuote(label=label, price=price, max_size=max_size, token_id=token_id)


def detect_internal_arbitrage(
    client: Any,  # noqa: ARG001 - retained for future live integrations
    max_items: int = 3,
    provider: ArbitrageDataProvider | None = None,
) -> List[ArbitrageOpportunity]:
    """
    Combine outcome quotes inside the same Polymarket event and highlight bundles
    where the sum of prices (plus fees) falls below 1.0.
    """

    source = provider or MockArbitrageDataProvider()
    opportunities: List[ArbitrageOpportunity] = []

    for candidate in source.list_candidates():
        outcomes_raw = candidate.get("outcomes") or []
        quotes = list(filter(None, (_normalize_outcome(item) for item in outcomes_raw)))
        if len(quotes) < 2:
            continue

        taker_fee = float(candidate.get("trading_fee_rate") or DEFAULT_TAKER_FEE_RATE)
        settlement_fee = float(candidate.get("settlement_fee_rate") or DEFAULT_SETTLEMENT_FEE_RATE)

        unit_cost = sum(q.price * (1 + taker_fee) for q in quotes)
        unit_expected_payout = 1.0 - settlement_fee
        unit_profit = unit_expected_payout - unit_cost
        if unit_cost <= 0 or unit_profit <= MIN_PROFIT_THRESHOLD:
            continue

        profit_rate = unit_profit / unit_cost
        bundle_capacity = min((q.max_size for q in quotes), default=0)
        if bundle_capacity <= 0:
            continue

        suggested_size = bundle_capacity
        suggested_investment = suggested_size * unit_cost
        expected_profit = suggested_size * unit_profit

        risks = [
            f"最弱盘口仅约 {int(bundle_capacity)} 份对冲，超量下单会引发滑点。",
            f"假设 taker 费率 {taker_fee * 100:.2f}% 与结算费 {settlement_fee * 100:.2f}%，实际费用以链上为准。",
        ]
        risks.extend(str(note) for note in candidate.get("risk_notes") or [] if str(note).strip())

        notes = [str(note).strip() for note in candidate.get("notes") or [] if str(note).strip()]

        opportunity = ArbitrageOpportunity(
            event_id=str(candidate.get("event_id") or ""),
            event_title=str(candidate.get("event_title") or "未知事件").strip(),
            market_id=str(candidate.get("market_id") or "?"),
            closes_at=str(candidate.get("closes_at") or "").strip() or None,
            source="mock",
            unit_cost=unit_cost,
            unit_expected_payout=unit_expected_payout,
            unit_profit=unit_profit,
            profit_rate=profit_rate,
            suggested_size=suggested_size,
            suggested_investment=suggested_investment,
            expected_profit=expected_profit,
            outcomes=quotes,
            risks=risks,
            notes=notes,
        )
        opportunities.append(opportunity)
        if 0 < max_items <= len(opportunities):
            break

    return opportunities


__all__ = [
    "ArbitrageOpportunity",
    "ArbitrageDataProvider",
    "MockArbitrageDataProvider",
    "OutcomeQuote",
    "detect_internal_arbitrage",
]
