# Security Policy

## Supported code

Security fixes are made against the latest code on the `main` branch. No release support window is currently promised.

## Reporting a vulnerability

Please do not publish exploitable details in a public issue, discussion, pull request, or commit.

Use GitHub's private vulnerability reporting feature for this repository if it is enabled. If it is unavailable, contact the repository owner privately through GitHub and request a secure reporting channel.

A useful report includes:

- The affected commit or component.
- The security boundary or asset affected.
- A concise reproduction and realistic impact.
- Any safe mitigation or workaround already identified.

Do not include real user data, access tokens, passwords, private Notion content, or third-party credentials. Do not test against systems or accounts you do not own or have permission to assess.

There is currently no published bug-bounty program or guaranteed response-time commitment.

## High-value security boundaries

Please pay particular attention to:

- Host credential resolution and principal ownership of sessions and tasks.
- Permission checks, approvals, and trusted tool-handler registration.
- Task retries, cancellation, lease expiry, and uncertain external side effects.
- SQLite ownership tables, backup publication, restore validation, and filesystem path handling.
- Memory and knowledge-graph retrieval, including prompt-injection attempts in retrieved records.
- CI permissions, workflow dependencies, repository secrets, and release artifacts.
