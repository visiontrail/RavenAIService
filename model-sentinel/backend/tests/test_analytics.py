import unittest
from datetime import datetime, timedelta, timezone

from app.analytics import aggregate, bucket_runs, percentile, period_window


UTC = timezone.utc


def run(at: datetime, success=True, usable=True, latency=1000, error_kind=None):
    return {
        "started_at": at.isoformat(),
        "success": success,
        "usable": usable,
        "latency_ms": latency,
        "ttft_ms": 400 if success else None,
        "total_tokens": 42,
        "error_kind": error_kind,
    }


class AnalyticsTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(percentile([100, 200, 300, 400], 0.95), 385)
        self.assertIsNone(percentile([], 0.95))

    def test_aggregate_reports_capacity_metrics(self):
        now = datetime.now(UTC)
        metrics = aggregate(
            [
                run(now),
                run(
                    now,
                    success=False,
                    usable=False,
                    latency=10,
                    error_kind="rate_limited",
                ),
            ]
        )
        self.assertEqual(metrics["calls"], 2)
        self.assertEqual(metrics["uptime_pct"], 50)
        self.assertEqual(metrics["rate_limit_pct"], 50)
        self.assertEqual(metrics["total_tokens"], 84)

    def test_hourly_buckets_include_empty_periods(self):
        end = datetime(2026, 7, 29, 4, 30, tzinfo=UTC)
        start = end - timedelta(hours=3)
        buckets = bucket_runs(
            [run(datetime(2026, 7, 29, 3, 10, tzinfo=UTC))],
            start,
            end,
            "hourly",
            "UTC",
        )
        self.assertEqual(len(buckets), 4)
        self.assertEqual(sum(bucket["calls"] for bucket in buckets), 1)

    def test_period_window_yields_exact_bucket_count(self):
        for granularity, periods in (("hourly", 24), ("daily", 30)):
            start, end = period_window(periods, granularity, "Asia/Singapore")
            buckets = bucket_runs([], start, end, granularity, "Asia/Singapore")
            self.assertEqual(len(buckets), periods)


if __name__ == "__main__":
    unittest.main()
