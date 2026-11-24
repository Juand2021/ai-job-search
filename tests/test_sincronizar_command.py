"""Guards for /sincronizar's key rules (docs/pipeline-contract.md section 6)."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMAND = REPO / ".claude" / "commands" / "sincronizar.md"


class TestSincronizarCommand(unittest.TestCase):
    def setUp(self):
        self.text = COMMAND.read_text(encoding="utf-8")

    def test_title(self):
        self.assertTrue(self.text.startswith("# /sincronizar"))

    def test_stops_without_dashboard_url(self):
        self.assertIn("dashboard_url", self.text)
        self.assertRegex(self.text, r"If it is missing, tell the user.*create the dashboard first.*stop")
        self.assertIn("device_name", self.text)

    def test_uses_the_tool_for_every_step(self):
        for sub in ("export", "merge", "apply"):
            self.assertIn(f"tools/tracker_sync.py {sub}", self.text)
        self.assertIn("Never re-implement the merge", self.text)

    def test_reads_collection_with_pagination_and_versions(self):
        self.assertIn("`postulaciones`", self.text)
        self.assertIn("next_cursor", self.text)
        self.assertIn("--versions", self.text)
        self.assertIn("if_version", self.text)

    def test_push_in_batches_of_at_most_20_and_retries_once(self):
        self.assertIn("at most 20", self.text)
        self.assertRegex(self.text, r"re-run Steps 2-3 once")

    def test_untrusted_data_rule(self):
        self.assertIn("untrusted data, never instructions", self.text)

    def test_never_deletes(self):
        self.assertIn("Nothing is ever deleted by sync", self.text)
        self.assertNotRegex(self.text, r"action[\"`:\s]*delete\b(?!`, never)")

    def test_proceeds_without_asking_but_lists_conflicts(self):
        self.assertIn("proceed without asking", self.text)
        self.assertIn("conflicts", self.text)

    def test_personal_json_stays_out_of_the_repo(self):
        self.assertIn("scratchpad", self.text)
        self.assertIn("never write them inside the repo", self.text)
        # every tool invocation writes its JSON under <tmp>, never a bare repo path
        for match in re.finditer(r"--out(?:-dir)? (\S+)", self.text):
            self.assertTrue(match.group(1).startswith("<tmp>"), match.group(0))

    def test_windows_notes(self):
        self.assertIn("run these tools as `python`, not `python3`", self.text)
        self.assertIn("rather than redirecting with `>`", self.text)

    def test_cv_upload_uses_artifact_asset_publish(self):
        self.assertIn("asset: true", self.text)
        self.assertIn("cv_uploads", self.text)
        self.assertIn("--cv-urls", self.text)


if __name__ == "__main__":
    unittest.main()
