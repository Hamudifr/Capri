# News-Driven Market Intelligence: Architecture and Build Plan

Status: implementation in progress, 2026-11-28. The point-in-time research core in `research/market_intelligence/` now covers events, surprises, append-only storage, price/corporate-action series, event studies, surprise datasets, scenario forecasting with calibration, and report assembly. Live data collection and trained models remain future work.

## Objective

Build a reusable research pipeline that explains and forecasts how new information may change market prices. It must compare information with prior expectations, model transmission channels and positioning, estimate multiple scenarios, and validate forecasts against point-in-time historical outcomes.

Initial research scope: US-listed equities and US macro catalysts, with Nasdaq/S&P benchmarks, USD/rates and XAUUSD as cross-market context. Expand to European equities, FX, commodities and crypto only after the core contracts and data provenance are stable.

This is research and paper analysis only. It does not execute trades.

## Architecture

1. **Discovery** — company announcements, filings, macro calendars, regulator releases, news and scheduled catalysts.
2. **Evidence ledger** — immutable source records, source tiers, exact URLs, publication and correction timestamps, claims and conflicting evidence.
3. **Entity resolution** — map company names, tickers, share classes, ADRs, ISINs, CIKs, exchanges, indices and related instruments without conflating them.
4. **Point-in-time data store** — versioned event, price, fundamentals, consensus, macro, positioning and corporate-action observations.
5. **Feature construction** — surprise vs consensus, surprise standardized by historical forecast error, revisions, guidance delta, price/volume response, implied move, volatility, positioning and cross-asset conditions.
6. **Transmission analysis** — map event to cash flows, discount rates, risk premium, liquidity, supply/demand and affected competitors/suppliers/customers.
7. **Forecasting** — transparent base rates and scenario model first; benchmark simple statistical models before complex ML.
8. **Validation** — event studies, market-adjusted returns, walk-forward tests, calibration, transaction costs and regime/sector analysis.
9. **Reporting** — timestamped forecast, scenarios, expected return, range, confidence, counterevidence, invalidation and data gaps.
10. **Learning loop** — log every forecast before the outcome, score it later, identify systematic errors and update the model only on training/validation data.

## Non-negotiable time semantics

Keep these clocks separate:

- `event_at`: when the underlying event occurred.
- `published_at`: when the source says the information was published.
- `available_at`: when this exact source version became publicly available to the market.
- `observed_at`: when our system collected it.
- `decision_at`: forecast cutoff.
- `effective_period`: the economic or financial period measured by a datum.

A historical scrape today does not mean the story became available today; a current page also cannot prove what its earlier version said. Corrections must be new versions with later `available_at`. For backtests, require trustworthy original publication timestamps and archived version history. Exclude records whose point-in-time availability cannot be established.

## Event and expectation model

For each event, capture:

- issuer/instrument, exchange, currency, sector and event category
- primary source and corroborating sources
- source event ID and immutable version ID
- event/publication/availability/observation timestamps
- actual value, unit, reference period and previous value
- consensus median, dispersion, number of estimates and snapshot time
- prior value as known before release and revised prior value
- management guidance and prior guidance snapshot
- expected market move / implied move where reliable
- source confidence, claim verification state and unresolved contradictions

For a numeric release:

`raw_surprise = actual - consensus`

`standardized_surprise = raw_surprise / historical_forecast_error_std`

Direction-adjusted interpretation must be indicator-specific. A larger CPI number is not automatically bullish or bearish for every asset. Also compare revisions to prior periods and forecast dispersion.

For scenario outcomes:

`expected_return = sum(probability_i * return_i)`

Probabilities must sum to one, and their calibration must be evaluated over many forecasts.

## Event-study design

- Predefine event timestamp and windows before observing outcomes.
- Use regular-session, premarket, after-hours and overnight windows correctly.
- Compute asset returns and benchmark-relative abnormal returns.
- Use a market model or factor model when a simple benchmark subtraction is inadequate.
- Exclude or explicitly model overlapping company, sector and macro events.
- Use split/dividend-adjusted prices for the chosen return definition; separately preserve as-traded prices for execution analysis.
- Control for market hours, halts, stale quotes, missing bars, spreads and liquidity.
- Report sample size, confidence intervals, effect sizes and heterogeneity by regime.

## Forecast evaluation

Required metrics include directional accuracy, balanced accuracy, Brier score, log loss, calibration curves, expected-return error, interval coverage, hit rate by horizon, benchmark-relative return, turnover, drawdown and cost-adjusted expectancy. Report sample sizes and uncertainty. Compare with naive base-rate and simple linear/tree baselines.

No model is considered useful merely because its in-sample fit is strong. Use chronological splits, purging/embargo around overlapping horizons, walk-forward evaluation and a final untouched holdout. Avoid survivorship, look-ahead, restatement, selection and multiple-testing biases.

## Build phases

### Phase 1 — evidence and event contracts
- [x] Add immutable event-version record with separate published/available/observed times.
- [x] Add as-of event-version selection.
- [x] Add numeric surprise, expected-return and simple abnormal-return primitives.
- [ ] Add deterministic JSONL import/export and schema versioning.
- [ ] Add source evidence/claim records and duplicate clustering.

### Phase 2 — free, lawful source adapters
- [ ] SEC EDGAR submissions, filing documents and company facts.
- [ ] BLS releases and time series.
- [ ] FRED/ALFRED with vintage preservation.
- [ ] ECB/Eurostat/Destatis for European macro.
- [ ] CFTC COT and official Treasury/Federal Reserve sources.
- [ ] Company IR announcements and earnings calendars.
- [ ] Select an equity OHLC source only after cost, terms, coverage and point-in-time quality review.
- [ ] Select historical news/consensus archives only after rights and timestamp completeness review.

### Phase 3 — event features and reaction research
- [ ] Earnings: EPS/revenue/guidance surprise, segment KPIs, margins, cash flow, call transcript deltas and estimate revisions.
- [ ] Macro: actual vs consensus, standardized surprise, prior-period revisions and policy-rate repricing.
- [ ] Price response: gap, intraday return, volume surprise, realized volatility and benchmark/factor-adjusted response.
- [ ] Positioning: options implied move/skew, short interest, futures positioning and ETF flows with publication lags.
- [ ] Cross-asset: yields, real yields, USD, VIX, oil, gold and sector/industry returns.

### Phase 4 — forecast and evaluate
- [ ] Event-category base rates and transparent scenario forecasts.
- [ ] Baselines: unconditional base rate, logistic regression and regularized linear model.
- [ ] Tree model and temporal model only if data size and ablations justify them.
- [ ] Probability calibration and selective no-forecast/no-trade thresholds.
- [ ] Walk-forward event study and paper-only monitoring.

## First success criterion

Given a historical, timestamped earnings or macro event and a point-in-time price/benchmark dataset, the system can reproduce:
1. exactly what was publicly known at the forecast cutoff;
2. the consensus/actual/revision surprise;
3. the event-window asset and abnormal returns;
4. the forecast generated before the outcome;
5. the later scoring result with no future data leakage.

## Boundaries

- No paid data, APIs, compute or subscriptions without explicit approval.
- No live broker connections, order placement or financial execution.
- No API keys in code, logs, Notion or GitHub.
- Do not use current revised macro data or current consensus as historical features.
- Do not call a rule score an AI model or an untrained architecture a prediction engine.
- Respect provider terms, redistribution rights and rate limits.
- A public page is not automatically a licensed historical dataset.
