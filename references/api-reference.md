# Garmin Personal API reference

Protocol reference checked on 2026-10-22 against Garmin's public sources and observed response behavior. These notes describe the API contract, not a provisioned account connection or blanket validation of every endpoint.

## Official sources

- Overview: https://developer.garmin.com/gc-developer-program/overview/
- Personal guide: https://developer.garmin.com/gc-developer-program/personal/personal-api
- Personal FAQ: https://developer.garmin.com/gc-developer-program/personal/personal-faq/
- Swagger documentation: https://developer.garmin.com/gc-developer-program/personal/swagger-docs/
- Account setup: https://connect.garmin.com/app/settings/personalApiToken

The parent Personal page is a JavaScript redirect to the guide. Swagger embeds its OpenAPI document in its page-specific JavaScript bundle. In October 2026 the embedded document reports OpenAPI 3.0.1, title Garmin Connect Personal API, version 1.0.0, and 26 GET paths. Find the current bundle through the public Swagger HTML rather than relying on a versioned asset filename. No sign-in or personal data is needed to inspect these public docs.

## Credential-input limitations

For ChatGPT Web, use a configured Codex Cloud environment with a requested Personal Vault Environment variable or Network secret, or an eligible authenticated MCP plugin, as described in [web-workflow.md](web-workflow.md). The helper consumes the runtime-provided value or protected stdin; these flags are not themselves a secure entry UI. A direct Environment variable puts the raw key in the client process; never print or persist it. Alternatively, a network-secret placeholder passes unchanged into the fixed-origin Authorization header and the default HTTPS proxy handles substitution. The actual Garmin token response still enters process memory. Ordinary chat text, command arguments, assistant terminal-input calls, and source files are not credential intake. Do not substitute local execution or an inaccessible sandbox variable for the Web workflow.

## Authentication and approval boundaries

The guide documents the exact token exchange:

- Method: POST.
- URL: https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token
- Authorization header: `ApiKey ` followed by the Personal API key.
- Accept header: `*/*`, as verified by the authorized test.
- Do not put the key in the URL or request body.

A Personal API key is not itself a resource access token. Garmin's FAQ describes OAuth2 access tokens lasting up to 24 hours, bounded by the key's earlier expiry, without refresh tokens. Generating a new token is a separate credential operation requiring applicable runtime authorization. Key creation may require accepting Garmin's terms and choosing expiry; do not perform it as an incidental step of a data pull.

The exchange can reject `Accept: application/json` with HTTP 406. The verified response for `Accept: */*` is HTTP 200 with `Content-Type: text/plain` and the raw access-token string, not JSON. The helper follows that observed contract: accept only a successful plain-text response, bound its size, validate its bearer-token syntax, and retain it only in process memory. Do not guess JSON field names or print the response. If the contract changes, stop and report the sanitized mismatch rather than trying alternate credential flows.

Use `Authorization: Bearer ` followed by the access token for resource reads. This authentication method has been verified against the documented activity-search endpoint; it is not merely a guessed Swagger scheme. The helper does not establish ongoing credential storage or scheduled access. Standards: https://www.rfc-editor.org/rfc/rfc6750#section-2.1 and https://www.rfc-editor.org/rfc/rfc6749#section-5.1.

The bundled `exchange_api_key` function and `--key-env`/`--key-stdin` options implement this contract. They require explicit runtime authorization, never retry the token-creation POST automatically, reject redirects, and do not save or log keys/tokens. A transport failure can leave token creation uncertain; do not treat it as proof that nothing executed. The bundled exchange implementation is regression-tested with synthetic responses; protocol verification is not evidence that every helper command or newly edited line received live testing.

## Implemented reads

All resources use this exact Swagger server origin: `https://personal.connectapi.garmin.com`.

- Activities: GET `/activitylist-service/activities/search/activities`. Query: `startDate`, `endDate`, `start`, `limit`, `sortOrder`, `excludeChildren`. Dates are inclusive and refer to activity-local start dates. `start` is a zero-based offset. Response is an array of activity summaries. The client uses descending order and excludes child activities. Default page size 50 and at most 10 pages are client safety choices, not claimed Garmin limits.
- Daily summary: GET `/usersummary-service/usersummary/daily` with query `calendarDate`. Returns the daily summary object, which may contain steps, calories, stress, Body Battery, and other available wellness fields.
- Sleep: GET `/sleep-service/sleep/dailySleep` with query `date`. Returns the daily sleep object.
- Heart rate: GET `/wellness-service/wellness/dailyHeartRate` with query `date`. Returns the daily heart-rate object.
- HRV range: GET `/hrv-service/hrv/daily/{fromDate}/{toDate}`. Dates use YYYY-MM-DD. Returns the HRV daily-summary response; HTTP 204 means no data. Endpoint boundary inclusivity was not specified in the reviewed description, so inspect returned dates rather than assuming full coverage.
- Activity detail: GET `/activity-service/activity/{activityId}`. The ID is a positive integer obtained from Garmin; response is the activity summary object.
- Original activity file: GET `/download-service/files/activity/{activityId}`. Documented response type is `application/x-zip-compressed`. Preserve it as ZIP rather than renaming the response directly to FIT.

The client restricts date ranges to at most 31 calendar days, page count to 20, and each response to 20 MiB. These are client bounds, not assertions about Garmin's service quotas. The public sources reviewed did not specify a universal rate limit. Do not claim one.

## Scope exclusions

Do not assume older business API delivery, OAuth onboarding, backfill, or pricing rules apply to this Personal API. Do not use unofficial Garmin login libraries, browser-cookie extraction, undocumented Connect internal endpoints, or direct ChatGPT Health ingestion. Do not fetch menstrual-cycle, pregnancy, food, weight, or other unrelated data just because an API exists.
