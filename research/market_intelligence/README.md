# Market Intelligence Research Core

Status: **point-in-time research foundation with storage, prices, event studies, surprise datasets, scenario forecasting and report assembly; no live feed, trained model, or trading signal**.

This module is isolated under `research/` and is not part of Capri's production runtime. It has no network access, broker integration, API keys, paid dependencies or order execution. The whole module uses only the Python standard library.

## What exists

**Events and surprises** (`core.py`)
- Immutable, versioned `MarketEvent` records.
- Separate underlying event occurrence, source publication, version-availability and collector-observation timestamps.
- UTC normalization and rejection of timezone-naive timestamps.
- Point-in-time selection of the latest event version known at a decision timestamp.
- Raw and direction-adjusted numeric surprise calculations.
- Probability-weighted scenario return, simple returns and benchmark-relative abnormal returns.

**Persistent storage** (`storage.py`)
- Deterministic, hash-tagged event serialization.
- Append-only, hash-chained JSONL `EventStore`: a correction is appended, never overwritten.
- Load-time verification of content hashes and the chain, so tampering or gaps are detected.

**Prices and corporate actions** (`prices.py`)
- Point-in-time `PriceSeries` with `as_of` visibility (no future price leakage).
- OHLCV `PriceObservation` validation.
- Retroactive split and dividend adjustment for continuous adjusted returns.
- Benchmark-relative return and multi-instrument `aligned_returns`.

**Event studies** (`event_windows.py`)
- `EventWindow` construction around an event timestamp.
- OLS market model (`alpha`, `beta`, `r_squared`) fit on a separate estimation window.
- Market-model abnormal returns, event-window returns, and cumulative abnormal return (CAR).

**Surprise datasets** (`datasets.py`)
- `EarningsRecord` and `MacroReleaseRecord` with direction-aware surprises.
- Point-in-time `ForecastSnapshot` (consensus, dispersion, analyst count) with `snapshot_at` lookup.
- `SurpriseDataset` aggregation and `forecast_dispersion`.

**Forecasting and scoring** (`forecasting.py`)
- `Scenario` and `ScenarioForecast` with expected return, variance and volatility.
- `PredictionScorecard`: Brier score, log loss, direction accuracy, and calibration bins for out-of-sample scoring.

**Reporting** (`reporting.py`)
- `MarketIntelligenceReport` assembling the standard nine-section report: market situation, developments, expectations, fundamental impact, technical/positioning, cross-market impact, prediction, risk/invalidation, and sourced verification.

A correction is represented as a new event version with the same `source_event_id` and a later `available_at`. Do not overwrite an earlier version. This is necessary to reconstruct what the market could have known at a historical decision time.

## First supported use

A caller can create event records from a verified company announcement, SEC filing, or macro release, then call `events_as_of(records, decision_at)` before building any features. This prevents a future announcement or later correction from leaking into an earlier prediction.

Example:

```python
from datetime import datetime, timezone
from market_intelligence import MarketEvent, events_as_of

event = MarketEvent(
    event_id="sec-8k-2026-001-v1",
    source_event_id="sec-8k-2026-001",
    instrument="NASDAQ:NVDA",
    category="earnings",
    headline="Quarterly results",
    source_name="Company investor relations",
    source_url="https://example.com/investors/news",
    source_tier="primary",
    published_at=datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc),
    available_at=datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc),
    observed_at=datetime(2026, 11, 28, 10, 1, tzinfo=timezone.utc),
)

known_at_decision = events_as_of(
    [event], datetime(2026, 11, 28, 10, 0, 30, tzinfo=timezone.utc)
)
```

The example is illustrative; it is not a real announcement.

## What does not exist yet

- News discovery, scraping, or live source adapters (the `SOURCES.md` register documents access and limits; no provider is called).
- Automated market price-history ingestion (price data is supplied by the caller).
- Automated consensus-estimate history collection (snapshots are supplied by the caller).
- Macro-release calendars and vintage-aware automated adapters.
- Event classification, entity resolution, deduplication and claim extraction.
- Trained probabilistic models, factor/market-model estimation on real data, or walk-forward model selection.
- Dashboards, alerts, background scheduling or broker connections.

Do not describe the current module as an AI prediction engine. It is a transparent foundation for preserving point-in-time evidence and calculating defensible quantities; the forecasting and scoring layers measure whether a method works rather than asserting that it does.

## Research sequence

1. ✅ Stabilize timestamp and source-version contracts. (`core.py`)
2. ✅ Add validated deterministic event serialization and append-only storage. (`storage.py`)
3. ⬜ Add source adapters only after documenting access, cost, rate limits, licensing and historical coverage. (`SOURCES.md` documents the landscape; no adapter is implemented.)
4. ✅ Build point-in-time price and benchmark series with corporate-action adjustment. (`prices.py`)
5. ✅ Implement event windows and market-model abnormal returns. (`event_windows.py`)
6. ✅ Build earnings and macro surprise datasets, including snapshots and forecast dispersion. (`datasets.py`)
7. ⬜ Add event categories, cross-asset transmission and positioning with their actual publication lags.
8. ⬜ Compare simple baselines before complex ML; calibrate probabilities and validate out of sample. (Scoring primitives exist in `forecasting.py`; model comparison on real data does not.)
9. ✅ Keep paper research separate from real-money execution. (Module is isolated under `research/` with no execution path.)

## Validation rules

- All timestamps are timezone-aware and normalized to UTC.
- Store publication time, correction/version availability and ingestion/observation time separately.
- Use only data available at the prediction cutoff.
- Preserve first releases and later revisions as distinct vintages.
- Keep consensus as it stood before the release, not a value revised after it.
- Exclude overlapping/confounded events or model them explicitly.
- Include splits, dividends, delistings, trading halts, market hours and benchmark alignment.
- Include spread, commission, slippage, borrow/funding, market impact and realistic execution delays in any later strategy simulation.
- Keep chronological train/validation/test splits and an untouched final holdout.
- Report sample sizes, uncertainty, calibration and regime-specific results.
- Record failed experiments; do not tune on the final holdout.

## Runtime and verification

The repository supports Python 3.15.x. The whole module uses only the standard library. The committed contract tests cover every layer (83 tests across core, storage, prices, event windows, datasets, forecasting and reporting) and run offline via `python -m unittest discover -s tests`. The repository's full quality workflow is the authoritative verification gate.
