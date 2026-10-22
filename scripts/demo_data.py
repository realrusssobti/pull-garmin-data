"""Small, wholly synthetic Garmin-shaped dataset for demos and offline tests."""

import datetime as dt


def demo_bundle():
    start = dt.date(2025, 3, 3)
    resources = {
        key: [] for key in ("activities", "daily", "sleep", "heart-rate", "hrv")
    }
    activities, hrv = [], []
    sleep_hours = [6.2, 7.1, 6.8, 6.4, 7.3, 7.8, 7.0, 7.2, 7.6, 7.1, 7.5, 7.8, 8.0, 7.4]
    for i in range(14):
        date = (start + dt.timedelta(days=i)).isoformat()
        rhr = [54, 53, 55, 54, 52, 53, 52, 52, 51, 53, 52, 51, 50, 51][i]
        daily = {
            "calendarDate": date,
            "restingHeartRate": rhr,
            "totalSteps": 6500 + (i * 791) % 8000,
            "averageStressLevel": 32 - i // 2,
            "bodyBatteryAtWakeTime": 65 + i,
            "bodyBatteryLowestValue": 18 + i % 8,
        }
        sleep = {
            "calendarDate": date,
            "sleepTimeSeconds": sleep_hours[i] * 3600,
            "napTimeSeconds": 1200 if i in (2, 8) else 0,
            "sleepScores": {"overall": {"value": 70 + i}},
            "avgSleepStress": 21 - i // 3,
        }
        heart = {"calendarDate": date, "restingHeartRate": rhr}
        for key, record in [("daily", daily), ("sleep", sleep), ("heart-rate", heart)]:
            resources[key].append(
                {"requested_date": date, "data": record, "metadata": {"complete": True}}
            )
        hrv.append(
            {
                "calendarDate": date,
                "lastNightAvg": 48 + i,
                "weeklyAvg": 50 + i // 2,
                "baseline": {"balancedLow": 42, "balancedUpper": 68},
                "status": "BALANCED",
            }
        )
        if i in (2, 6, 9, 13):
            continue
        kind = "running" if i % 3 != 1 else "strength_training"
        duration = (30 + i % 4 * 5) * 60
        activities.append(
            {
                "activityId": 1000 + i,
                "startTimeLocal": date + " 07:30:00",
                "activityType": {"typeKey": kind},
                "duration": duration,
                "distance": duration / (360 if i < 7 else 350) * 1000
                if kind == "running"
                else 0,
                "averageHR": 138 + i % 6,
                "maxHR": 165,
                "activityTrainingLoad": 40 + i * 2,
                "aerobicTrainingEffect": 2.5 + i % 4 / 10,
                "anaerobicTrainingEffect": 0.6,
                "elevationGain": 22 + i,
                "trainingEffectLabel": "AEROBIC_BASE",
            }
        )
    resources["activities"] = [
        {"requested_date": None, "data": activities, "metadata": {"complete": True}}
    ]
    resources["hrv"] = [
        {
            "requested_date": None,
            "data": {"hrvSummaries": hrv},
            "metadata": {"complete": True},
        }
    ]
    return {
        "schema_version": 1,
        "synthetic": True,
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=13)).isoformat(),
        "timezone": "America/Los_Angeles",
        "retrieved_at": "2025-03-17T12:00:00+00:00",
        "resources": resources,
        "errors": [],
    }
