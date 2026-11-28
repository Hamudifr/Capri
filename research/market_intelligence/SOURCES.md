# Market Intelligence Source Register

Last reviewed: 2026-11-28.

This is a discovery and due-diligence register, not a declaration that all sources have been integrated or that every API is free for every use. No provider has been called from this research module and no data has been licensed, purchased or bulk-downloaded.

## Primary and official sources

| Source | Best use | Access and limits to preserve |
| --- | --- | --- |
| SEC EDGAR | US issuer filings, 8-K events, 10-Q/10-K, company submissions and XBRL facts | Public access; follow SEC fair-access rules and identify the client with a User-Agent. Filing facts are as reported and may be restated later. Preserve accession number, filed timestamp, period and form. |
| Company investor relations | Earnings releases, guidance, presentations, event calendars and transcripts | Primary for issuer statements. Preserve page/PDF URL and publication/update timestamp. Confirm the announcement against the SEC filing when applicable. |
| BLS | CPI, PPI, employment, wages and labor-market releases | Official releases and public time series. Store reference period separately from release timestamp; distinguish first print from later revisions. |
| BEA | GDP, PCE, income, consumption and national accounts | Official release tables and API. API access may require a key; use public release pages unless an authorized no-cost access route is confirmed. |
| FRED / ALFRED | Macro and financial series plus historical data vintages | FRED API requires an API key; public pages/downloads may be usable without one. ALFRED vintages are essential for point-in-time backtests. Store series ID, units, frequency, observation date and real-time/vintage dates. |
| Federal Reserve | FOMC statements, minutes, projections, speeches, H.15 and monetary-policy material | Primary policy source. Record exact release timestamp and distinguish statement, minutes, projections and later speeches. |
| ECB Data Portal | Euro-area rates, yields, HICP, exchange rates and monetary statistics | Public SDMX data access. Preserve dataflow/key, frequency, units and revision/vintage semantics. |
| Eurostat / Destatis | European inflation, GDP, employment and sector statistics | Official national/statistical releases. Store publication timestamp, reference period, seasonal adjustment and revision status. |
| CFTC | Commitments of Traders positioning | Public weekly reports, not real-time. Position snapshot is Tuesday; publication generally follows Friday. Never use a report before its publication time. |
| US Treasury | Treasury yields, auctions, debt and fiscal data | Official releases and datasets. Distinguish auction announcement, result, settlement and daily yield observations. |
| CME Group / exchange sources | Futures specifications, settlements, volume/open interest, FedWatch expectations | Public tools may be delayed or limited. Confirm contract, expiry, timezone, session and whether the field is real-time, delayed or end-of-day. |
| FINRA | US short-interest and short-sale datasets | Different datasets and reporting schedules. Short-sale volume is not short interest. Preserve the reporting period and publication date. |

## News and estimates

| Source type | Use | Main risk |
| --- | --- | --- |
| Issuer press releases and filings | Confirmed corporate facts | Promotional framing; compare claims with reported financials and prior guidance. |
| Wire services and established financial press | Discovery, context, independent reporting | Syndication creates duplicates; distinguish original reporting from copies. Paywalls and archive licensing restrict historical collection. |
| Analyst consensus / target revisions | Market expectations and changes in the Street view | Coverage is incomplete; consensus providers differ; estimates can be revised after events. Preserve the exact snapshot timestamp, contributing analysts and methodology. |
| Earnings-call transcripts | Management guidance, Q&A and analyst concerns | Transcript providers can have delays or transcription errors; verify material quotations against audio or issuer material where feasible. |
| Options and derivatives data | Implied move, skew and positioning | Prints do not reveal full multi-leg strategy or opening/closing intent. Open interest updates with a lag. Unusual flow is not a directional forecast by itself. |
| Investor/social discussion | Early discovery and narrative/sentiment hypotheses | Not authoritative; bots, selection bias, coordinated activity and survivorship are material. Never promote an unverified claim to fact. |

## Providers not approved for automatic use

Commercial or freemium aggregators such as Benzinga, Fiscal.ai, EODHD, Finnhub, Twelve Data, Marketstack and similar services may offer useful structured data, but plan terms, request costs, rate limits, historical depth and redistribution rights must be checked before use. A connector being installed or a capability appearing in a catalogue does not establish zero cost.

Do not trigger billable provider reads, paid API calls, subscription trials, or large research batches without explicit cost verification and authorization. Prefer official public data and user-supplied broker/chart exports for the initial prototype.

## Minimum provenance fields

Every ingested observation should retain:

- provider and exact endpoint/dataset identifier
- source URL and original record identifier
- instrument identifier, exchange/venue and currency
- source publication timestamp and timezone
- effective/reference period
- version/correction availability timestamp
- collector observation timestamp
- units, scale, frequency and adjustment method
- licensing/access classification and known delay
- raw payload hash or immutable source snapshot reference
- transformation code/version and retrieval date

## Known gaps

1. A free, licensed, point-in-time global equity price and corporate-action feed has not been selected.
2. Historical consensus estimates and analyst revisions are not yet sourced.
3. A timestamped historical news archive with clear backtest and redistribution rights has not been selected.
4. Options history and institutional positioning are incomplete and may be delayed or commercial.
5. European issuer and regulator coverage needs a country/exchange-specific mapping.
