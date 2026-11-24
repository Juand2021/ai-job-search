"""Guards for /postular, the one-shot pipeline built on /apply.

The command is a markdown spec (the spec IS the implementation), so these pin
the rules that would break silently: it reuses /apply's steps instead of
forking them, reads its threshold and cover-letter rule from
pipeline.config.json with the contract's defaults, records the `borrador`
stage through tools/pipeline_events.py, and never submits an application.
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POSTULAR = REPO / ".claude" / "commands" / "postular.md"
APPLY = REPO / ".claude" / "commands" / "apply.md"
CONTRACT = REPO / "docs" / "pipeline-contract.md"
GUIDE = REPO / "docs" / "postular.md"
CLAUDE_MD = REPO / "CLAUDE.md"


def section(text, heading):
    """Body of one markdown section, up to the next heading of the same or higher level."""
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    rest = text[start + len(heading):]
    m = re.search(r"^#{1,%d} " % level, rest, re.M)
    return rest[: m.start()] if m else rest


def contract_defaults():
    text = CONTRACT.read_text(encoding="utf-8")
    block = section(text, "## 4. Pipeline settings")
    return json.loads(re.search(r"```json\n(.*?)```", block, re.S).group(1))


class PostularSpec(unittest.TestCase):
    def setUp(self):
        self.text = POSTULAR.read_text(encoding="utf-8")

    def test_title_matches_command_name(self):
        self.assertTrue(self.text.startswith("# /postular"))

    def test_reuses_apply_steps_0_to_6b(self):
        self.assertIn(".claude/commands/apply.md", self.text)
        self.assertIn("Steps 0 through 6b", self.text)
        apply_text = APPLY.read_text(encoding="utf-8")
        for heading in ("## Step 0:", "## Step 1:", "## Step 2:", "### Step 6b:"):
            self.assertIn(heading, apply_text, "postular.md overrides apply.md by step number")
        for heading in (
            "### Override 1 - Step 1",
            "### Override 2 - Step 2",
            "### Override 3 - Step 2",
            "### Override 4 - Step 0",
            "### Override 5 - after Step 6b",
        ):
            self.assertIn(heading, self.text)

    def test_threshold_read_from_config_with_contract_default(self):
        self.assertEqual(contract_defaults()["fit_threshold"], 65)
        self.assertIn("pipeline.config.json", self.text)
        self.assertRegex(self.text, r"\|\s*`fit_threshold`\s*\|\s*`65`\s*\|")
        rule = section(self.text, "### Override 1 - Step 1")
        self.assertIn(">= `fit_threshold`", rule)
        self.assertIn("below `fit_threshold`", rule)
        self.assertIn('Do **not** ask "Should I proceed', rule)

    def test_guard_verdict_other_than_clean_stops(self):
        rule = section(self.text, "### Override 1 - Step 1")
        self.assertIn("posting_guard: clean", rule)
        self.assertIn("anything other than a clean verdict", rule)

    def test_cover_letter_default_when_requested(self):
        self.assertEqual(contract_defaults()["cover_letter"], "when_requested")
        self.assertRegex(self.text, r"\|\s*`cover_letter`\s*\|\s*`when_requested`\s*\|")
        rule = section(self.text, "### Override 2 - Step 2")
        self.assertIn("`when_requested` (default)", rule)
        self.assertIn("only when the posting explicitly asks for one", rule)

    def test_cv_language_follows_posting_with_spanish_headings(self):
        self.assertEqual(contract_defaults()["cv_language"], "posting")
        rule = section(self.text, "### Override 3 - Step 2")
        self.assertIn("`posting` (default)", rule)
        self.assertIn("05-cv-templates.md", rule)
        self.assertIn("Experiencia Profesional", rule)

    def test_blocked_posting_goes_through_browser_and_guard(self):
        rule = section(self.text, "### Override 4 - Step 0")
        for needle in (
            "mcp__Claude_Browser__",
            "mcp__remote-devices__Claude_Browser__",
            "get_page_text",
            "python3 tools/posting_guard.py --in",
            "--text",
            "paste",
        ):
            self.assertIn(needle, rule)

    def test_records_borrador_event_through_the_tool(self):
        rule = section(self.text, "### Override 5 - after Step 6b")
        line = next(l for l in rule.splitlines() if l.startswith("python3 tools/pipeline_events.py add"))
        for flag in ("--company", "--role", "--etapa borrador", "--fuente postular", "--ref"):
            self.assertIn(flag, line)

    def test_borrador_and_postular_are_valid_for_the_tool(self):
        sys.path.insert(0, str(REPO / "tools"))
        try:
            import pipeline_events
        finally:
            sys.path.pop(0)
        self.assertIn("borrador", [e[0] for e in pipeline_events.ETAPAS])
        out = subprocess.run(
            [sys.executable, str(REPO / "tools" / "pipeline_events.py"), "add", "-h"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        self.assertIn("postular", CONTRACT.read_text(encoding="utf-8"))

    def test_never_submits(self):
        self.assertIn("**This command never submits an application.**", self.text)
        rules = section(self.text, "## Important Rules")
        self.assertIn("**Never submit.**", rules)
        self.assertIn("The user clicks submit", rules)
        report = section(self.text, "## Step P2")
        self.assertIn("nunca envía la postulación", report)

    def test_buscar_uses_rank_state_shortlist(self):
        variant = section(self.text, "### Variant: `/postular buscar`")
        self.assertIn("python3 tools/rank_state.py shortlist", variant)
        self.assertIn("Never read that file into the conversation", variant)

    def test_final_report_next_steps(self):
        report = section(self.text, "## Step P2")
        self.assertIn("/outcome <empresa>", report)
        self.assertIn("Fase 5", report)
        self.assertIn("3-line rationale", report)
        end = section(self.text, "### Override 7 - end of run")
        self.assertIn("`rebuild_dashboard`", end)
        self.assertIn("`dashboard_url`", end)
        self.assertIn("/sincronizar", end)


class PostularDocs(unittest.TestCase):
    def test_guide_lists_config_keys_and_examples(self):
        text = GUIDE.read_text(encoding="utf-8")
        for key in ("fit_threshold", "cover_letter", "cv_language", "/postular buscar"):
            self.assertIn(key, text)
        self.assertIn("Nunca envía la postulación", text)

    def test_claude_md_workflow_names_postular_threshold(self):
        text = CLAUDE_MD.read_text(encoding="utf-8")
        workflow = section(text, "## Workflow for New Job Applications")
        self.assertIn("/postular", workflow)
        self.assertIn("fit_threshold", workflow)


if __name__ == "__main__":
    unittest.main()
