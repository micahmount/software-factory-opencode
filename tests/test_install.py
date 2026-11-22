"""Tests for dropping the factory into another OpenCode project."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import REPO

INSTALL = REPO / "factory" / "install"
LABELS = REPO / "factory" / "labels"


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / "factory-checkout"
        self.target = Path(self.tmp.name) / "target"
        shutil.copytree(
            REPO, self.source,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "jobs", ".worktrees"),
        )
        self.target.mkdir()
        run(["git", "init", "-q", str(self.target)])

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_copies_the_factory_without_runtime_state(self):
        (self.target / "opencode.json").write_text(json.dumps({"model": "keep/this", "x": 1}))
        res = run([str(INSTALL), str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        for path in (
            "factory/bin/job", "factory/bin/gate", "factory/bin/route",
            "factory/checks.sh", "factory/config.json", "factory/dashboard.html",
            "factory/labels", "factory/install", ".opencode/commands/factory.md",
            ".opencode/agents/intake.md", ".opencode/agents/approver.md",
            ".opencode/opencode.json",
        ):
            self.assertTrue((self.target / path).exists(), path)
        self.assertFalse((self.target / "factory" / "jobs").exists())
        self.assertFalse((self.target / ".worktrees").exists())
        self.assertEqual(
            json.loads((self.target / "opencode.json").read_text()),
            {"model": "keep/this", "x": 1},
        )
        settings = json.loads((self.target / ".opencode" / "opencode.json").read_text())
        self.assertEqual(settings["worktree"]["directory"], ".worktrees")

    def test_install_refuses_to_clobber_and_force_replaces_factory_files(self):
        (self.target / "opencode.json").write_text("{}")
        self.assertEqual(run([str(INSTALL), str(self.target)]).returncode, 0)
        (self.target / ".opencode" / "agents" / "custom.md").write_text("custom\n")
        (self.target / ".opencode" / "commands" / "custom.md").write_text("custom\n")
        (self.target / ".opencode" / "agents" / "intake.md").write_text("stale\n")
        again = run([str(INSTALL), str(self.target)])
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already installed", again.stderr)
        forced = run([str(INSTALL), "--force", str(self.target)])
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual((self.target / ".opencode" / "agents" / "custom.md").read_text(), "custom\n")
        self.assertEqual((self.target / ".opencode" / "commands" / "custom.md").read_text(), "custom\n")
        self.assertNotIn("stale", (self.target / ".opencode" / "agents" / "intake.md").read_text())

    def test_install_merges_existing_opencode_settings(self):
        (self.target / ".opencode").mkdir()
        (self.target / ".opencode" / "opencode.json").write_text(json.dumps({
            "model": "keep/this",
            "x": 1,
            "worktree": {"directory": "custom-worktrees", "other": True},
            "permissions": [{"action": "read", "resource": "custom/*", "effect": "allow"}],
        }))
        (self.target / ".opencode" / "agents").mkdir()
        (self.target / ".opencode" / "agents" / "custom.md").write_text("custom\n")

        res = run([str(INSTALL), str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        settings = json.loads((self.target / ".opencode" / "opencode.json").read_text())
        self.assertEqual(settings["model"], "keep/this")
        self.assertEqual(settings["x"], 1)
        self.assertTrue(settings["worktree"]["other"])
        self.assertEqual(settings["worktree"]["directory"], ".worktrees")
        rules = {(r["action"], r.get("resource")): r["effect"] for r in settings["permissions"]}
        self.assertEqual(rules[("read", "custom/*")], "allow")
        self.assertEqual(rules[("subagent", "*")], "allow")
        self.assertEqual(rules[("shell", "gh pr merge *")], "ask")
        self.assertTrue((self.target / ".opencode" / "agents" / "custom.md").exists())
        self.assertTrue((self.target / ".opencode" / "agents" / "intake.md").exists())

    def test_install_adds_runtime_paths_to_gitignore_without_clobbering(self):
        (self.target / ".gitignore").write_text("*.log\n/factory/jobs/\n")
        res = run([str(INSTALL), str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = (self.target / ".gitignore").read_text().splitlines()
        self.assertIn("*.log", lines)
        self.assertEqual(lines.count("/factory/jobs/"), 1)
        self.assertIn("/.worktrees/", lines)

    def test_install_provides_agents_md_without_overwriting_the_projects(self):
        res = run([str(INSTALL), str(self.target)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("factory/checks.sh", (self.target / "AGENTS.md").read_text())
        (self.target / "AGENTS.md").write_text("project rules\n")
        forced = run([str(INSTALL), "--force", str(self.target)])
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual((self.target / "AGENTS.md").read_text(), "project rules\n")

    def test_install_rejects_a_non_git_directory(self):
        bare = Path(self.tmp.name) / "not-a-repo"
        bare.mkdir()
        res = run([str(INSTALL), str(bare)])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("git repository", res.stderr)


class LabelTests(unittest.TestCase):
    def test_labels_creates_the_three_configured_labels(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ghbin = root / "bin"
        ghbin.mkdir()
        log = root / "gh.log"
        (ghbin / "gh").write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> " + str(log) + "\n"
        )
        (ghbin / "gh").chmod(0o755)
        res = run([str(LABELS), str(REPO)], env={
            **os.environ, "PATH": f"{ghbin}:{os.environ['PATH']}",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for name in ("factory", "factory:needs-info", "factory:needs-human"):
            self.assertTrue(any(line.startswith(f"label create {name} ") for line in lines), name)


class DocsTests(unittest.TestCase):
    def test_runtime_paths_are_ignored(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertIn("/factory/jobs/", lines)
        self.assertIn("/.worktrees/", lines)

    def test_readme_documents_the_human_merge_remit(self):
        text = (REPO / "README.md").read_text()
        for phrase in ("job handoff", "human", "factory/install", "factory/labels"):
            self.assertIn(phrase, text, phrase)

    def test_agents_md_exists_for_project_agents(self):
        text = (REPO / "AGENTS.md").read_text()
        self.assertIn("python3 -m unittest discover -s tests", text)
        self.assertIn("factory/checks.sh", text)
