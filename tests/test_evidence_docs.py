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
            "job handoff",
            "opencode/big-pickle",
            "- [x] One real issue taken end-to-end",
        ):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("- [ ] One real issue taken end-to-end", text)

    def test_design_status_matches_the_landed_port(self):
        text = (REPO / "DESIGN.md").read_text()
        self.assertIn("end-to-end spike complete", text)
        self.assertIn("issue #4 → PR #5", text)
        self.assertNotIn("end-to-end spike pending", text)
        self.assertNotIn("The remaining work is the\nend-to-end spike", text)


if __name__ == "__main__":
    unittest.main()
