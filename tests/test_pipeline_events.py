import json
import re
from pathlib import Path

import pytest

from tools import pipeline_events as pe

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "pipeline-contract.md"


def test_folder_name_matches_readme_rule_with_accents_folded():
    assert pe.folder_name("Novo Nordisk A/S", "ML Engineer") == "novo_nordisk_as_ml_engineer"
    assert pe.folder_name("Bancolombia", "Analista de Ingeniería") == "bancolombia_analista_de_ingenieria"
    assert pe.folder_name("  ACME  ", "  Dev  ") == "acme_dev"
    with pytest.raises(ValueError):
        pe.folder_name("///", "***")


def test_contract_table_matches_code():
    rows = re.findall(r"^\| `(\w+)` \| ([^|]+) \| `(\w+)` \| (yes|no) \|$", CONTRACT.read_text(encoding="utf-8"), re.M)
    assert [(e, label.strip(), s, f == "yes") for e, label, s, f in rows] == pe.ETAPAS


def test_every_tracker_status_has_a_default_etapa():
    canonical = {"drafted", "applied", "interview", "offer", "hired", "rejected",
                 "no_response", "offer_declined", "withdrawn"}
    assert canonical <= set(pe.STATUS_DEFAULT_ETAPA)
    for status, etapa in pe.STATUS_DEFAULT_ETAPA.items():
        assert pe.ETAPA_STATUS[etapa] == status.replace(" ", "_")


def test_add_is_append_only_and_idempotent(tmp_path):
    ev = pe.make_event("enviada", "postular", "2026-11-24T21:57:00-05:00", "Enviada  por\nportal", "https://x")
    assert ev["status"] == "applied" and ev["detalle"] == "Enviada por portal"
    path = pe.append_event(tmp_path, "Acme", "Dev", ev)
    pe.append_event(tmp_path, "Acme", "Dev", ev)
    later = pe.make_event("prueba_tecnica", "gmail", "2026-11-26T09:00:00-05:00", ref="msg1")
    pe.append_event(tmp_path, "Acme", "Dev", later)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [e["etapa"] for e in pe.read_events(path)] == ["enviada", "prueba_tecnica"]
    assert pe.dump_all(tmp_path) == {"acme_dev": pe.read_events(path)}


@pytest.mark.parametrize("kwargs", [
    {"etapa": "applied", "fuente": "manual"},
    {"etapa": "enviada", "fuente": "linkedin"},
    {"etapa": "enviada", "fuente": "manual", "ts": "2026-11-24T10:00:00"},
    {"etapa": "enviada", "fuente": "manual", "detalle": "x" * 201},
])
def test_bad_input_is_refused(kwargs):
    with pytest.raises(ValueError):
        pe.make_event(**kwargs)


def test_cli_refuses_without_writing(tmp_path, capsys):
    code = pe.main(["add", "--company", "A", "--role", "B", "--etapa", "nope",
                    "--fuente", "manual", "--root", str(tmp_path)])
    assert code == 1
    assert not any(tmp_path.iterdir())


def test_torn_line_does_not_hide_history(tmp_path):
    path = tmp_path / "a_b" / "events.jsonl"
    path.parent.mkdir()
    good = json.dumps(pe.make_event("borrador", "postular", "2026-11-20T10:00:00-05:00"))
    path.write_text(good + "\n{not json\n", encoding="utf-8")
    assert len(pe.read_events(path)) == 1
