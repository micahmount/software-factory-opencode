"""Tests that the repository records the completed OpenCode factory spike."""

import unittest

from support import REPO


class EvidenceDocsTests(unittest.TestCase):
    def test_readme_records_the_end_to_end_spike(self):
        text = (REPO / "README.md").read_text()
        for phrase in (
            "issue #4",
            "PR #5",
            "SMOKE.md",
            "job merge",
            "opencode/big-pickle",
            "- [x] One real issue taken end-to-end",
        ):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("job handoff", text)
        self.assertNotIn("- [ ] One real issue taken end-to-end", text)

    def test_readme_keeps_a_human_in_the_escalation_path_only(self):
        text = (REPO / "README.md").read_text()
        self.assertIn("APPROVE auto-merges", text)
        self.assertIn("ESCALATE parks the job", text)
        self.assertNotIn("A human always makes the final merge call", text)

    def test_design_status_matches_the_landed_port(self):
        text = (REPO / "DESIGN.md").read_text()
        self.assertIn("end-to-end spike complete", text)
        self.assertIn("issue #4 → PR #5", text)
        self.assertNotIn("end-to-end spike pending", text)
        self.assertNotIn("The remaining work is the\nend-to-end spike", text)

    def test_design_records_the_upstream_merge_contract(self):
        for name in ("DESIGN.md", "factory/README.md", "AGENTS.md"):
            text = (REPO / name).read_text()
            self.assertNotIn("job handoff", text, name)
        design = (REPO / "DESIGN.md").read_text()
        self.assertIn("APPROVE auto-merges", design)
        self.assertIn("ESCALATE parks the job", design)
        self.assertIn("gh pr merge", design)

    def test_readme_records_a_real_auto_merge_run(self):
        text = (REPO / "README.md").read_text()
        for phrase in (
            "issue #10",
            "PR #11",
            "AUTO_MERGE_SMOKE.md",
            "job merge 002-add-an-auto-merge",
            "round-1/merge-checks.md",
            "no human merge call",
        ):
            self.assertIn(phrase, text, phrase)

    def test_design_records_a_real_auto_merge_run(self):
        text = (REPO / "DESIGN.md").read_text()
        self.assertIn("issue #10 → PR #11", text)
        self.assertIn("auto-merge path", text)


if __name__ == "__main__":
    unittest.main()
