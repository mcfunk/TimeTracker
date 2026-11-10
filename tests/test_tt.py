"""Unit tests for tt. Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.dont_write_bytecode = True
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tt")
_loader = importlib.machinery.SourceFileLoader("tt", _PATH)
tt = importlib.util.module_from_spec(importlib.util.spec_from_loader("tt", _loader))
_loader.exec_module(tt)

T0 = datetime(2026, 3, 4, 9, 0, 0)  # a Wednesday


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = tt.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.clock = T0
        patcher = mock.patch.object(tt, "now", lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, **settings):
        for name, value in settings.items():
            patcher = mock.patch.object(tt, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def at(self, minutes):
        """Set the clock to T0 + minutes."""
        self.clock = T0 + timedelta(minutes=minutes)

    def run_tt(self, *argv):
        """Run a command; return (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tt.main(list(argv), conn=self.conn)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_tt(*argv)
        self.assertEqual(code, 0, err)
        return out

    def fail(self, *argv):
        code, _, err = self.run_tt(*argv)
        self.assertEqual(code, 1)
        return err

    def total(self, order_id):
        order = tt._order_by_id(self.conn, order_id)
        return tt.order_seconds(self.conn, order, self.clock)

    def export(self):
        return self.run_tt("export")[1].splitlines()


class TimeCalculationTests(unittest.TestCase):
    def entry(self, **kw):
        base = {"start_ts": "2026-03-04 09:00:00", "end_ts": None,
                "paused_secs": 0, "pause_started_at": None}
        base.update(kw)
        return base

    def test_closed_entry(self):
        e = self.entry(end_ts="2026-03-04 10:30:00")
        self.assertEqual(tt.entry_seconds(e, T0 + timedelta(hours=9)), 5400)

    def test_running_entry_counts_to_now(self):
        self.assertEqual(tt.entry_seconds(self.entry(), T0 + timedelta(minutes=20)), 1200)

    def test_paused_time_is_subtracted(self):
        e = self.entry(end_ts="2026-03-04 10:00:00", paused_secs=900)
        self.assertEqual(tt.entry_seconds(e, T0), 2700)
        self.assertEqual(tt.entry_paused_seconds(e, T0), 900)

    def test_pause_in_progress_stops_the_clock(self):
        e = self.entry(paused_secs=300, pause_started_at="2026-03-04 09:30:00")
        later = T0 + timedelta(hours=3)
        self.assertEqual(tt.entry_seconds(e, later), 1500)  # 30 min - 5 min
        self.assertEqual(tt.entry_paused_seconds(e, later), 300 + 9000)

    def test_never_negative(self):
        e = self.entry(end_ts="2026-03-04 09:01:00", paused_secs=600)
        self.assertEqual(tt.entry_seconds(e, T0), 0)

    def test_fmt_hmm(self):
        self.assertEqual(tt.fmt_hmm(0), "0:00")
        self.assertEqual(tt.fmt_hmm(59), "0:00")
        self.assertEqual(tt.fmt_hmm(3660), "1:01")
        self.assertEqual(tt.fmt_hmm(36000 + 59 * 60), "10:59")

    def test_round_seconds(self):
        self.assertEqual(tt.round_seconds(100, 0), 100)
        self.assertEqual(tt.round_seconds(89, 1), 60)
        self.assertEqual(tt.round_seconds(90, 1), 120)
        self.assertEqual(tt.round_seconds(7 * 60, 15), 0)
        self.assertEqual(tt.round_seconds(8 * 60, 15), 900)
        self.assertEqual(tt.round_seconds(450, 15), 900)  # exactly half rounds up


class DurationFormatTests(unittest.TestCase):
    def test_decimal_hours(self):
        self.assertEqual(tt.format_duration(5400, "decimal_hours", 0), "1.50")
        self.assertEqual(tt.format_duration(4980, "decimal_hours", 15), "1.50")  # 1:23
        self.assertEqual(tt.format_duration(4980, "decimal_hours", 1), "1.38")
        self.assertEqual(tt.format_duration(0, "decimal_hours", 15), "0.00")

    def test_minutes(self):
        self.assertEqual(tt.format_duration(5400, "minutes", 1), "90")
        self.assertEqual(tt.format_duration(5430, "minutes", 0), "90.5")
        self.assertEqual(tt.format_duration(5430, "minutes", 1), "91")
        self.assertEqual(tt.format_duration(4980, "minutes", 15), "90")

    def test_h_mm(self):
        self.assertEqual(tt.format_duration(5400, "h:mm", 1), "1:30")
        self.assertEqual(tt.format_duration(4980, "h:mm", 15), "1:30")
        self.assertEqual(tt.format_duration(299, "h:mm", 0), "0:05")
        self.assertEqual(tt.format_duration(36300, "h:mm", 1), "10:05")

    def test_unknown_format(self):
        with self.assertRaises(tt.TTError):
            tt.format_duration(60, "fortnights", 1)


class StepTests(unittest.TestCase):
    def test_name_prefix_and_number(self):
        self.assertEqual(tt.resolve_step("assemble"), "assemble")
        self.assertEqual(tt.resolve_step("as"), "assemble")
        self.assertEqual(tt.resolve_step("T"), "test")
        self.assertEqual(tt.resolve_step("1"), "pick")
        self.assertEqual(tt.resolve_step("4"), "pack")

    def test_ambiguous_prefix_lists_candidates(self):
        with self.assertRaises(tt.TTError) as ctx:
            tt.resolve_step("p")
        self.assertIn("pick, pack", str(ctx.exception))

    def test_unknown(self):
        for bad in ("zz", "0", "9"):
            with self.assertRaises(tt.TTError):
                tt.resolve_step(bad)

    def test_exact_name_beats_prefix(self):
        with mock.patch.object(tt, "STEPS", ["test", "test2"]):
            self.assertEqual(tt.resolve_step("test"), "test")


class OrderIdTests(Base):
    def test_match_ids(self):
        ids = ["40000123", "40000999", "50000123", "123"]
        self.assertEqual(tt.match_ids("999", ids), ["40000999"])
        self.assertEqual(tt.match_ids("5", ids), ["50000123"])
        self.assertEqual(tt.match_ids("0123", ids), ["40000123", "50000123"])
        self.assertEqual(tt.match_ids("123", ids), ["123"])  # exact wins
        self.assertEqual(tt.match_ids("777", ids), [])

    def test_default_pattern_is_permissive(self):
        for good in ("12345678", "A-1/b#2.c", "a;b$c", "x" * 40):
            self.assertEqual(tt.validate_order_id(good), good)
        for bad in ("", "has space", "x" * 41):
            with self.assertRaises(tt.TTError):
                tt.validate_order_id(bad)

    def test_failed_match_names_id_and_pattern(self):
        self.config(ORDER_ID_REGEX=r"\d{8}")
        err = self.fail("start", "12AB")
        self.assertIn("12AB", err)
        self.assertIn(r"\d{8}", err)
        self.ok("start", "12345678")

    def test_normalize(self):
        self.assertEqual(tt.normalize_order_id("  ab1 "), "ab1")
        self.config(ORDER_ID_NORMALIZE="strip_upper")
        self.assertEqual(tt.normalize_order_id("  ab1 "), "AB1")
        self.config(ORDER_ID_NORMALIZE="none")
        self.assertEqual(tt.normalize_order_id(" ab1 "), " ab1 ")

    def test_suffix_and_prefix_select_open_order(self):
        self.ok("start", "40000123")
        self.ok("start", "50000999")
        self.assertIn("40000123", self.ok("pause", "123"))
        self.assertIn("50000999", self.ok("pause", "5"))

    def test_ambiguous_lists_candidates(self):
        self.ok("start", "40000123")
        self.ok("start", "50000123")
        err = self.fail("pause", "123")
        self.assertIn("ambiguous", err)
        self.assertIn("40000123, 50000123", err)

    def test_no_match(self):
        self.ok("start", "40000123")
        self.assertIn("no open order matches '777'", self.fail("pause", "777"))

    def test_start_reuses_partial_match_unless_new(self):
        self.ok("start", "40000123")
        self.assertIn("Already running: 40000123", self.ok("start", "123"))
        self.assertIn("Opened and started 123", self.ok("start", "--new", "123"))
        self.assertEqual(tt._ids(self.conn, "open"), ["40000123", "123"])

    def test_special_characters_are_stored_safely(self):
        weird = "x'); DROP TABLE orders;--"
        self.config(ORDER_ID_REGEX=r".{1,40}")
        self.ok("start", weird)
        self.assertEqual(tt._ids(self.conn, "open"), [weird])

    def test_default_is_most_recently_touched(self):
        self.ok("start", "111")
        self.ok("start", "222")
        self.assertIn("222", self.ok("pause"))
        self.fail("resume", "111")  # already running: an error, so not a touch
        self.assertIn("222", self.ok("resume"))
        self.ok("note", "hello", "-o", "111")
        self.assertIn("111", self.ok("pause"))

    def test_no_open_orders(self):
        self.assertIn("no open orders", self.fail("pause"))


class TimerTests(Base):
    def test_pause_resume_excludes_break(self):
        self.ok("start", "111")
        self.at(30)
        self.assertIn("Paused 111 [pick] at 0:30", self.ok("pause"))
        self.at(45)
        self.assertEqual(self.total("111"), 1800)  # clock stopped while paused
        self.assertIn("Resumed 111", self.ok("resume"))
        self.at(60)
        self.ok("stop")
        self.assertEqual(self.total("111"), 2700)
        entry = self.conn.execute("SELECT * FROM entries").fetchone()
        self.assertEqual(entry["paused_secs"], 900)

    def test_stop_while_paused_ends_at_pause(self):
        self.ok("start", "111")
        self.at(20)
        self.ok("pause")
        self.at(500)
        self.ok("stop")
        entry = self.conn.execute("SELECT * FROM entries").fetchone()
        self.assertEqual(entry["end_ts"], "2026-03-04 09:20:00")
        self.assertEqual(self.total("111"), 1200)

    def test_pause_errors(self):
        self.ok("start", "111")
        self.ok("pause")
        self.assertIn("already paused", self.fail("pause"))
        self.ok("stop")
        self.assertIn("no active timer", self.fail("pause"))
        self.assertIn("no active timer", self.fail("stop"))

    def test_resume_running_is_an_error(self):
        self.ok("start", "111")
        self.assertIn("already running", self.fail("resume"))

    def test_start_keeps_other_timers_running(self):
        self.ok("start", "111")
        self.ok("start", "222")
        self.at(10)
        self.assertEqual(self.total("111"), 600)
        self.assertEqual(self.total("222"), 600)

    def test_switch_pauses_others(self):
        self.ok("start", "111")
        self.ok("start", "222")
        self.at(10)
        out = self.ok("switch", "333")
        self.assertIn("paused: 111, 222", out)
        self.at(25)
        self.assertEqual(self.total("111"), 600)
        self.assertEqual(self.total("333"), 900)
        self.assertIn("Resumed 111", self.ok("switch", "111"))
        self.at(30)
        self.assertEqual(self.total("111"), 900)
        self.assertEqual(self.total("333"), 900)

    def test_pause_all_and_stop_all(self):
        self.ok("start", "111")
        self.ok("start", "222")
        self.assertIn("Paused 2 timer(s)", self.ok("pause", "--all"))
        self.assertIn("No running timers", self.ok("pause", "--all"))
        self.assertIn("Stopped 2 timer(s)", self.ok("stop", "--all"))
        self.assertIn("No active timers", self.ok("stop", "--all"))

    def test_step_closes_entry_and_marks_complete(self):
        self.ok("start", "111")
        self.at(15)
        out = self.ok("step", "as")
        self.assertIn("from pick (0:15, complete) to assemble", out)
        self.at(25)
        entries = self.conn.execute("SELECT * FROM entries ORDER BY id").fetchall()
        self.assertEqual([(e["step"], e["step_completed"]) for e in entries],
                         [("pick", 1), ("assemble", 0)])
        self.assertEqual(entries[0]["end_ts"], "2026-03-04 09:15:00")
        self.assertEqual(self.total("111"), 1500)
        self.assertIn("already on step", self.fail("step", "2"))
        self.assertIn("unknown step", self.fail("step", "zz"))

    def test_step_on_stopped_order_marks_last_entry(self):
        self.ok("start", "111")
        self.at(5)
        self.ok("stop")
        self.ok("step", "3")
        first = self.conn.execute("SELECT * FROM entries ORDER BY id").fetchone()
        self.assertEqual(first["step_completed"], 1)

    def test_done_and_reopen(self):
        self.ok("start", "111", "pack")
        self.at(40)
        self.assertIn("Done: 111 completed at step pack, total 0:40", self.ok("done"))
        self.assertEqual(tt._ids(self.conn, "open"), [])
        self.assertIn("already done", self.fail("pause", "111"))
        self.assertIn("Total for 111: 0:40", self.ok("show", "111"))
        self.assertIn("Reopened and started 111", self.ok("start", "111"))

    def test_status_and_bare_command(self):
        self.assertIn("No open orders", self.ok("status"))
        self.ok("start", "111")
        self.at(61)
        out = self.ok()
        self.assertIn("running", out)
        self.assertIn("1:01", out)

    def test_note(self):
        self.ok("start", "111")
        self.ok("note", "waiting", "on", "parts")
        self.ok("note", "arrived")
        note = self.conn.execute("SELECT note FROM entries").fetchone()["note"]
        self.assertEqual(note, "waiting on parts; arrived")

    def test_state_survives_reconnect(self):
        path = os.path.join(self.enterContext(__import__("tempfile").TemporaryDirectory()),
                            "sub", "tt.db")
        conn = tt.connect(path)
        with contextlib.redirect_stdout(io.StringIO()):
            tt.main(["start", "111"], conn=conn)
        conn.commit()
        conn.close()
        self.at(90)
        conn = tt.connect(path)
        self.addCleanup(conn.close)
        self.assertEqual(tt.order_seconds(conn, tt._order_by_id(conn, "111"), self.clock), 5400)


class EditTests(Base):
    def setUp(self):
        super().setUp()
        self.ok("start", "111")
        self.at(60)
        self.ok("stop")

    def test_list(self):
        out = self.ok("edit")
        self.assertIn("#1", out)
        self.assertIn("1:00", out)

    def test_adjust_start_and_end(self):
        self.ok("edit", "1", "--start", "08:30", "--end", "09:45")
        self.assertEqual(self.total("111"), 75 * 60)

    def test_full_datetime(self):
        self.ok("edit", "1", "--start", "2026-03-03 23:30")
        self.assertEqual(self.total("111"), 10 * 3600 + 1800)

    def test_rejects_bad_times(self):
        self.assertIn("must be before", self.fail("edit", "1", "--start", "10:30"))
        self.assertIn("future", self.fail("edit", "1", "--end", "23:00"))
        self.assertIn("invalid time", self.fail("edit", "1", "--end", "noon"))
        self.assertIn("no entry", self.fail("edit", "99", "--delete"))
        self.assertEqual(self.total("111"), 3600)

    def test_delete(self):
        self.assertIn("Deleted entry #1", self.ok("edit", "1", "--delete"))
        self.assertEqual(self.total("111"), 0)


class ExportTests(Base):
    """Two orders on one day:

    111: pick 9:00-9:30, assemble 9:30-10:40 with a 10-minute pause (60 worked),
         pick again 10:40-10:53 (13 minutes), then done.
    222: pick 9:00-9:20, stopped (open).
    """

    def setUp(self):
        super().setUp()
        self.config(
            CSV_COLUMNS=["order_id", "step", "date", "start", "end", "duration",
                         "paused_time", "order_status", "note"],
            CSV_HEADERS={}, CSV_ROW_MODE="entry", CSV_DURATION_FORMAT="minutes",
            CSV_ROUND_MINUTES=1, CSV_DATE_FORMAT="%Y-%m-%d", CSV_TIME_FORMAT="%H:%M",
            CSV_DELIMITER=",", CSV_INCLUDE_HEADER=False)
        self.ok("start", "111")
        self.ok("start", "222")
        self.at(20)
        self.ok("stop", "222")
        self.at(30)
        self.ok("step", "assemble", "111")
        self.ok("note", "jig missing")
        self.at(50)
        self.ok("pause")
        self.at(60)
        self.ok("resume")
        self.at(100)
        self.ok("step", "pick")
        self.ok("note", "rework")
        self.at(113)
        self.ok("done")

    def test_entry_mode(self):
        self.assertEqual(self.export(), [
            "111,pick,2026-03-04,09:00,09:30,30,0,done,",
            "222,pick,2026-03-04,09:00,09:20,20,0,open,",
            "111,assemble,2026-03-04,09:30,10:40,60,10,done,jig missing",
            "111,pick,2026-03-04,10:40,10:53,13,0,done,rework",
        ])

    def test_step_mode(self):
        self.config(CSV_ROW_MODE="step")
        self.assertEqual(self.export(), [
            "111,pick,2026-03-04,09:00,10:53,43,0,done,rework",
            "222,pick,2026-03-04,09:00,09:20,20,0,open,",
            "111,assemble,2026-03-04,09:30,10:40,60,10,done,jig missing",
        ])

    def test_order_mode(self):
        self.config(CSV_ROW_MODE="order")
        self.assertEqual(self.export(), [
            '111,"pick, assemble",2026-03-04,09:00,10:53,103,10,done,jig missing; rework',
            "222,pick,2026-03-04,09:00,09:20,20,0,open,",
        ])

    def test_decimal_hours_rounded_to_quarter_after_summing(self):
        self.config(CSV_ROW_MODE="order", CSV_DURATION_FORMAT="decimal_hours",
                    CSV_ROUND_MINUTES=15, CSV_COLUMNS=["order_id", "duration", "paused_time"])
        # 103 min -> 1.75 h (per-entry rounding would give 0.5 + 1.0 + 0.25).
        self.assertEqual(self.export(), ["111,1.75,0.25", "222,0.25,0.00"])

    def test_h_mm(self):
        self.config(CSV_ROW_MODE="order", CSV_DURATION_FORMAT="h:mm",
                    CSV_COLUMNS=["order_id", "duration", "paused_time"])
        self.assertEqual(self.export(), ["111,1:43,0:10", "222,0:20,0:00"])

    def test_headers_columns_delimiter_and_formats(self):
        self.config(CSV_COLUMNS=["date", "order_id", "start", "duration"],
                    CSV_HEADERS={"order_id": "Work Order", "duration": "Mins"},
                    CSV_INCLUDE_HEADER=True, CSV_DELIMITER=";", CSV_ROW_MODE="order",
                    CSV_DATE_FORMAT="%d/%m/%Y", CSV_TIME_FORMAT="%I:%M %p")
        self.assertEqual(self.export(), [
            "date;Work Order;start;Mins",
            "04/03/2026;111;09:00 AM;103",
            "04/03/2026;222;09:00 AM;20",
        ])

    def test_running_entry_has_blank_end_and_counts_to_now(self):
        self.ok("start", "222")
        self.at(120)
        self.config(CSV_COLUMNS=["order_id", "start", "end", "duration"])
        self.assertEqual(self.export()[-1], "222,10:53,,7")

    def test_unknown_column(self):
        self.config(CSV_COLUMNS=["order_id", "colour"])
        self.assertIn("colour", self.fail("export"))

    def test_csv_file_and_date_filters(self):
        path = os.path.join(self.enterContext(__import__("tempfile").TemporaryDirectory()), "o.csv")
        self.assertIn("Exported 4 row(s)", self.ok("export", "--csv", path, "--today"))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().splitlines()), 4)
        self.clock = T0 + timedelta(days=1)  # Thursday of the same week
        self.assertEqual(self.run_tt("export", "--today")[1], "")
        self.assertEqual(len(self.run_tt("export", "--week")[1].splitlines()), 4)
        self.assertEqual(len(self.run_tt("export", "--from", "2026-03-04", "--to", "2026-03-04")[1]
                             .splitlines()), 4)
        self.assertEqual(self.run_tt("export", "--from", "2026-03-05")[1], "")
        self.assertIn("only one of", self.fail("export", "--today", "--week"))
        self.assertIn("YYYY-MM-DD", self.fail("export", "--from", "yesterday"))

    def test_report(self):
        out = self.ok("report")
        self.assertRegex(out, r"111\s+done\s+pick, assemble\s+1:43")
        self.assertRegex(out, r"222\s+open\s+-\s+0:20")
        self.assertIn("2 order(s), total 2:03 (today)", out)
        self.clock = T0 + timedelta(days=7)
        self.assertIn("No time recorded (this week)", self.ok("report", "--week"))

    def test_show(self):
        out = self.ok("show", "111")
        self.assertRegex(out, r"pick\s+0:43\s+complete")
        self.assertRegex(out, r"assemble\s+1:00\s+complete")
        self.assertIn("Total for 111: 1:43", out)


if __name__ == "__main__":
    unittest.main()
