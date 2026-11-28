"""Research-only market intelligence primitives.

Point-in-time event and quantitative primitives for news-driven market
research: immutable versioned events, surprise calculations, append-only
storage, price series with corporate-action adjustment, event studies,
earnings/macro surprise datasets, scenario forecasting with calibration, and
structured report assembly. No network, broker, model, or third-party
dependency; standard library only.
"""

from .core import (
    MarketEvent,
    Surprise,
    abnormal_return,
    compute_surprise,
    events_as_of,
    expected_return,
    parse_utc_timestamp,
    simple_return,
)
from .storage import EventStore, deserialize_event, load_events, serialize_event, to_jsonl
from .prices import (
    CorporateAction,
    PriceObservation,
    PriceSeries,
    aligned_returns,
)
from .event_windows import (
    EventStudyResult,
    EventWindow,
    MarketModel,
    abnormal_return_market_model,
    cumulative_abnormal_return,
    event_window_returns,
    ols_fit,
    run_event_study,
)
from .datasets import (
    EarningsRecord,
    ForecastSnapshot,
    MacroReleaseRecord,
    SurpriseDataset,
    forecast_dispersion,
)
from .forecasting import (
    Scenario,
    ScenarioForecast,
    PredictionScorecard,
    prediction_variance,
)
from .reporting import (
    MarketIntelligenceReport,
    MarketSituation,
    build_report,
)

__all__ = [
    # core
    "MarketEvent",
    "Surprise",
    "abnormal_return",
    "compute_surprise",
    "events_as_of",
    "expected_return",
    "parse_utc_timestamp",
    "simple_return",
    # storage
    "EventStore",
    "deserialize_event",
    "load_events",
    "serialize_event",
    "to_jsonl",
    # prices
    "CorporateAction",
    "PriceObservation",
    "PriceSeries",
    "aligned_returns",
    # event windows
    "EventStudyResult",
    "EventWindow",
    "MarketModel",
    "abnormal_return_market_model",
    "cumulative_abnormal_return",
    "event_window_returns",
    "ols_fit",
    "run_event_study",
    # datasets
    "EarningsRecord",
    "ForecastSnapshot",
    "MacroReleaseRecord",
    "SurpriseDataset",
    "forecast_dispersion",
    # forecasting
    "Scenario",
    "ScenarioForecast",
    "PredictionScorecard",
    "prediction_variance",
    # reporting
    "MarketIntelligenceReport",
    "MarketSituation",
    "build_report",
]
