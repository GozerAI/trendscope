"""Tests for TrendScheduler."""

import threading
import time

import pytest

from trendscope.scheduler import TrendScheduler, ScheduleEntry


class TestScheduleEntry:
    def test_defaults(self):
        entry = ScheduleEntry(name="test", interval_minutes=5.0, callback=lambda: None)
        assert entry.name == "test"
        assert entry.interval_minutes == 5.0
        assert entry.enabled is True
        assert entry.last_run is None
        assert entry.run_count == 0
        assert entry.last_status == "pending"
        assert entry.last_error is None

    def test_custom_values(self):
        entry = ScheduleEntry(
            name="custom",
            interval_minutes=10.0,
            callback=lambda: None,
            enabled=False,
            run_count=5,
            last_status="success",
        )
        assert entry.enabled is False
        assert entry.run_count == 5
        assert entry.last_status == "success"


class TestTrendScheduler:
    @pytest.fixture
    def scheduler(self):
        s = TrendScheduler()
        yield s
        s.stop()

    def test_register(self, scheduler):
        scheduler.register("test_job", 10.0, lambda: None)
        assert "test_job" in scheduler._schedules

    def test_list_schedules_empty(self, scheduler):
        assert scheduler.list_schedules() == []

    def test_list_schedules(self, scheduler):
        scheduler.register("job1", 5.0, lambda: None)
        scheduler.register("job2", 10.0, lambda: None)
        schedules = scheduler.list_schedules()
        assert len(schedules) == 2
        names = {s["name"] for s in schedules}
        assert names == {"job1", "job2"}

    def test_list_schedules_structure(self, scheduler):
        scheduler.register("job", 15.0, lambda: None)
        schedules = scheduler.list_schedules()
        s = schedules[0]
        assert s["name"] == "job"
        assert s["interval_minutes"] == 15.0
        assert s["enabled"] is True
        assert s["last_run"] is None
        assert s["run_count"] == 0
        assert s["last_status"] == "pending"
        assert s["last_error"] is None

    def test_run_now_success(self, scheduler):
        called = []
        scheduler.register("job", 10.0, lambda: called.append(1))
        result = scheduler.run_now("job")
        assert result["status"] == "success"
        assert result["run_count"] == 1
        assert len(called) == 1

    def test_run_now_not_found(self, scheduler):
        result = scheduler.run_now("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_run_now_error(self, scheduler):
        def fail():
            raise ValueError("boom")

        scheduler.register("fail_job", 10.0, fail)
        result = scheduler.run_now("fail_job")
        assert result["status"] == "error"
        assert "boom" in result["error"]

    def test_run_now_concurrent_protection(self, scheduler):
        """Concurrent runs of the same schedule are blocked."""
        barrier = threading.Event()
        started = threading.Event()

        def slow_job():
            started.set()
            barrier.wait(timeout=5)

        scheduler.register("slow", 10.0, slow_job)

        # Start first run in a thread
        t = threading.Thread(target=scheduler.run_now, args=("slow",))
        t.start()
        started.wait(timeout=2)

        # Second run should be skipped
        result = scheduler.run_now("slow")
        assert result["status"] == "skipped"
        assert result["reason"] == "already running"

        barrier.set()
        t.join(timeout=2)

    def test_enable_disable(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.disable("job")
        assert scheduler._schedules["job"].enabled is False
        scheduler.enable("job")
        assert scheduler._schedules["job"].enabled is True

    def test_start_stop(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.start()
        assert scheduler._started is True
        assert "job" in scheduler._timers
        scheduler.stop()
        assert scheduler._started is False
        assert len(scheduler._timers) == 0

    def test_run_now_updates_count(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.run_now("job")
        scheduler.run_now("job")
        scheduler.run_now("job")
        entry = scheduler._schedules["job"]
        assert entry.run_count == 3

    def test_run_now_records_error(self, scheduler):
        def fail():
            raise RuntimeError("test error")

        scheduler.register("err", 10.0, fail)
        scheduler.run_now("err")
        entry = scheduler._schedules["err"]
        assert entry.last_status == "error"
        assert entry.last_error == "test error"

    def test_run_now_clears_error_on_success(self, scheduler):
        counter = {"n": 0}

        def sometimes_fail():
            counter["n"] += 1
            if counter["n"] == 1:
                raise RuntimeError("first fail")

        scheduler.register("job", 10.0, sometimes_fail)
        scheduler.run_now("job")
        assert scheduler._schedules["job"].last_status == "error"

        scheduler.run_now("job")
        assert scheduler._schedules["job"].last_status == "success"
        assert scheduler._schedules["job"].last_error is None

    def test_run_now_updates_last_run(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        assert scheduler._schedules["job"].last_run is None
        scheduler.run_now("job")
        assert scheduler._schedules["job"].last_run is not None

    def test_disabled_schedule_not_started(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.disable("job")
        scheduler.start()
        assert "job" not in scheduler._timers

    def test_enable_while_running_arms_timer(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.disable("job")
        scheduler.start()
        assert "job" not in scheduler._timers
        scheduler.enable("job")
        assert "job" in scheduler._timers

    def test_disable_cancels_timer(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.start()
        assert "job" in scheduler._timers
        scheduler.disable("job")
        assert "job" not in scheduler._timers

    def test_get_schedule(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        entry = scheduler.get_schedule("job")
        assert entry is not None
        assert entry.name == "job"

    def test_get_schedule_not_found(self, scheduler):
        assert scheduler.get_schedule("nonexistent") is None

    def test_multiple_registers_overwrite(self, scheduler):
        scheduler.register("job", 10.0, lambda: None)
        scheduler.register("job", 20.0, lambda: None)
        assert scheduler._schedules["job"].interval_minutes == 20.0
