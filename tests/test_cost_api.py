"""Tests for OpenCode session cost when the DB lags the running service."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import configure, load_script, make_job


class CostApiFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        (self.root / "factory" / "bin").mkdir(parents=True)
        self.db = Path(self.tmp.name) / "opencode.db"
        self.db.write_text("")
        os.environ["OPENCODE_DB"] = str(self.db)
        import sqlite3
        con = sqlite3.connect(self.db)
        con.executescript(
            "create table session (id text primary key, parent_id text, cost real default 0, "
            "model text, agent text);"
            "create table message (id text primary key, session_id text, time_created integer, data text);"
            "create table part (id text primary key, message_id text, session_id text, "
            "time_created integer, data text);"
        )
        con.close()
        self.job_mod = load_script("job")
        configure(self.job_mod, self.root)

    def tearDown(self):
        os.environ.pop("OPENCODE_DB", None)
        self.tmp.cleanup()

    def test_uses_api_when_recorded_sessions_are_not_in_the_db_yet(self):
        make_job(self.root, sessions={"builder": "ses_a", "reviewer-code": "ses_b"})
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            sid = cmd[-1].rsplit("/", 1)[-1]
            cost = {"ses_a": 1.25, "ses_b": 0.75}[sid]
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps({"data": {"id": sid, "cost": cost, "parentID": "ses_parent"}}), ""
            )

        original = self.job_mod.subprocess.run
        self.job_mod.subprocess.run = fake_run
        try:
            total = self.job_mod.cost_usd(self.job_mod.resolve("001-test"))
        finally:
            self.job_mod.subprocess.run = original

        self.assertEqual(total, 2.0)
        self.assertEqual(len(calls), 2)

    def test_api_failures_do_not_break_sync(self):
        make_job(self.root, sessions={"builder": "ses_missing"})
        original = self.job_mod.subprocess.run
        self.job_mod.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "no session")
        try:
            self.assertEqual(self.job_mod.cost_usd(self.job_mod.resolve("001-test")), 0.0)
        finally:
            self.job_mod.subprocess.run = original


if __name__ == "__main__":
    unittest.main()
