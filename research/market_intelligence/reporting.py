"""Structured market intelligence report assembly.

This turns the gathered evidence — a point-in-time event, a surprise, a
scenario forecast, and its invalidation conditions — into the standard report
structure: market situation, developments, expectations, fundamental impact,
technical/positioning, cross-market impact, the probability-weighted prediction,
risk/invalidation, and sourced verification.

The report never invents market data: every field is supplied by the caller from
verified inputs, and missing sections are reported as absent rather than
fabricated. Only the Python standard library is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .core import parse_utc_timestamp
from .forecasting import ScenarioForecast


@dataclass(frozen=True)
class MarketSituation:
    """Snapshot of the instrument's current market context."""

    instrument: str
    decision_at: datetime
    price: float | None = None
    trend: str | None = None
    relative_strength: float | None = None
    volatility: float | None = None
    liquidity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        object.__setattr__(self, "decision_at", parse_utc_timestamp(self.decision_at))


@dataclass(frozen=True)
class ReportSection:
    """A named report section with rendered content lines."""

    title: str
    lines: tuple[str, ...]


@dataclass
class MarketIntelligenceReport:
    """A complete, sourced market intelligence report for one instrument."""

    instrument: str
    decision_at: datetime
    situation: MarketSituation
    developments: tuple[str, ...] = ()
    expectations: tuple[str, ...] = ()
    fundamental_impact: tuple[str, ...] = ()
    technical_positioning: tuple[str, ...] = ()
    cross_market: tuple[str, ...] = ()
    forecast: ScenarioForecast | None = None
    risk_invalidation: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        object.__setattr__(self, "decision_at", parse_utc_timestamp(self.decision_at))

    def prediction_block(self) -> str:
        """Render the probability-weighted prediction section."""
        if self.forecast is None:
            return "Prediction: not available (no scenario forecast supplied)."
        lines = [
            f"Expected return: {self.forecast.expected_return:+.4f}",
            f"Expected volatility: {self.forecast.expected_volatility:.4f}",
            "Scenarios:",
        ]
        for scenario in self.forecast.scenarios:
            lines.append(
                f"  - {scenario.name}: {scenario.probability:.0%} -> "
                f"{scenario.return_value:+.2%}"
            )
        return "\n".join(lines)

    def render(self) -> str:
        """Render the full report as structured markdown text."""
        sections: list[ReportSection] = [
            ReportSection(
                "1. Market situation",
                self._situation_lines(),
            ),
            ReportSection(
                "2. Latest developments",
                self._bullet_lines(self.developments),
            ),
            ReportSection(
                "3. Expectations",
                self._bullet_lines(self.expectations),
            ),
            ReportSection(
                "4. Fundamental impact",
                self._bullet_lines(self.fundamental_impact),
            ),
            ReportSection(
                "5. Technical and positioning",
                self._bullet_lines(self.technical_positioning),
            ),
            ReportSection(
                "6. Cross-market impact",
                self._bullet_lines(self.cross_market),
            ),
            ReportSection("7. Prediction", self.prediction_block().splitlines()),
            ReportSection(
                "8. Risk and invalidation",
                self._bullet_lines(self.risk_invalidation),
            ),
            ReportSection(
                "9. Sources and verification",
                self._bullet_lines(self.sources),
            ),
        ]
        parts = [
            f"# CAPRI MARKET INTELLIGENCE REPORT — {self.instrument}",
            f"Decision time: {self.decision_at.isoformat()}",
            "",
        ]
        for section in sections:
            parts.append(f"## {section.title}")
            parts.extend(section.lines if section.lines else ["- Not available."])
            parts.append("")
        return "\n".join(parts)

    def _situation_lines(self) -> tuple[str, ...]:
        lines: list[str] = []
        situation = self.situation
        if situation.price is not None:
            lines.append(f"- Current price: {situation.price}")
        if situation.trend is not None:
            lines.append(f"- Trend: {situation.trend}")
        if situation.relative_strength is not None:
            lines.append(f"- Relative strength: {situation.relative_strength:.4f}")
        if situation.volatility is not None:
            lines.append(f"- Volatility: {situation.volatility:.4f}")
        if situation.liquidity is not None:
            lines.append(f"- Liquidity: {situation.liquidity}")
        return tuple(lines)

    @staticmethod
    def _bullet_lines(items: Sequence[str]) -> tuple[str, ...]:
        if not items:
            return ()
        return tuple(f"- {item}" for item in items)


def build_report(
    instrument: str,
    decision_at: str | datetime,
    situation: MarketSituation,
    *,
    developments: Sequence[str] = (),
    expectations: Sequence[str] = (),
    fundamental_impact: Sequence[str] = (),
    technical_positioning: Sequence[str] = (),
    cross_market: Sequence[str] = (),
    forecast: ScenarioForecast | None = None,
    risk_invalidation: Sequence[str] = (),
    sources: Sequence[str] = (),
) -> MarketIntelligenceReport:
    """Construct a ``MarketIntelligenceReport`` from verified inputs."""
    return MarketIntelligenceReport(
        instrument=instrument,
        decision_at=parse_utc_timestamp(decision_at),
        situation=situation,
        developments=tuple(developments),
        expectations=tuple(expectations),
        fundamental_impact=tuple(fundamental_impact),
        technical_positioning=tuple(technical_positioning),
        cross_market=tuple(cross_market),
        forecast=forecast,
        risk_invalidation=tuple(risk_invalidation),
        sources=tuple(sources),
    )
