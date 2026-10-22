---
name: pull-garmin-data
description: Pull the user's own Garmin Connect activity and health data through the official Personal API. Use for Garmin workouts, daily summaries, sleep, heart rate, HRV, and original activity files. Includes a bounded read-only Python client with authorized in-memory API-key exchange or an existing securely supplied OAuth bearer token. Require applicable runtime credential authorization; do not confuse installation with a live connection or ChatGPT Health integration.
---

# Pull Garmin Data

Retrieve only the user's requested Garmin data, on demand. Use the official Personal API, not Garmin Connect scraping or unofficial login libraries.

## Check credential intake before promising a connection

Treat this skill as reusable code and instructions, not a connector, secure entry form, credential vault, OAuth sign-in screen, or persistent account session. A successful test in one conversation does not provision credentials in another conversation or execution environment.

Before giving credential setup instructions, verify an actual supported route in the current environment:

- Use an already-connected eligible Garmin plugin if its own authorization flow and requested read are available.
- Use a key/token already provisioned into the selected runtime through a user-authorized secret mechanism, without exposing it in chat, tool arguments, command history, or logs. The environment-variable and stdin options below consume such input; they do not create a secure intake channel.
- A user-run local terminal program can obtain a secret directly from the user with a hidden-input function and call this helper in the same process. Offer local execution only when requested and the user has the script and a real terminal. Hidden terminal echo alone does not make assistant tool-input logging safe.

If none of these routes exists, state the blocker plainly: “The Garmin skill is installed, but this chat has no supported secure way to receive your Garmin credential. It is not signed in here.” Offer only a verified available connector/setup route, or a user-run local workflow if desired. Do not invent a secure field, ask for a key in chat, send it through an assistant's terminal-input tool, paste it into tool arguments, hardcode it, save it in the skill, or repurpose unrelated hosting configuration as a credential vault. Do not claim a browser login automatically provides API access.

## Establish scope and access

1. Resolve data categories, date range, and time zone from the conversation. Ask only when missing details materially change the pull. Do not collect unrelated metrics or full history by default.
2. Read [api-reference.md](references/api-reference.md) for verified official endpoints, supported commands, date semantics, and authentication limitations. Recheck official documentation if Garmin changes its contract.
3. Prefer an eligible connected Garmin plugin when it supports the task. Otherwise use the bundled client with an existing access token, or separately authorize an in-memory Personal API key exchange, using an approved runtime secret mechanism.
4. Obtain applicable user authorization before transmitting credentials, generating tokens, or configuring persistent access. Creating or invoking this skill does not grant that authority. Never ask the user to paste a key, token, or password in chat.
5. Keep Personal API keys distinct from resource access tokens. If a key is supplied, obtain applicable approval for sending it to Garmin and creating an access token before invoking the exchange option. The helper makes one fixed-origin POST, accepts the observed plain-text token response, and then performs only the requested GET reads. Never display or save a credential or the exchange response. Do not automatically retry an exchange with an uncertain outcome.

## Use the read-only client

Run `scripts/garmin_pull.py` with Python 3.9 or newer and standard-library dependencies only. Set the path relative to this installed skill. It accepts existing OAuth bearer tokens or Personal API keys from protected stdin or a named environment variable, never as an argument value. Key and token inputs are mutually exclusive. Do not place a credential literal in a shell command or enable shell tracing. The environment option removes the variable from the child process after reading, not from its parent or external secret store.

The examples below are execution examples, not credential-onboarding instructions. Use them only after verifying that the named secret is already safely provisioned in the actual runtime and applicable approval is in place. A minimal bounded test with an existing access token is:

```bash
python3 scripts/garmin_pull.py --token-env GARMIN_ACCESS_TOKEN --approved-token-use --metadata-only activities --start-date 2020-01-01 --end-date 2020-01-01 --page-size 1 --max-pages 1
```

These example dates are synthetic. Replace them with the user's requested period. The approval flag is an execution guard, not a substitute for actual approval. `--token-stdin` is an alternative only when an approved mechanism can supply the token without exposing it in commands or tool output.

