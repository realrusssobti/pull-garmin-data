# Garmin Personal API reference

Contract notes checked on 2026-10-22.

## Official sources

- [Personal API guide](https://developer.garmin.com/gc-developer-program/personal/personal-api)
- [Personal API FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/)
- [Swagger documentation](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/)
- [Key settings](https://connect.garmin.com/app/settings/personalApiToken)

Swagger embeds its OpenAPI document in a page-specific JavaScript bundle. Find the current bundle through the Swagger HTML when checking the contract. The reviewed document reports OpenAPI 3.0.1, API version 1.0.0, and 26 GET paths.

## Authentication

Exchange a Personal API key for a resource access token:

- POST `https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`
- Header: `Authorization: ApiKey <key>`
- Header: `Accept: */*`
- Empty body.
- Expected response: HTTP 200, `Content-Type: text/plain`, containing the raw access token.

`Accept: application/json` can produce HTTP 406. The response is a plain string, not a JSON object. Resource reads use `Authorization: Bearer <token>`.

Tokens expire within 24 hours or at the key's earlier expiry. There is no refresh token. Reuse a valid token within the task; the helper's `exchange_api_key(key, approved=True)` performs one exchange without automatic retries. A transport failure may leave the exchange outcome unknown.

The CLI accepts a key or token through stdin or a named environment variable. It requires `--approved-token-use` and, for keys, `--approved-key-exchange`. Set these for the user's requested authenticated operation. See [runtime setup](web-workflow.md) for optional Cloud provisioning.

## Implemented reads

All paths use `https://personal.connectapi.garmin.com`.

| Command | GET path | Parameters and response |
| --- | --- | --- |
| `activities` | `/activitylist-service/activities/search/activities` | `startDate`, `endDate`, `start`, `limit`, `sortOrder`, `excludeChildren`; array of activity summaries |
| `daily` | `/usersummary-service/usersummary/daily` | `calendarDate`; daily summary object |
| `sleep` | `/sleep-service/sleep/dailySleep` | `date`; daily sleep object |
| `heart-rate` | `/wellness-service/wellness/dailyHeartRate` | `date`; daily heart-rate object |
| `hrv` | `/hrv-service/hrv/daily/{fromDate}/{toDate}` | Daily-summary object; HTTP 204 means no data |
| `activity` | `/activity-service/activity/{activityId}` | Activity detail object |
| `activity-file` | `/download-service/files/activity/{activityId}` | Original activity ZIP archive |

Activity search dates are inclusive activity-local start dates. Pagination uses a zero-based `start` offset. The client requests descending order and excludes multisport child activities. It defaults to 50 records per page and at most 10 pages; a short page establishes completion.

Daily summaries may contain steps, calories, stress, Body Battery, and other wellness fields. Availability varies by date and device. HRV range boundary inclusivity was not specified in the reviewed description; inspect returned dates for coverage.

The original-file response is documented as `application/x-zip-compressed`. Preserve the ZIP archive rather than labeling it as FIT.

## Client limits and errors

- Range requests: 1–31 calendar days.
- Activity pagination: page size 1–99, at most 20 pages.
- Response size: at most 20 MiB per request.
- Duplicate or invalid activity IDs, invalid supplied local dates, and out-of-range supplied local dates fail collection.
- Missing local dates are counted in metadata.
- Redirects, 401/403 responses, unexpected content types, and schema mismatches stop the request.
- Selected transient GET server failures receive at most two retries. Rate-limit responses report `Retry-After` when supplied.

These are client bounds, not Garmin service quotas. Add endpoints from the official Personal API contract and extend the client's path allowlist and tests.
