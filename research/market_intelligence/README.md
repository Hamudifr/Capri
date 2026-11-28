# Market Intelligence Research Core

Status: **initial data-contract foundation; no live feed, trained model, forecast or trading signal**.

This module is isolated under `research/` and is not part of Capri's production runtime. It has no network access, broker integration, API keys, paid dependencies or order execution. The initial core uses only the Python standard library.

## What exists

- Immutable, versioned `MarketEvent` records.
- Separate underlying event occurrence, source publication, version-availability and collector-observation timestamps.
- UTC normalization and rejection of timezone-naive timestamps.
- Point-in-time selection of the latest event version known at a decision timestamp.
- Raw and direction-adjusted numeric surprise calculations.
- Probability-weighted scenario return.
- Simple returns and benchmark-relative abnormal returns.

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

- News discovery, scraping, or source adapters.
- Market price history ingestion or corporate-action adjustment.
- Consensus-estimate history and analyst-revision snapshots.
- Macro-release calendars and vintage-aware data adapters.
- Event classification, entity resolution, deduplication and claim extraction.
- Event-window return calculations, factor/market-model estimation or statistical inference.
- Probabilistic forecasting, model training, calibration or walk-forward evaluation.
- Dashboards, alerts, background scheduling or broker connections.

Do not describe the current module as an AI prediction engine. It is an initial foundation for preserving evidence and calculating a few transparent quantities.

## Research sequence

1. Stabilize timestamp and source-version contracts.
2. Add validated CSV/JSONL import and deterministic event serialization.
3. Add source adapters only after documenting access, cost, rate limits, licensing and historical coverage.
4. Build point-in-time price and benchmark datasets with corporate-action and timezone rules.
5. Implement event windows and market-model abnormal returns.
6. Build earnings and macro surprise datasets, including revisions and forecast dispersion.
7. Add event categories, cross-asset transmission and positioning with their actual publication lags.
8. Compare simple baselines before complex ML; calibrate probabilities and validate out of sample.
9. Keep paper research separate from real-money execution.

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

## Runtime

The repository supports Python 3.15.x. The core itself uses only the standard library. Run the repository's full quality workflow for verification; this session has no local checkout, so no local test result is claimed.
