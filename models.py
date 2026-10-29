from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MarketContext:
    asset: str
    symbol: str

    price: Optional[float]

    ema50: Optional[float]
    ema200: Optional[float]

    trend: str

    change_pct: Optional[float] = None
    atr_pct: Optional[float] = None


@dataclass
class Analysis:
    macro_bias: str
    technical_bias: str

    alignment: str

    risk: str

    summary: str
    technical_summary: str

    should_alert: bool

    impact: str
    confidence: str

    affected_assets: list[str] = field(
        default_factory=list
    )

    source_name: str = ""
    source_url: str = ""

    evidence: str = ""

    raw: dict[str, Any] = field(
        default_factory=dict
    )