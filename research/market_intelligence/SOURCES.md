# Market Intelligence Source Register

Last reviewed: 2026-11-28.

This is a discovery and due-diligence register, not a declaration that all sources have been integrated or that every API is free for every use. No provider has been called from this research module and no data has been licensed, purchased or bulk-downloaded.

## Primary and official sources

| Source | Best use | Access and limits to preserve |
| --- | --- | --- |
| SEC EDGAR | US issuer filings, 8-K events, 10-Q/10-K, company submissions and XBRL facts | Public submissions/XBRL APIs on data.sec.gov do not require API keys. SEC fair-access policy limits clients to 10 requests/second across the caller's machines; identify the client and fetch only required records. Filing facts may be restated later. Preserve accession number, filed timestamp, period and form. |
| Company investor relations | Earnings releases, guidance, presentations, event calendars and transcripts | Primary for issuer statements. Preserve page/PDF URL and publication/update timestamp. Confirm the announcement against the SEC filing when applicable. |
| BLS | CPI, PPI, employment, wages and labor-market releases | Public API v1 is unregistered and limited to 25 queries/day, 25 series/query and 10 years/query. API v2 requires registration and provides higher limits. Start with v1 and official release pages. Store reference period separately from release timestamp; distinguish first print from later revisions. |
| BEA | GDP, PCE, income, consumption and national accounts | Official release tables and API. API access requires a registered 36-character UserID. Use public release pages unless an authorized key is supplied through an approved secret mechanism. |
| FRED / ALFRED | Macro and financial series plus historical data vintages | Every FRED API request requires a registered API key. Public pages/downloads may be usable without one, but automated API access is not keyless. ALFRED vintages are essential for point-in-time backtests. Store series ID, units, frequency, observation date and real-time/vintage dates. |
| Federal Reserve | FOMC statements, minutes, projections, speeches, H.15 and monetary-policy material | Primary policy source. Record exact release timestamp and distinguish statement, minutes, projections and later speeches. |
| ECB Data Portal | Euro-area rates, yields, HICP, exchange rates and monetary statistics | Public SDMX data access. Preserve dataflow/key, frequency, units and revision/vintage semantics. |
| Eurostat / Destatis | European inflation, GDP, employment and sector statistics | Official national/statistical releases. Store publication timestamp, reference period, seasonal adjustment and revision status. |
| CFTC | Commitments of Traders positioning | The currently posted schedule still shows the traditional weekly Friday release based on Tuesday positions. An Oct 27, 2026 CFTC announcement says a move to twice-weekly Monday/Wednesday position snapshots published Wednesday/Friday is planned by end-2026. Treat this as a planned transition, not proof it is live: inspect the actual release schedule and each report's as-of/published timestamps. |
| US Treasury | Treasury yields, auctions, debt and fiscal data | Official releases and datasets. Distinguish auction announcement, result, settlement and daily yield observations. |
| CME Group / exchange sources | Futures specifications, settlements, volume/open interest, FedWatch expectations | Public tools may be delayed or limited. Confirm contract, expiry, timezone, session and whether the field is real-time, delayed or end-of-day. |
| FINRA | US short-interest and short-sale datasets | Different datasets and reporting schedules. Short-sale volume is not short interest. Preserve the reporting period and publication date. |

## API and publication controls

- SEC: [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and [fair-access rules](https://www.sec.gov/about/developer-resources). No API key for submissions/XBRL; request-rate ceiling is 10 requests/second.
- BLS: [API getting started](https://www.bls.gov/developers/) and [API FAQ](https://www.bls.gov/developers/api_faqs.htm). Unregistered v1 has lower quotas; registered v2 requires a registration key.
- FRED/ALFRED: [API overview](https://fred.stlouisfed.org/docs/api/fred/) and [real-time/vintage periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html). API key required for every API request. Historical values must be queried at the vintage available on the forecast date.
- BEA: [API guide](https://apps.bea.gov/API/docs/) requires a registered 36-character UserID. Do not register or collect account details as part of this task; use public release pages unless an authorized key is supplied through an approved secret mechanism.
- ECB: [SDMX web service](https://data.ecb.europa.eu/help/api/overview) supports public programmatic data retrieval and discovery. Preserve dataflow, dimensions, units and revision semantics.
- CFTC: [current release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm), [COT report description](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm), and [Oct 27, 2026 transition announcement](https://www.cftc.gov/PressRoom/PressReleases/9316-26). Confirm actual operational cadence from the current schedule and each report.

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
