"""Guards for /gmail-sync's Colombian/Spanish extension (pipeline Phase 3).

Pins: Spanish signal phrases per class, LatAm portal/ATS sender domains in
the Step 3 query, the class -> etapa mapping from docs/pipeline-contract.md
section 2, and that stage-history events are appended only in Step 7a
(after approval) with --fuente gmail and the email's date as --ts.
"""
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GMAIL_SYNC = REPO / ".claude" / "commands" / "gmail-sync.md"
sys.path.insert(0, str(REPO / "tools"))
import pipeline_events  # noqa: E402


def section(text, start, end):
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


class TestSpanishGmailSync(unittest.TestCase):
    def setUp(self):
        self.text = GMAIL_SYNC.read_text(encoding="utf-8")
        self.step3 = section(self.text, "## Step 3:", "## Step 4:")
        self.step5 = section(self.text, "## Step 5:", "## Step 6:")
        self.step6 = section(self.text, "## Step 6:", "## Step 7:")
        self.step7a = section(self.text, "### Step 7a:", "## Step 8:")

    def _row(self, table_text, label):
        for line in table_text.splitlines():
            if line.startswith(f"| {label} |"):
                return line
        self.fail(f"no table row for {label!r}")

    def test_spanish_phrases_per_class(self):
        spanish = section(self.step5, "**Spanish phrasing.**", "**Etapa for each class**")
        expected = {
            "Application ack": ["hemos recibido tu postulación"],
            "OA / assessment": ["prueba técnica", "prueba psicotécnica", "assessment"],
            "Interview invite/scheduled": ["lo invitamos a una entrevista",
                                           "agendar una entrevista",
                                           "continuar en el proceso"],
            "Offer extended": ["oferta laboral", "carta oferta"],
            "Rejection": ["no continuará en el proceso",
                          "hemos decidido continuar con otros candidatos",
                          "no fue seleccionado"],
            "Portal status update": ["tu hoja de vida fue vista", "en proceso de selección"],
        }
        for label, phrases in expected.items():
            row = self._row(spanish, label)
            for phrase in phrases:
                self.assertIn(f'"{phrase}"', row, f"{label}: missing {phrase!r}")

    def test_english_phrases_kept(self):
        for phrase in ("we've received your application", "online assessment",
                       "schedule a call", "pleased to offer",
                       "moving forward with other candidates"):
            self.assertIn(phrase, self.step5)

    def test_latam_sender_domains_in_ats_group(self):
        group = re.search(r"\{from:greenhouse\.io[^}]*\}", self.step3)
        self.assertIsNotNone(group, "ATS OR-group not found")
        group = group.group(0)
        for sender in ("computrabajo.com", "elempleo.com", "magneto365.com",
                       "jobs-noreply@linkedin.com", "successfactors.com",
                       "taleo.net", "oraclecloud.com", "workablemail.com",
                       "teamtailor.com",
                       # upstream senders must stay
                       "greenhouse.io", "lever.co", "myworkday.com", "bamboohr.com"):
            self.assertIn(f"from:{sender}", group)
        self.assertNotIn("from:linkedin.com", group,
                         "all of linkedin.com would pull in every LinkedIn notification")

    def test_etapa_mapping(self):
        mapping = section(self.step5, "**Etapa for each class**", "An ack or portal update")
        expected = {
            "Application ack": "enviada",
            "Portal status update": "en_revision",
            "OA / assessment": "prueba_tecnica",
            "Interview invite/scheduled": "entrevista_rrhh",
            "Offer extended": "oferta",
            "Rejection": "rechazado",
        }
        for label, etapa in expected.items():
            row = self._row(mapping, label)
            self.assertIn(f"`{etapa}`", row.split("|")[2], label)
        interview = self._row(mapping, "Interview invite/scheduled")
        self.assertIn("`entrevista_tecnica`", interview)
        self.assertIn("`entrevista_final`", interview)
        for etapa in re.findall(r"`([a-z_]+)`", mapping):
            self.assertIn(etapa, pipeline_events.ETAPA_STATUS, f"unknown etapa {etapa}")

    def test_portal_update_never_moves_tracker_past_applied(self):
        self.assertIn("never moves the tracker past `applied`", self.step5)

    def test_events_only_after_approval(self):
        before_approval = self.text[: self.text.index("## Step 7:")]
        self.assertNotIn("pipeline_events.py add", before_approval)
        self.assertIn("pipeline_events.py add", self.step7a)
        self.assertIn("`tools/pipeline_events.py add` runs only in Step 7a", self.text)
        self.assertIn("Skipped rows get no event", self.step7a)

    def test_event_command_uses_gmail_fuente_and_email_date(self):
        cmd = re.search(r"python3 tools/pipeline_events\.py add [^\n]+", self.step7a).group(0)
        self.assertIn("--fuente gmail", cmd)
        self.assertIn("--ts <email Date header", cmd)
        self.assertIn("--ref <gmail message id>", cmd)
        self.assertIn("--etapa <etapa>", cmd)
        self.assertIn("--detalle", cmd)
        self.assertIn("never the sync time", self.step7a)
        self.assertIn("never a sentence copied from the email", self.step7a)
        self.assertIn("gmail", pipeline_events.FUENTES)

    def test_sincronizar_and_schedule_note(self):
        step10 = section(self.text, "## Step 10:", "## Important Rules")
        self.assertIn("dashboard_url", step10)
        self.assertIn("/sincronizar", step10)
        self.assertIn("scheduled task in the Claude desktop app", step10)
        self.assertIn("Do not create the scheduled task yourself", step10)


if __name__ == "__main__":
    unittest.main()
