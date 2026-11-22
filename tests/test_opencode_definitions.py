"""Tests for the OpenCode agent, command and project configuration port."""

import json
import unittest

import yaml

from support import REPO

AGENTS = REPO / ".opencode" / "agents"
COMMAND = REPO / ".opencode" / "commands" / "factory.md"
CONFIG = REPO / "opencode.json"

EXPECTED_MODELS = {
    "intake": "anthropic/claude-fable-5-2",
    "spec-writer": "anthropic/claude-opus-5-5",
    "builder": "anthropic/claude-opus-5-5",
    "reviewer-code": "anthropic/claude-sonnet-5-5",
    "reviewer-security": "anthropic/claude-opus-5-5",
    "reviewer-ux": "anthropic/claude-sonnet-5-5",
    "reviewer-ui": "anthropic/claude-haiku-5-5",
    "approver": "anthropic/claude-opus-5-5",
}


def frontmatter(text):
    assert text.startswith("---\n"), "file has no YAML frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def permissions(meta):
    return {(rule["action"], rule.get("resource")): rule["effect"]
            for rule in meta.get("permissions", [])}


class AgentDefinitionsTests(unittest.TestCase):
    def test_all_eight_agents_are_opencode_subagents(self):
        self.assertEqual(
            sorted(p.stem for p in AGENTS.glob("*.md")), sorted(EXPECTED_MODELS)
        )
        for name, model in EXPECTED_MODELS.items():
            meta = frontmatter((AGENTS / f"{name}.md").read_text())
            self.assertEqual(meta.get("mode"), "subagent", name)
            self.assertEqual(meta.get("model"), model, name)
            self.assertTrue(meta.get("description"), name)
            for legacy in ("tools", "hooks", "name", "permission", "prompt"):
                self.assertNotIn(legacy, meta, f"{name} still has {legacy}")

    def test_agent_permissions_match_their_remit(self):
        for name in EXPECTED_MODELS:
            meta = frontmatter((AGENTS / f"{name}.md").read_text())
            rules = permissions(meta)
            self.assertEqual(rules.get(("subagent", "*")), "deny", name)
            self.assertEqual(rules.get(("execute", "*")), "deny", name)
            self.assertEqual(rules.get(("question", "*")), "deny", name)
            self.assertEqual(rules.get(("read", "*")), "allow", name)
        self.assertEqual(
            permissions(frontmatter((AGENTS / "intake.md").read_text())).get(("shell", "*")),
            "deny",
        )
        for name in ("spec-writer", "builder", "reviewer-code", "approver"):
            self.assertEqual(
                permissions(frontmatter((AGENTS / f"{name}.md").read_text())).get(("shell", "*")),
                "allow",
                name,
            )
        for name in ("reviewer-code", "reviewer-security", "reviewer-ux", "reviewer-ui"):
            self.assertEqual(
                permissions(frontmatter((AGENTS / f"{name}.md").read_text())).get(("edit", "*")),
                "deny",
                name,
            )

    def test_no_claude_harness_language_survives(self):
        banned = ("Claude", "CLAUDE", ".claude", "SendMessage", "Agent tool",
                  "subagent_type", "agent_transcript_path")
        for path in list(AGENTS.glob("*.md")) + [COMMAND]:
            text = path.read_text()
            for word in banned:
                self.assertNotIn(word, text, f"{word} found in {path}")


class CommandTests(unittest.TestCase):
    def test_factory_command_uses_the_opencode_subagent_contract(self):
        self.assertTrue(COMMAND.exists())
        text = COMMAND.read_text()
        meta = frontmatter(text)
        self.assertTrue(meta.get("description"))
        self.assertIn("$ARGUMENTS", text)
        for phrase in ("subagent", "sessionID", "job session", "job merge",
                       "Job folder:", "quoted data", "base_branch"):
            self.assertIn(phrase, text, phrase)
        self.assertIn("gh pr merge", text)
        self.assertIn("/factory run", text)

    def test_approver_decision_semantics_match_upstream(self):
        command = COMMAND.read_text()
        approver = (AGENTS / "approver.md").read_text()
        for phrase in ("job merge <id>", "gh pr merge", "APPROVE", "ESCALATE"):
            self.assertIn(phrase, command, phrase)
        self.assertNotIn("job handoff", command)
        self.assertNotIn("human makes the final merge", command)
        self.assertIn("merges the PR with no human looking", approver)
        self.assertIn("runs `gh pr merge`", approver)
        for condition in ("money, access or identity", "deploy, CI or hosting",
                          "database schema", "adds a\n  dependency",
                          "product or business decision"):
            self.assertIn(condition, approver, condition)
        self.assertNotIn("human handoff", approver)

    def test_command_covers_the_full_pipeline(self):
        text = COMMAND.read_text()
        for stage in ("intake", "route", "spec", "build", "gate", "review", "approve"):
            self.assertIn(stage, text, stage)
        self.assertIn("NEEDS-INFO", text)
        self.assertIn("REJECT", text)
        self.assertIn("needs-human", text)
        self.assertIn("WAIT FOR ALL", text)


class ProjectConfigTests(unittest.TestCase):
    def test_opencode_config_is_v2_and_scopes_the_factory(self):
        self.assertTrue(CONFIG.exists())
        config = json.loads(CONFIG.read_text())
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(config["worktree"]["directory"], ".worktrees")
        self.assertEqual(config["model"], "anthropic/claude-sonnet-5-5")
        self.assertTrue(any(rule["action"] == "subagent" for rule in config["permissions"]))

    def test_job_state_machine_has_no_handoff_command(self):
        job = (REPO / "factory" / "bin" / "job").read_text()
        self.assertIn("def cmd_merge(job):", job)
        self.assertIn('"pr", "merge", str(job["pr"]), f"--{CONFIG[\'merge_method\']}"', job)
        self.assertNotIn("cmd_handoff", job)
        self.assertNotIn("job handoff", job)
        self.assertNotIn("alias for handoff", job)

    def test_no_claude_agent_directory_is_left(self):
        self.assertFalse((REPO / ".claude").exists())
