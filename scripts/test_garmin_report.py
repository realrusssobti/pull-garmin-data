"""Report regressions using invented records only; no Garmin account required."""

import contextlib
import datetime as dt
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_report as report
from demo_data import demo_bundle


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.bundle = demo_bundle()

    def normalized(self):
        return report.normalize(self.bundle)

    def test_equal_periods_and_independent_totals(self):
        result = self.normalized()
        self.assertEqual([p["sessions"] for p in result["periods"]], [5, 5])
        self.assertEqual([p["activityMinutes"] for p in result["periods"]], [175, 190])
        self.assertEqual([p["exerciseLoad"] for p in result["periods"]], [226, 296])
        self.assertAlmostEqual(result["periods"][0]["sleepHours"], 48.6 / 7)
        self.assertEqual(result["coverage"]["hrvMs"], 14)
        self.assertFalse(result["warnings"])

    def test_no_workouts_is_zero_when_search_complete(self):
        self.bundle["resources"]["activities"][0]["data"] = []
        result = self.normalized()
        self.assertEqual(result["periods"][0]["activityMinutes"], 0)
        self.assertEqual(result["daily"][0]["activityCount"], 0)
        self.assertIsNone(result["periods"][0]["paceMinKm"])
        self.assertNotIn("nan", report.render(result).lower())

    def test_partial_search_never_creates_rest_days_or_totals(self):
        self.bundle["resources"]["activities"][0]["metadata"]["complete"] = False
        result = self.normalized()
        self.assertIsNone(result["daily"][2]["activityCount"])
        self.assertIsNone(result["periods"][0]["activityMinutes"])
        self.assertIn("incomplete", report.narrative(result)["training"])
        self.assertEqual(len(result["activities"]), 10)

    def test_undated_activity_retained_but_disables_totals(self):
        del self.bundle["resources"]["activities"][0]["data"][0]["startTimeLocal"]
        result = self.normalized()
        self.assertEqual(len(result["activities"]), 10)
        self.assertFalse(result["activityComplete"])
        self.assertIn("Undated", report.render(result))

    def test_missing_daily_metrics_do_not_become_zero(self):
        self.bundle["resources"]["daily"][0]["data"] = None
        self.bundle["resources"]["sleep"][0]["data"] = None
        self.bundle["resources"]["heart-rate"][0]["data"] = None
        result = self.normalized()
        self.assertIsNone(result["daily"][0]["steps"])
        self.assertIsNone(result["daily"][0]["sleepHours"])
        self.assertEqual(result["coverage"]["sleepHours"], 13)
        self.assertNotIn(
            "Resting heart rate changed", report.narrative(result)["recovery"]
        )
        self.assertIn("(6/7 days)", report.render(result))
        self.assertIn("Incomplete coverage", report.render(result))

    def test_rhr_fallback_and_conflict(self):
        del self.bundle["resources"]["daily"][0]["data"]["restingHeartRate"]
        self.bundle["resources"]["heart-rate"][1]["data"]["restingHeartRate"] = 99
        result = self.normalized()
        self.assertEqual(result["daily"][0]["restingHeartRate"], 54)
        self.assertEqual(result["daily"][1]["restingHeartRate"], 53)
        self.assertTrue(any("differs" in w for w in result["warnings"]))

    def test_hrv_uses_nightly_values_not_rolling_weekly_values(self):
        for item in self.bundle["resources"]["hrv"][0]["data"]["hrvSummaries"]:
            item["weeklyAvg"] = 999
            item["baseline"] = None
            item["status"] = "NONE"
        result = self.normalized()
        self.assertEqual(result["periods"][0]["hrvMs"], 51)
        self.assertIn("No personal HRV baseline", report.narrative(result)["recovery"])

    def test_missing_load_or_duration_makes_aggregate_unknown(self):
        first = self.bundle["resources"]["activities"][0]["data"][0]
        del first["activityTrainingLoad"]
        del first["duration"]
        result = self.normalized()
        self.assertIsNone(result["periods"][0]["exerciseLoad"])
        self.assertIsNone(result["periods"][0]["activityMinutes"])
        self.assertNotIn(
            "Summed exercise load changed", report.narrative(result)["training"]
        )

    def test_distance_flag_does_not_discard_duration(self):
        self.bundle["resources"]["activities"][0]["data"][0]["distance"] = 20
        result = self.normalized()
        self.assertTrue(result["activities"][0]["distanceFlagged"])
        self.assertIsNone(result["activities"][0]["paceMinKm"])
        self.assertEqual(result["periods"][0]["activityMinutes"], 175)
        self.assertAlmostEqual(result["periods"][0]["runningKm"], (45 + 35) / 6)

    def test_treadmill_excluded_from_outdoor_pace(self):
        self.bundle["resources"]["activities"][0]["data"][0]["activityType"][
            "typeKey"
        ] = "treadmill_running"
        result = self.normalized()
        self.assertEqual(result["periods"][0]["runningSessions"], 2)

    def test_invalid_dates_duplicates_and_mismatches_fail(self):
        modifications = [
            lambda b: b.update(end_date="2025-03-17"),
            lambda b: b["resources"]["daily"].append(b["resources"]["daily"][0]),
            lambda b: b["resources"]["daily"][0]["data"].update(
                calendarDate="2024-01-01"
            ),
            lambda b: b["resources"]["activities"][0]["data"].append(
                b["resources"]["activities"][0]["data"][0]
            ),
            lambda b: b["resources"]["activities"][0]["data"][0].update(
                startTimeLocal="2024-01-01 12:00:00"
            ),
        ]
        for mutate in modifications:
            with self.subTest(mutate=mutate):
                bundle = demo_bundle()
                mutate(bundle)
                with self.assertRaises(report.api.PullError):
                    report.normalize(bundle)

    def test_invalid_measurements_remain_missing(self):
        for value in [True, -1, float("nan"), float("inf"), "50"]:
            with self.subTest(value=value):
                self.assertIsNone(report.number(value))
        self.assertEqual(report.number(0), 0)
        self.assertIsNone(report.number(101, 0, 100))

    def test_default_dates_use_local_yesterday_including_dst(self):
        now = dt.datetime(2025, 3, 10, 6, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(
            report.resolve_window(14, timezone="America/Los_Angeles", now=now)[:2],
            ("2025-02-23", "2025-03-08"),
        )
        self.assertEqual(
            report.resolve_window(14, timezone="UTC", now=now)[:2],
            ("2025-02-24", "2025-03-09"),
        )
        with self.assertRaises(report.api.PullError):
            report.resolve_window(13)
        with self.assertRaises(report.api.PullError):
            report.resolve_window(14, timezone="Invalid/Zone")

    def test_summary_changes_with_data(self):
        original = report.narrative(self.normalized())
        for entry in self.bundle["resources"]["sleep"]:
            entry["data"]["sleepTimeSeconds"] = 9 * 3600
        changed = report.narrative(self.normalized())
        self.assertNotEqual(original["sleep"], changed["sleep"])
        self.assertIn("9h 00m", changed["sleep"])
        self.assertNotIn(
            "Make sleep the first experiment", " ".join(changed["suggestions"])
        )

    def test_portable_html_escaping_and_projection(self):
        attack = '</script><script>alert("test")</script>'
        self.bundle["timezone"] = attack
        self.bundle["resources"]["activities"][0]["data"][0]["ownerFullName"] = (
            "PRIVATE OWNER"
        )
        self.bundle["resources"]["activities"][0]["data"][0]["startLatitude"] = 123.456
        page = report.render(self.normalized())
        self.assertNotIn(attack, page)
        self.assertNotIn("PRIVATE OWNER", page)
        self.assertNotIn("startLatitude", page)
        self.assertNotIn("{{", page)
        self.assertNotRegex(page, r'<(?:script|link|img)[^>]+(?:src|href)="https?://')
        self.assertEqual(page.count('<figure class="chart">'), 6)
        embedded = re.search(
            r'<script id="report-data" type="application/json">(.*?)</script>',
            page,
            re.S,
        )
        self.assertEqual(json.loads(embedded.group(1))["timezone"], attack)

    def test_charts_preserve_gaps(self):
        rows = [
            {"date": f"2025-03-0{i + 1}", "value": v}
            for i, v in enumerate([10, None, 30])
        ]
        svg = report.chart(rows, ["value"], ["Value"], "Test", "points")
        self.assertEqual(svg.count("<polyline"), 2)
        self.assertEqual(svg.count("<circle"), 2)


class CommandTests(unittest.TestCase):
    def run_main(self, args):
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return report.main(args)

    def test_demo_and_saved_bundle_are_offline_and_private(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(report.api, "exchange_api_key") as exchange,
            patch.object(report.api, "Client") as client,
        ):
            root = Path(directory)
            output, raw, replay = (
                root / "demo.html",
                root / "bundle.json",
                root / "replay.html",
            )
            self.assertEqual(
                self.run_main(
                    ["--demo", "--output", str(output), "--save-json", str(raw)]
                ),
                0,
            )
            self.assertEqual(
                self.run_main(["--from-json", str(raw), "--output", str(replay)]), 0
            )
            self.assertEqual(output.read_bytes(), replay.read_bytes())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
            exchange.assert_not_called()
            client.assert_not_called()

    def test_one_exchange_for_entire_fetch(self):
        bundle = demo_bundle()
        calls = []

        def collect(client, args):
            calls.append((args.resource, args.date))
            entries = bundle["resources"][args.resource]
            entry = next(e for e in entries if e["requested_date"] == args.date)
            return entry["data"], entry["metadata"]

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"GARMIN_API_KEY": "synthetic-api-key"}, clear=True),
            patch.object(
                report.api, "exchange_api_key", return_value="synthetic-token"
            ) as exchange,
            patch.object(report.api, "collect", side_effect=collect),
            patch.object(report.api, "Client") as client,
        ):
            output = Path(directory) / "live.html"
            self.assertEqual(
                self.run_main(
                    [
                        "--end-date",
                        "2025-03-16",
                        "--timezone",
                        "UTC",
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            exchange.assert_called_once_with("synthetic-api-key", approved=True)
            client.assert_called_once_with("synthetic-token")
            self.assertEqual(len(calls), 44)
            self.assertEqual(client.return_value._token, None)
            self.assertNotIn("synthetic-api-key", output.read_text())
            self.assertNotIn("synthetic-token", output.read_text())

    def test_existing_token_skips_exchange(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, {"GARMIN_ACCESS_TOKEN": "synthetic-token"}, clear=True
            ),
            patch.object(report.api, "exchange_api_key") as exchange,
            patch.object(report, "fetch_bundle", return_value=demo_bundle()),
        ):
            self.assertEqual(
                self.run_main(["--output", str(Path(directory) / "token.html")]), 0
            )
            exchange.assert_not_called()

    def test_exchange_failure_is_not_retried(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"GARMIN_API_KEY": "synthetic-api-key"}, clear=True),
            patch.object(
                report.api,
                "exchange_api_key",
                side_effect=report.api.PullError("Failed"),
            ) as exchange,
            patch.object(report, "fetch_bundle") as fetch,
        ):
            output = Path(directory) / "failed.html"
            self.assertEqual(self.run_main(["--output", str(output)]), 1)
            exchange.assert_called_once()
            fetch.assert_not_called()
            self.assertFalse(output.exists())

    def test_existing_output_rejected_before_auth(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(report.api, "exchange_api_key") as exchange,
        ):
            output = Path(directory) / "existing.html"
            output.write_text("keep me")
            self.assertEqual(self.run_main(["--output", str(output)]), 1)
            exchange.assert_not_called()
            self.assertEqual(output.read_text(), "keep me")

    def test_malformed_offline_input_and_mixed_options_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad.json"
            bad.write_text('{"resources":[]}')
            self.assertEqual(
                self.run_main(
                    ["--from-json", str(bad), "--output", str(root / "bad.html")]
                ),
                1,
            )
            self.assertFalse((root / "bad.html").exists())
            self.assertEqual(
                self.run_main(
                    ["--demo", "--days", "14", "--output", str(root / "mixed.html")]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
