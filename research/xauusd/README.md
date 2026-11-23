# Capri Gold Intelligence (XAUUSD)

Status: **research foundation only; model untrained; no trading signal**.

This isolated research module is outside the production Capri runtime. It must
not place orders, connect to a broker, or import credentials.

## Objective

Estimate calibrated DOWN / FLAT / UP probabilities for multiple future
horizons. Default label horizons are 1, 4, 16 and 96 bars. Their meaning depends
on the input timeframe and must be stated in every experiment.

The Discord buy-zone example (3,495–3,470) is a hypothesis to audit, not a
rule to encode. Test whether comparable zones add out-of-sample value after
controlling for volatility, trend, macro regime, event risk and costs.

## Market-driver map

1. **Rates and opportunity cost:** US real yields (e.g. FRED DFII10), nominal
   Treasury yields, inflation compensation and rate-path repricing.
2. **USD and FX:** broad trade-weighted USD proxies and, where licensed, DXY.
   Never silently equate a broad USD index with ICE DXY.
3. **Macro surprises:** CPI, PCE, payrolls, unemployment, wages, ISM and GDP.
   Store release timestamp, reference period, first release, pre-release
   consensus, prior value and later revisions separately.
4. **Risk and liquidity:** equity returns, VIX, Treasury volatility, credit
   stress, oil, funding/liquidity proxies and cross-asset correlations.
5. **Gold demand:** ETF flows/holdings, central-bank purchases, bar/coin and
   jewellery demand. These are structural, low-frequency variables.
6. **Futures and positioning:** COMEX returns, volume, open interest, CFTC COT
   categories and options positioning. Respect publication lags.
7. **Price and execution:** broker-specific XAUUSD OHLC, tick volume, spread,
   session, realized volatility, gaps and rollover conditions.
8. **News:** timestamped headlines and event classifications. Information
   published after a decision timestamp must never enter its features.

## Conditional relationships

Gold is not a one-variable inflation hedge. Higher inflation can support gold
through purchasing-power concerns, but if it reprices real rates upward or
strengthens the USD, those channels can dominate. Geopolitical stress can
increase safe-haven demand, but oil/inflation/rates shocks or forced
liquidations can push gold down simultaneously. Learn interactions and
regimes; do not hard-code slogans.

## Initial neural network

model.py implements a small Transformer temporal encoder with attention
pooling and separate classification heads for each forecast horizon. It is
untrained. labels.py creates volatility-scaled forward-return labels while
using only past volatility to set thresholds.

This is a candidate, not a claim that Transformers outperform simpler models.
Required benchmarks: majority/no-change baseline, regularized logistic
regression, gradient-boosted trees, a small temporal CNN/GRU, then this model.

## Data contract

One row per completed bar, sorted strictly by UTC timestamp, with at least:
timestamp, open, high, low, close, volume or explicitly named tick_volume,
spread in documented broker units, point-in-time macro/cross-asset/event
features, source, instrument, venue/broker, timezone and data-version metadata.

Every feature needs availability-time semantics. A macro value is unavailable
until its actual publication time. Use first-release/vintage data where
possible; revised history must not be backfilled into earlier decisions.
Forward-fill only after publication, never backward-fill. Record missingness.

## Validation rules

- Chronological train / validation / test partitions, never random row splits.
- Purge/embargo at least the maximum forecast horizon around split boundaries.
- Fit scalers, imputers, feature selection and calibration on training data only.
- Keep a final untouched holdout and use rolling walk-forward evaluation.
- Compare against simple baselines and directional persistence.
- Report per-horizon log loss, Brier score, calibration, balanced accuracy,
  precision/recall, confusion matrix, turnover, cost-adjusted returns,
  drawdown and confidence intervals.
- Evaluate by volatility, trend, rate, USD and event regimes.
- Include spread, commission, swaps, slippage, latency, gaps and broker
  contract specifications in execution simulation.
- Do not repeatedly tune on the final holdout. Preserve failed experiments.

## Data sources to investigate

Prefer official/free sources where feasible:
- FRED / ALFRED: yields, real yields, breakevens, broad USD, oil and macro.
  Check frequency, release timing and vintage/revision support.
- CFTC: weekly COT positioning; apply publication lag.
- World Gold Council: ETF holdings/flows, demand, central-bank and market
  structure research; granular historical access may be limited.
- CME / COMEX: futures volume, open interest, contract specifications and
  settlements; distinguish public summaries from paid historical feeds.
- Broker/MT5 export: exact XAUUSD bars and spread for intended venue. Broker
  CFD prices are not a universal consolidated spot tape.
- Official releases: Federal Reserve, BLS, BEA, Treasury and EIA.
- News text requires a timestamped historical archive and licensing review.

Free-data depth, redistribution rights and API limits must be verified. No
paid data or subscription is authorized.

## First experiment

1. Obtain a clean XAUUSD OHLC export and record broker, timeframe, UTC
   conversion, precision, spread and missing-bar policy.
2. Build and evaluate a price-only baseline chronologically.
3. Add real yields and broad USD with point-in-time timestamps.
4. Add event surprises, then positioning and ETF data at true release times.
5. Add news only after obtaining a reliable timestamped archive.
6. Run ablations to test whether each feature family adds out-of-sample value.
7. Calibrate probabilities and define a selective NO-TRADE threshold.

## Installation

Optional dependencies (not part of Capri's zero-dependency runtime):

    python -m pip install -r research/xauusd/requirements.txt

No trained checkpoint is included. This prototype does not support real-money
use.
