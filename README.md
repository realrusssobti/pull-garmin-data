# Pull Garmin Data

**Your last two weeks of health and training, in one portable HTML report.**

Fetch your Garmin Connect data and turn it into period comparisons, daily charts, a searchable activity log, and a plain-language summary. The same command works as a skill or directly in a terminal.

Python 3.9+ · standard library only · works locally or in a cloud runtime · offline HTML

## Try the report

No account or credentials needed for the synthetic demo:

```sh
git clone https://github.com/realrusssobti/pull-garmin-data.git
cd pull-garmin-data
python3 scripts/garmin_report.py --demo --output "$HOME/GarminReports/demo.html"
```

Open the generated HTML in a browser. It contains all its styles, SVG charts, and controls. There are no external scripts, fonts, or analytics. Print to PDF, download the normalized report data, or export the activity log as CSV.

## Generate your report

Create a key in Garmin Connect’s [Personal API settings](https://connect.garmin.com/app/settings/personalApiToken), then make it available as `GARMIN_API_KEY` in your runtime. You can also supply an existing token as `GARMIN_ACCESS_TOKEN`. See [credential and runtime setup](references/web-workflow.md) for local, cloud, and connected-service options.

```sh
python3 scripts/garmin_report.py \
  --days 14 \
  --timezone America/Los_Angeles \
  --output "$HOME/GarminReports/report-$(date +%Y%m%d-%H%M%S).html"
```

By default, the window ends **yesterday in the selected time zone**, keeping today’s partial readings out of the comparison. Without `--timezone`, the command uses the computer’s local zone. Choose any even window from 2 to 30 days; the report compares equal halves.

The generator exchanges a key once and reuses the resulting token for all reads. It fetches activity summaries, daily summaries, sleep, HRV, and heart rate. It creates a private output directory when needed and writes new files without overwriting existing reports. Use an output directory outside a Git repository; an existing directory must be owned by you with mode `0700`.

### Save a pull and render it again

```sh
python3 scripts/garmin_report.py \
  --end-date 2025-03-16 --days 14 --timezone America/Los_Angeles \
  --output "$HOME/GarminReports/march.html" \
  --save-json "$HOME/GarminReports/march-bundle.json"

python3 scripts/garmin_report.py \
  --from-json "$HOME/GarminReports/march-bundle.json" \
  --output "$HOME/GarminReports/march-rerendered.html"
```

`--from-json` uses the raw bundle produced by `--save-json` and makes no API calls. The report’s **Download report data** button exports a smaller, normalized dataset for analysis; it is a different format from that raw bundle.

Authentication overrides: `--key-env NAME`, `--token-env NAME`, `--key-stdin`, or `--token-stdin`. Existing tokens take precedence when both default environment variables are present; `--key-env GARMIN_API_KEY` explicitly selects the key.

## Use as a skill

Ask your skill-capable agent:

> Install the skill from https://github.com/realrusssobti/pull-garmin-data

Then:

> $pull-garmin-data render an HTML report of my last 14 days of Garmin data, summarizing my health and training progression.

The skill runs the bundled generator. Dates, calculations, narrative, charts, and layout are deterministic; generating a report requires no model API, Node installation, build step, or other reporting plugin. A local installation can also be made by cloning this repository to `~/.codex/skills/pull-garmin-data`.

## What the report covers

- **Training:** session count, active days, exercise time, exercise-load sum, activity mix, and outdoor running distance and pace.
- **Recovery:** sleep duration and score, resting heart rate, overnight HRV, Body Battery, daily stress, and steps.
- **Progression:** equal-period comparisons, daily trends, and suggestions based on the available readings.
- **Coverage:** missing readings, incomplete activity searches, and questionable running distances are visible. Missing data never becomes a fabricated zero.

The report distinguishes recorded workload from Garmin’s weighted acute load and longer-term training status. It describes running pace in context and does not infer strength or climbing gains from session duration. Definitions and data handling are in [report methodology](references/report-methodology.md).

## Individual data exports

The underlying client also retrieves activity detail and original activity ZIP files:

```sh
python3 scripts/garmin_pull.py \
  --key-env GARMIN_API_KEY --approved-key-exchange --approved-token-use \
  --metadata-only activities \
  --start-date 2025-03-03 --end-date 2025-03-16
```

See the [API reference](references/api-reference.md) for endpoints, date semantics, pagination, and export commands. The client uses Garmin’s official Personal API. It does not require account scraping or a browser session.

## Development

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

All fixtures are synthetic. Tests cover authentication and pagination, date boundaries, missing metrics, incomplete searches, aggregate calculations, report escaping, and offline rendering. CI runs the same suite on Python 3.9 and 3.13. The HTML template lives in `assets/report.html`; calculations and narrative live in `scripts/garmin_report.py`.
