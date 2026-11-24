import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD = (ROOT / ".claude" / "commands" / "scrape-navegador.md").read_text(encoding="utf-8")


def test_never_applies_fills_or_logs_in():
    assert "nunca escribas en formularios" in CMD
    assert '"Aplicar"' in CMD and '"Enviar"' in CMD
    assert "nunca inicies sesión" in CMD


def test_pages_are_untrusted_data():
    assert "nunca instrucciones" in CMD
    assert "09-web-research.md" in CMD


def test_robots_and_rate_limits():
    assert "tools/robots_check.py" in CMD
    assert "5 páginas de resultados por empresa" in CMD
    assert "3 por portal" in CMD
    assert "3 segundos" in CMD


def test_linkedin_is_capped_and_stops_on_challenge():
    linkedin = CMD.split("**LinkedIn:**", 1)[1].split("\n", 1)[0]
    assert "condiciones de uso" in linkedin
    assert "3 páginas" in linkedin
    assert "CAPTCHA" in linkedin


def test_dedup_goes_through_scrape_state_with_browser_source():
    assert "tools/scrape_state.py candidates" in CMD
    assert "tools/scrape_state.py store" in CMD
    assert 'source: "browser"' in CMD


def test_scrape_state_accepts_browser_source(tmp_path):
    import argparse
    import contextlib
    import io
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import scrape_state

    state = tmp_path / "job_scraper" / "seen_jobs.json"
    tracker = tmp_path / "tracker.csv"
    results = tmp_path / "r.json"
    job = {"title": "Analista de Datos Junior", "company": "Acme", "url": "https://acme.example/jobs/1",
           "location": "Bogotá", "first_seen": "2026-11-24", "posted_date": None, "deadline": None,
           "employment_type": None, "fit": "high", "status": "new", "portal": "empresa:Acme", "source": "browser"}
    results.write_text(json.dumps([job]), encoding="utf-8")
    args = argparse.Namespace(command="store", results=results, state=state, tracker=tracker)
    with contextlib.redirect_stdout(io.StringIO()):
        assert scrape_state.run(args) == 0
    assert "Analista" in state.read_text(encoding="utf-8")
