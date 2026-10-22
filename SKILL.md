---
name: pull-garmin-data
description: Retrieve Garmin Connect activities, daily summaries, sleep, heart rate, HRV, and original activity files through the official Personal API. Generate portable HTML health and training reports with the bundled Python generator. Use for Garmin data pulls, recovery summaries, and training comparisons.
---

# Pull Garmin Data

## Health and training reports

Use `scripts/garmin_report.py` for a standard HTML report. Run the bundled generator directly; it owns calculations, narrative, charts, and layout. No frontend rebuild or separate reporting plugin is needed. Resolve paths relative to this installed skill.

```sh
python3 scripts/garmin_report.py \
  --days 14 --timezone America/Los_Angeles \
  --output "$HOME/GarminReports/report-$(date +%Y%m%d-%H%M%S).html"
```

Use the user's time zone from context; otherwise the command defaults to system local time. “Last 14 days” means the last 14 completed calendar days, ending yesterday. `--end-date YYYY-MM-DD` selects another inclusive endpoint. Supported windows are even numbers from 2 to 30 days, split into equal periods.

The generator uses `GARMIN_ACCESS_TOKEN` when present, otherwise `GARMIN_API_KEY`. It exchanges a key once and reuses the token across all requested reads. Named environment variables and stdin are supported through `--key-env`, `--token-env`, `--key-stdin`, and `--token-stdin`.

A user may supply a credential through chat, an existing environment variable, stdin, or their chosen local/cloud store. Use the supplied access for the requested operation. If the user asks to persist a key, store it under `GARMIN_API_KEY` in their chosen runtime configuration. Ask for missing setup only when the available credential or connection cannot support the task. See [runtime setup](references/web-workflow.md) when needed.

Choose a fresh HTML output path outside source-control repositories. The command creates a private parent directory if absent; existing output directories must have mode `0700`. Return a clickable link to the HTML and a concise summary of its main findings. Report any material data gaps visible in the artifact.

Additional modes:

- `--save-json /absolute/path/bundle.json` saves the raw pull for reuse.
- `--from-json /absolute/path/bundle.json --output /absolute/path/report.html` renders a saved raw bundle without API calls. Dates and time zone come from the bundle.
- `--demo --output /absolute/path/demo.html` renders wholly synthetic data without credentials.

The report embeds only fields used in the analysis; raw bundles contain the full fetched responses. Keep personal outputs separate from the skill. See [report methodology](references/report-methodology.md) for calculation definitions, missing-data rules, and the bundle format. Custom requests can extend this output, but standard reports should use the packaged implementation.

## Other Garmin requests

For individual resource reads, use `scripts/garmin_pull.py` or a connected Garmin plugin that supports the requested resource. Read [API reference](references/api-reference.md) for endpoints and command syntax.

```sh
python3 scripts/garmin_pull.py \
  --key-env GARMIN_API_KEY --approved-key-exchange --approved-token-use \
  --metadata-only activities \
  --start-date 2025-03-03 --end-date 2025-03-16
```

Set the client's acknowledgement flags for the user's requested authenticated operation. A full page can be incomplete; use pagination metadata before claiming a complete activity history. An authentication failure stops the pull; token exchange is not automatically retried. Keep requests within the user's date and resource scope.

## Development

Python 3.9+ with standard-library dependencies only. After changes, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

Use synthetic fixtures. Check new endpoints against Garmin's official contract before adding them to the client.
