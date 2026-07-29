# Compliance and safe execution

## Contents

- Open versus free-to-read
- Institution access
- Automation stops
- Data handling
- Google Scholar

## Open versus free-to-read

Separate these concepts:

- `open-access`: an identified OA location, ideally with a recorded license.
- `free-to-read`: currently readable without payment, but reuse rights may be unclear.
- `authorized-subscription`: accessible through the user's institution.
- `unknown`: access or license cannot be established.

Do not upgrade `free-to-read`, `authorized-subscription`, or `unknown` to `open-access`.

## Institution access

Require the user to authenticate in a visible local browser. Never request credentials or copy cookies into project files. Use publisher-native download controls and conservative frequency. A subscription permits normal scholarly use but may prohibit automated bulk retrieval.

## Automation stops

Stop a provider route on:

- HTTP 403 or repeated 401;
- HTTP 429 or an explicit rate-limit warning;
- CAPTCHA or bot-detection interstitial;
- account or IP warning;
- terms that explicitly prohibit the intended automation;
- a response that differs from the expected PDF workflow.

Record the status and continue only with a separate legal source.

## Data handling

- Store no passwords, cookies, API tokens or session exports.
- Keep API keys in environment variables.
- Refuse private, loopback and link-local URLs by default.
- Limit record count, file size, request duration and request rate.
- Preserve source, resolved URL, provider, license, version and SHA-256.
- Do not commit downloaded papers to this repository.

## Google Scholar

Google Scholar states that it does not provide bulk access and asks automated clients to respect its `robots.txt`. Use it for interactive discovery, citation export and “all versions” inspection only. Do not implement a crawler, CAPTCHA solver or automated pagination loop.

Official help: <https://scholar.google.com/intl/us/scholar/help.html>
