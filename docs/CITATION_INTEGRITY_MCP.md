# Scholar Sidekick citation-integrity integration

**Status:** plugin source updated; ChatGPT-side MCP handshake and tool execution not yet verified.

## Added to Capri Engineering Lab v0.4.0

- Private plugin: https://chatgpt.com/plugins/plugins_6aef721e946c81918014a2c04ff4476f
- Plugin ID: plugins_6aef721e946c81918014a2c04ff4476f
- Release ID: pluginrel_6aef770eadc48191a82b293aefce6c4a
- Added skill: citation-integrity
- Added Streamable HTTP MCP endpoint: https://scholar-sidekick.com/api/mcp
- No API key, paid tier, or RapidAPI configuration is included.

## Capability

The upstream project documents seven read-only tools:
1. verifyCitation — compare a claimed citation title with the record resolved from its identifier.
2. auditBibliography — audit up to 25 public references from BibTeX, RIS, CSL-JSON, or structured claims; citation identity and retraction checks.
3. checkRetraction — check for retraction, correction, or expression of concern.
4. checkOpenAccess — find a legal open-access location and associated license/version.
5. resolveIdentifier — resolve DOI, PMID, PMCID, ISBN, arXiv, ISSN, ADS bibcode, or WHO IRIS identifiers.
6. formatCitation — format references using APA, IEEE, Vancouver, AMA, CSE, or CSL styles.
7. exportCitation — export to common bibliography formats.

Sources: [upstream repository](https://github.com/mlava/scholar-sidekick-mcp), [security policy](https://github.com/mlava/scholar-sidekick-mcp/blob/main/SECURITY.md), [tool contract](https://github.com/mlava/scholar-sidekick-mcp/blob/main/tools.json), [hosted MCP guide](https://scholar-sidekick.com/mcp), [engineering principles](https://scholar-sidekick.com/engineering-principles).

## Due diligence

- Upstream package declares MIT; v0.8.13 was the release surfaced during this review.
- Security policy describes all seven tools as read-only, using HTTPS to the configured API host; inputs are identifiers and citation metadata, not arbitrary URLs. No shell execution or local file writes are part of the server.
- Anonymous access is documented on a rate-limited free tier. Optional first-party keys raise limits; paid RapidAPI access exists but is not configured or required.
- Operator documentation states raw citation inputs are not retained as application data; requests may be resolved through upstream services such as Crossref and PubMed.
- Third-party data processing remains a privacy boundary. Send only public bibliographic metadata; never send confidential manuscripts, unpublished/private bibliographies, patient data, personal data, credentials, or private research records.
- The MCP endpoint is documented as Streamable HTTP. Independent service directories report successful unauthenticated initialize probes, but Capri has not yet verified a current ChatGPT-host handshake or tool call.

## Interpretation safeguards

- A matched result confirms identifier-to-record identity, not whether the paper supports the sentence citing it.
- mismatch is a discrepancy requiring human review, not automatic proof of fraud.
- ambiguous requires inspecting both candidate records.
- not_found does not prove non-existence.
- auditBibliography does not assess scientific methods, results, or claim support. Parse errors and truncated items are unchecked.
- Retraction counts are a separate axis from citation-verdict totals; a matched paper may still be retracted.
- Optional LLM screening is intentionally not enabled; it requires authentication. The default workflow remains anonymous and read-only.

## Next verification

1. Refresh/install the updated private plugin in ChatGPT.
2. Confirm the scholar-sidekick MCP server appears and completes initialize/tools-list.
3. Run one harmless public DOI format/resolve test.
4. Run one harmless known citation verification and inspect the complete structured output.
5. Confirm no API key or paid service is requested.
6. Record actual runtime status separately from static plugin configuration.