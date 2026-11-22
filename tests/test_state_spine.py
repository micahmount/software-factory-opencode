"""Tests for the deterministic OpenCode factory spine."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import EXPECTED_CONFIG, REPO, configure, load_script, make_job, write_config


def git(cwd, *args, check=True):
    res = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Factory", "GIT_AUTHOR_EMAIL": "factory@example.com",
             "GIT_COMMITTER_NAME": "Factory", "GIT_COMMITTER_EMAIL": "factory@example.com"},
    )
    if check and res.returncode:
        raise AssertionError(f"git {args} failed: {res.stderr}")
    return res.stdout.strip()


def make_db(path, sessions):
    con = sqlite3.connect(path)
    con.executescript(
        "create table session (id text primary key, parent_id text, cost real default 0, "
        "model text, agent text);"
        "create table message (id text primary key, session_id text, time_created integer, data text);"
        "create table part (id text primary key, message_id text, session_id text, "
        "time_created integer, data text);"
    )
    for i, (sid, parent, cost, prompt) in enumerate(sessions):
        con.execute("insert into session values (?, ?, ?, ?, ?)", (sid, parent, cost, "{}", "build"))
        msg = f"msg-{i}"
        con.execute("insert into message values (?, ?, ?, ?)",
                    (msg, sid, i, json.dumps({"role": "user"})))
        con.execute("insert into part values (?, ?, ?, ?, ?)",
                    (f"part-{i}", msg, sid, i, json.dumps({"type": "text", "text": prompt})))
    con.commit()
    con.close()


class StateSpineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        (self.root / "factory" / "bin").mkdir(parents=True)
        for name in ("job", "gate", "route"):
            src = REPO / "factory" / "bin" / name
            if src.exists():
                dst = self.root / "factory" / "bin" / name
                shutil.copy2(src, dst)
                dst.chmod(0o755)
        self.db = Path(self.tmp.name) / "opencode.db"
        os.environ["OPENCODE_DB"] = str(self.db)

    def tearDown(self):
        os.environ.pop("OPENCODE_DB", None)
        self.tmp.cleanup()

    def test_cost_sums_recorded_opencode_sessions_only(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        job = make_job(self.root, sessions={
            "builder": "ses_one", "reviewer-code": "ses_two",
        })
        make_db(self.db, [
            ("ses_one", "ses_parent", 1.25, "Job: 001-test. other text"),
            ("ses_two", "ses_parent", 0.75, "Job: 001-test. other text"),
            ("ses_other", "ses_parent", 99.0, "Job: 002-other. other text"),
        ])
        self.assertEqual(job_mod.cost_usd(job), 2.0)

    def test_cost_finds_sessions_by_job_prompt_without_a_mapping(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        job = make_job(self.root)
        folder = self.root / "factory" / "jobs" / "001-test"
        make_db(self.db, [
            ("ses_match", "ses_parent", 3.5,
             f"Job: 001-test. Job folder: {folder}/. Worktree: /tmp/x."),
            ("ses_other", "ses_parent", 10.0, "Job: 002-other. Job folder: /tmp/other/."),
            ("ses_root", None, 20.0, f"Job: 001-test. Job folder: {folder}/."),
        ])
        self.assertEqual(job_mod.cost_usd(job), 3.5)

    def test_cost_is_zero_when_the_database_is_missing(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        self.db.unlink(missing_ok=True)
        self.assertEqual(job_mod.cost_usd(make_job(self.root)), 0.0)

    def test_session_ids_can_be_recorded_and_read_for_resume(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        make_job(self.root, stage="build", round=1)
        job_mod.cmd_session(job_mod.resolve("001-test"), ["builder-001-test", "ses_abc123"])
        job_mod.cmd_session(job_mod.resolve("001-test"), ["reviewer-code", "ses_def456"])
        self.assertEqual(
            job_mod.resolve("001-test")["sessions"],
            {"builder-001-test": "ses_abc123", "reviewer-code": "ses_def456"},
        )

    def test_route_uses_anthropic_model_ids_from_config(self):
        route = load_script("route")
        configure(route, self.root)
        job_mod = load_script("job")
        configure(job_mod, self.root)
        make_job(self.root, stage="intake", intake={
            "decision": "ACCEPT", "risk": "high", "surfaces": ["ui", "security"],
            "rescoped": False,
        })
        (self.root / "factory" / "jobs" / "001-test" / "intake.md").write_text(
            "DECISION: ACCEPT\nRISK: high\nSURFACES: ui, security\nRESCOPED: no\n\n## Summary\n- ok\n"
        )
        route.main(["001-test"])
        agents = json.loads(
            (self.root / "factory" / "jobs" / "001-test" / "job.json").read_text()
        )["agents"]["reviewers"]
        self.assertEqual(agents, {
            "code": "anthropic/claude-sonnet-5-5",
            "ux": "anthropic/claude-sonnet-5-5",
            "ui": "anthropic/claude-haiku-5-5",
            "security": "anthropic/claude-opus-5-5",
        })

    def test_merge_merges_an_approved_pr(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        job = make_job(self.root, stage="merging", round=1)
        (self.root / "factory" / "jobs" / "001-test" / "decision.md").write_text(
            "APPROVE\n\n## Summary\n- ok\n"
        )
        calls = []
        transitions = []
        originals = {name: getattr(job_mod, name) for name in (
            "sync", "save", "advance", "git", "run", "pr_state", "gh", "gh_json"
        )}
        original_subprocess_run = job_mod.subprocess.run

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        job_mod.sync = lambda j: j
        job_mod.save = lambda j: calls.append(("save", j["stage"]))
        job_mod.advance = lambda j, stage: (transitions.append(stage), j)[1]
        job_mod.git = lambda j, *args, check=True: Result()
        job_mod.run = lambda args, **kwargs: calls.append(("run", args)) or Result()
        job_mod.pr_state = lambda j: "OPEN"
        job_mod.gh = lambda *args: calls.append(("gh", args)) or ""
        job_mod.gh_json = lambda *args: {"isDraft": True}
        job_mod.subprocess.run = lambda *args, **kwargs: Result()
        try:
            job_mod.cmd_merge(job)
        finally:
            for name, value in originals.items():
                setattr(job_mod, name, value)
            job_mod.subprocess.run = original_subprocess_run

        self.assertEqual(transitions[-1], "merged")
        self.assertIn(("gh", ("pr", "ready", "34")), calls)
        self.assertIn(("gh", ("pr", "merge", "34", "--squash")), calls)
        self.assertTrue(any(call[0] == "run" and "--delete" in call[1] for call in calls))

    def test_merge_escalates_when_sync_conflicts(self):
        job_mod = load_script("job")
        configure(job_mod, self.root)
        job = make_job(self.root, stage="merging", round=1)
        calls = []
        transitions = []
        originals = {name: getattr(job_mod, name) for name in (
            "sync", "save", "advance", "git", "run", "pr_state", "gh", "gh_json", "escalate"
        )}
        original_subprocess_run = job_mod.subprocess.run

        class Result:
            def __init__(self, code=0, stdout=""):
                self.returncode = code
                self.stdout = stdout
                self.stderr = ""

        def fake_git(j, *args, check=True):
            if args[0] == "merge":
                return Result(1, "conflict")
            return Result()

        job_mod.sync = lambda j: j
        job_mod.save = lambda j: calls.append(("save", j["stage"]))
        job_mod.advance = lambda j, stage: (transitions.append(stage), j)[1]
        job_mod.git = fake_git
        job_mod.run = lambda args, **kwargs: Result()
        job_mod.pr_state = lambda j: "OPEN"
        job_mod.gh = lambda *args: calls.append(("gh", args)) or ""
        job_mod.gh_json = lambda *args: {"isDraft": False}
        job_mod.escalate = lambda j, why: calls.append(("escalate", why.splitlines()[0]))
        job_mod.subprocess.run = lambda *args, **kwargs: Result()
        try:
            job_mod.cmd_merge(job)
        finally:
            for name, value in originals.items():
                setattr(job_mod, name, value)
            job_mod.subprocess.run = original_subprocess_run

        self.assertEqual(transitions[-1], "needs-human")
        self.assertTrue(any(call[0] == "escalate" for call in calls))
        self.assertFalse(any(call[0] == "gh" and "merge" in call[1] for call in calls))

    def test_gate_has_no_claude_hook_mode(self):
        gate = load_script("gate")
        configure(gate, self.root)
        with self.assertRaises(SystemExit) as caught:
            gate.main(["--hook"])
        self.assertEqual(caught.exception.code, 2)

    def test_gate_writes_checks_md_and_refuses_protected_changes(self):
        gate = load_script("gate")
        configure(gate, self.root)
        origin = Path(self.tmp.name) / "origin.git"
        git(Path(self.tmp.name), "init", "--bare", "--quiet", str(origin))
        clone = Path(self.tmp.name) / "clone"
        git(Path(self.tmp.name), "clone", "--quiet", str(origin), str(clone))
        git(clone, "config", "user.email", "factory@example.com")
        git(clone, "config", "user.name", "Factory")
        (clone / "README.md").write_text("base\n")
        (clone / "factory").mkdir()
        (clone / "factory" / "config.json").write_text("{}\n")
        git(clone, "add", "README.md", "factory/config.json")
        git(clone, "commit", "--quiet", "-m", "base")
        git(clone, "push", "--quiet", "origin", "HEAD:main")
        git(clone, "symbolic-ref", "HEAD", "refs/heads/main")

        worktree = self.root / ".worktrees" / "001-test"
        worktree.parent.mkdir(parents=True)
        git(self.root, "init", "--quiet")
        git(self.root, "remote", "add", "origin", str(origin))
        git(self.root, "fetch", "--quiet", "origin", "main")
        git(self.root, "worktree", "add", "--quiet", "-b", "factory/001-test",
            str(worktree), "origin/main")
        (worktree / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        git(worktree, "add", "calc.py")
        git(worktree, "commit", "--quiet", "-m", "add calc")
        git(worktree, "push", "--quiet", "-u", "origin", "factory/001-test")

        (self.root / "factory" / "checks.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        make_job(self.root, stage="round", round=1)
        rounds = self.root / "factory" / "jobs" / "001-test" / "round-1"
        rounds.mkdir()

        with self.assertRaises(SystemExit) as caught:
            gate.main(["001-test"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("GATE: PASS", (rounds / "checks.md").read_text())

        (worktree / "factory" / "config.json").write_text('{"unsafe": true}\n')
        git(worktree, "add", "factory/config.json")
        git(worktree, "commit", "--quiet", "-m", "touch protected file")
        git(worktree, "push", "--quiet", "origin", "factory/001-test")
        with self.assertRaises(SystemExit) as caught:
            gate.main(["001-test"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("GATE: FAIL", (rounds / "checks.md").read_text())


class ConfigTests(unittest.TestCase):
    def test_repo_config_is_the_opencode_routing_table(self):
        config = json.loads((REPO / "factory" / "config.json").read_text())
        self.assertEqual(config["routing"], EXPECTED_CONFIG["routing"])
        self.assertEqual(config["surface_reviewers"], EXPECTED_CONFIG["surface_reviewers"])
        self.assertEqual(config["concurrency"], 1)
        self.assertEqual(config["base_branch"], "main")
        self.assertIn("claude-fable-5-2", config["prices_usd_per_mtok"])

    def test_no_claude_code_paths_remain_in_binaries(self):
        for path in (REPO / "factory" / "bin").glob("*"):
            if not path.is_file():
                continue
            text = path.read_text()
            for banned in ("CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR", "agent_transcript_path",
                           "~/.claude", "subagents/agent-"):
                self.assertNotIn(banned, text, f"{banned} found in {path}")


if __name__ == "__main__":
    unittest.main()