If the user instead authorizes a Personal API key exchange and the subsequent token use, use an already-provisioned secret environment variable:

```bash
python3 scripts/garmin_pull.py --key-env GARMIN_PERSONAL_API_KEY --approved-key-exchange --approved-token-use --metadata-only activities --start-date 2020-01-01 --end-date 2020-01-01 --page-size 1 --max-pages 1
```

Use `--key-stdin` only with protected input. The helper does not create a Personal API key, accept terms, store credentials, refresh tokens, or establish a standing connection. Each invocation using a key creates a new access token, so prefer an existing valid token within its authorized scope. Both approval flags require actual applicable approval; neither grants it.

For an approved in-process workflow, import the module with bytecode writing disabled, call `exchange_api_key(key, approved=True)` only when exchange is authorized, then `Client(token)` and `collect(client, args)`. Keep returned records private and print only the selected non-sensitive metadata. Catch unexpected exceptions without printing their values or a traceback. Releasing Python references does not guarantee secure memory erasure.

For a requested data file, replace `--metadata-only` with `--output /absolute/private-directory/result.json`. Choose a fresh file outside the skill and any source-control repository. The parent directory must be user-owned and private (0700); the client can create its immediate parent. Files are created exclusively with 0600 permissions and are never overwritten. Use a `.zip` filename for `activity-file`; preserve the original archive and inspect it safely before extracting.

Use these commands:

- `activities --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--page-size 1..99] [--max-pages 1..20]`
- `daily --date YYYY-MM-DD`
- `sleep --date YYYY-MM-DD`
- `heart-rate --date YYYY-MM-DD`
- `hrv --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
- `activity --activity-id ID`
- `activity-file --activity-id ID`

Use an activity ID returned by Garmin, never an invented ID. Date ranges are limited to 31 days per invocation. Request larger histories in explicitly scoped chunks. Activity search excludes child legs of multisport activities by default; use activity detail or extend the documented filter support when the task requires those legs.

## Interpret results and failures

- Read the returned metadata: status, resource, page count, record count when known, completeness, no-content status, persistence, and activity-local date verification. Disclose records with missing local dates; pagination completeness does not prove date coverage. Metadata-only still performs the requested read but does not write or print its raw data.
- Treat `complete: false` as a truncated activity result, not a successful full-history pull. The last full page cannot establish completeness. Increase the authorized page bound or narrow the requested dates. Pagination is not a transactional snapshot; duplicate/non-positive/non-integer IDs and supplied local dates outside the requested range cause a stop rather than a misleading merged result.
- Treat empty and unavailable values as missing, not zero. A single successful health response does not prove that every requested metric or every day is populated. Preserve Garmin's units and timestamps, including activity-local dates.
- Stop on 401/403, redirects, schema mismatch, or unexpected response types. Do not switch to scraping, extract browser cookies, or broaden access. On 429, respect Retry-After and recheck when appropriate. The client performs at most two bounded retries for selected transient server errors and never retries authentication failures.
- Keep raw health records, activity files, keys, and tokens outside the skill, repositories, logs, and unnecessary summaries. Do not send data to another service, enable background collection, or schedule recurring pulls as a side effect.

## Deliver and verify honestly

State the actual categories and dates retrieved, known record counts, omissions, incomplete pages, and sync freshness only when supplied. Attribute Garmin as the source and identify the device only when present. Deliver requested files privately; expose only relevant health details. Do not present wellness observations as diagnoses.

Distinguish installed, mock-tested, authenticated, and successfully retrieved. The plain-text exchange and bearer activity-read protocol have been verified, while the bundled helper is regression-tested with synthetic responses. This does not establish ongoing access, persistent credentials, or success for every resource or metric. Installation alone does not connect an account. This skill is separate from ChatGPT Health and does not ingest data into it.

Run offline tests after client changes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

Use only synthetic fixtures. Add endpoints only after checking the official Personal API contract and extending the exact-path allowlist and tests. A new authenticated live test requires applicable authorization even when mock tests pass.
