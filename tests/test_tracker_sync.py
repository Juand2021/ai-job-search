import json
import os
from pathlib import Path

import pytest

from tools import pipeline_events as pe
from tools import tracker_sync as ts

HEADER14 = ",".join(ts.HEADER)
HEADER13 = ",".join(ts.HEADER[:-1])
OLD = "2026-01-01T00:00:00-05:00"
NEW = "2026-11-20T10:00:00-05:00"


def write_tracker(tmp_path, *rows, header=HEADER14, mtime=None, newline="\n"):
    path = tmp_path / "job_search_tracker.csv"
    path.write_bytes((newline.join([header, *rows]) + newline).encode("utf-8"))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def doc(company="Acme", role="Dev", **kw):
    base = {f: "" for f in ts.STRING_FIELDS}
    base.update({"company": company, "role": role, "fit_rating": None, "status": "applied",
                 "etapa": "", "events": [], "updated_at": OLD, "updated_by": "pc-casa"})
    base.update(kw)
    return base


def ev(etapa, when, ref="", fuente="manual"):
    return pe.make_event(etapa, fuente, when, ref=ref)


# ------------------------------------------------------------------ export

def test_export_shape(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,tech,Dev,,portal,applied,,82,hola,cv/main_acme_dev.tex,,https://x,")
    apps = tmp_path / "apps"
    out = ts.export_docs(tracker, apps, "pc-casa")
    assert list(out) == ["acme_dev"]
    d = out["acme_dev"]
    assert set(d) == set(ts.STRING_FIELDS) | {"fit_rating", "status", "etapa", "events", "updated_at", "updated_by"}
    assert d["fit_rating"] == 82 and d["status"] == "applied" and d["etapa"] == "enviada"
    assert d["events"] == [] and d["updated_by"] == "pc-casa"
    assert ts.parse_ts(d["updated_at"]) is not None


def test_export_etapa_and_updated_at_from_latest_event(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,n/a,,,,,", mtime=1_700_000_000)
    apps = tmp_path / "apps"
    pe.append_event(apps, "Acme", "Dev", ev("enviada", "2026-11-01T09:00:00-05:00"))
    pe.append_event(apps, "Acme", "Dev", ev("prueba_tecnica", "2030-01-01T09:00:00-05:00", ref="m1"))
    d = ts.export_docs(tracker, apps, "pc-trabajo")["acme_dev"]
    assert d["etapa"] == "prueba_tecnica"
    assert d["status"] == "applied"  # export keeps the tracker status; merge derives it
    assert d["updated_at"] == "2030-01-01T09:00:00-05:00"
    assert d["fit_rating"] is None
    assert [e["etapa"] for e in d["events"]] == ["enviada", "prueba_tecnica"]


def test_export_legacy_13_columns_and_accents(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Ingeniería Ñandú,,Analista de Datos,,,no response,,70,,,,",
                            header=HEADER13)
    d = ts.export_docs(tracker, tmp_path / "apps", "pc-casa")
    assert list(d) == ["ingenieria_nandu_analista_de_datos"]
    row = d["ingenieria_nandu_analista_de_datos"]
    assert row["company"] == "Ingeniería Ñandú" and row["deadline"] == ""
    assert row["status"] == "no_response" and row["etapa"] == "sin_respuesta"


def test_export_prefers_open_row_over_closed_one(tmp_path):
    tracker = write_tracker(tmp_path,
                            "2026-11-05,Acme,,Dev,,,interview,,,second,,,,",
                            "2025-01-01,Acme,,Dev,,,rejected,,,first,,,,")
    assert ts.export_docs(tracker, tmp_path / "a", "x")["acme_dev"]["notes"] == "second"


def test_export_refuses_overlong_row(tmp_path, capsys):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,,a,b,c,d,e,f")
    assert ts.main(["export", "--tracker", str(tracker), "--apps", str(tmp_path), "--device", "x"]) == 1
    assert "fields" in capsys.readouterr().err


# ------------------------------------------------------------------ merge

def merge(local, remote, **kw):
    return ts.merge_docs(local, remote, now="2026-11-24T12:00:00-05:00", device="pc-casa", **kw)


def test_rule1_events_union_dedup_sorted():
    a, b, c = ev("enviada", "2026-11-01T09:00:00-05:00"), ev("entrevista_rrhh", "2026-11-10T09:00:00-05:00", "m1"), \
        ev("prueba_tecnica", "2026-11-05T09:00:00-05:00", "m2")
    r = merge({"acme_dev": doc(events=[a, b])}, {"acme_dev": doc(events=[b, c])})
    events = r["merged"]["acme_dev"]["events"]
    assert [e["etapa"] for e in events] == ["enviada", "prueba_tecnica", "entrevista_rrhh"]
    # same ts+etapa but a different ref is a different event
    d = ev("enviada", "2026-11-01T09:00:00-05:00", ref="other")
    r = merge({"acme_dev": doc(events=[a])}, {"acme_dev": doc(events=[d])})
    assert len(r["merged"]["acme_dev"]["events"]) == 2


def test_rule2_status_and_etapa_from_latest_event_even_if_older_doc():
    late = ev("oferta", "2026-11-20T09:00:00-05:00")
    local = doc(status="interview", updated_at=NEW, events=[ev("enviada", "2026-11-01T09:00:00-05:00")])
    remote = doc(status="applied", updated_at=OLD, events=[late])
    m = merge({"acme_dev": local}, {"acme_dev": remote})["merged"]["acme_dev"]
    assert (m["status"], m["etapa"]) == ("offer", "oferta")


def test_rule2_status_without_events_newer_wins():
    m = merge({"acme_dev": doc(status="interview", updated_at=NEW)},
              {"acme_dev": doc(status="applied", updated_at=OLD)})
    assert m["merged"]["acme_dev"]["status"] == "interview"
    assert m["merged"]["acme_dev"]["etapa"] == "entrevista_rrhh"
    assert m["conflicts"]["acme_dev"][-1]["field"] == "status"


def test_rule2_warns_when_a_status_is_ahead_of_the_events():
    r = merge({"acme_dev": doc(status="rejected", events=[ev("enviada", OLD)])}, {})
    assert r["merged"]["acme_dev"]["status"] == "applied"
    assert any("ahead of the latest event" in w for w in r["warnings"])


def test_rule3_newer_updated_at_wins_other_fields_and_conflict_listed():
    r = merge({"acme_dev": doc(notes="local note", updated_at=OLD)},
              {"acme_dev": doc(notes="remote note", updated_at=NEW)})
    assert r["merged"]["acme_dev"]["notes"] == "remote note"
    assert r["conflicts"]["acme_dev"] == [
        {"field": "notes", "local": "local note", "remote": "remote note", "kept": "remote"}]
    assert "acme_dev" in r["pull"] and "acme_dev" not in r["conflicts"].get("x", {})


def test_rule3_compares_instants_not_strings():
    # 10:00-05:00 is 15:00Z, later than 14:00Z even though "10" < "14"
    r = merge({"acme_dev": doc(notes="local", updated_at="2026-11-20T10:00:00-05:00")},
              {"acme_dev": doc(notes="remote", updated_at="2026-11-20T14:00:00+00:00")})
    assert r["merged"]["acme_dev"]["notes"] == "local"


def test_rule3_empty_never_overwrites_non_empty():
    r = merge({"acme_dev": doc(deadline="2026-12-01", fit_rating=80, updated_at=OLD)},
              {"acme_dev": doc(deadline="", fit_rating=None, sector="tech", updated_at=NEW)})
    m = r["merged"]["acme_dev"]
    assert (m["deadline"], m["fit_rating"], m["sector"]) == ("2026-12-01", 80, "tech")
    assert "acme_dev" not in r["conflicts"]


def test_rule4_one_sided_docs_copied_with_versions():
    r = merge({"acme_dev": doc()}, {"beta_qa": doc("Beta", "QA", updated_by="dashboard")},
              versions={"beta_qa": 4})
    assert set(r["merged"]) == {"acme_dev", "beta_qa"}
    assert "acme_dev" in r["push"] and "acme_dev" not in r["versions"]
    assert "beta_qa" in r["pull"]
    entries = [e for batch in ts.push_writes(r, None) for e in batch]
    assert {e["doc_id"]: e.get("if_version") for e in entries}["acme_dev"] is None


def test_rule5_nothing_deleted_and_no_spurious_push_or_pull():
    same = doc(events=[ev("enviada", OLD)], etapa="enviada")
    r = merge({"acme_dev": dict(same)}, {"acme_dev": {**same, "updated_at": NEW, "_version": 7}})
    assert r["push"] == {} and r["pull"] == {}
    r = merge({}, {})
    assert r["merged"] == {}


def test_push_writes_carry_if_version_and_chunk_at_20(tmp_path):
    local = {f"c{i}_r": doc(f"C{i}", "R", notes="new", updated_at=NEW) for i in range(25)}
    remote = {k: {**v, "notes": "old", "updated_at": OLD} for k, v in local.items()}
    r = merge(local, remote, versions={k: 2 for k in remote})
    batches = ts.push_writes(r, tmp_path)
    assert [len(b) for b in batches] == [20, 5]
    assert all(e["if_version"] == 2 and e["op"] == "set" and e["collection"] == "postulaciones"
               and "_version" not in r["push"][e["doc_id"]] for b in batches for e in b)
    assert r["push"]["c0_r"]["updated_at"] == "2026-11-24T12:00:00-05:00"
    assert r["push"]["c0_r"]["updated_by"] == "pc-casa"


def test_remote_directory_input_and_version_file(tmp_path):
    folder = tmp_path / "remote" / "postulaciones"
    folder.mkdir(parents=True)
    (folder / "acme_dev.json").write_text(json.dumps(doc(notes="r", updated_at=NEW)), encoding="utf-8")
    (tmp_path / "local.json").write_text(json.dumps({"acme_dev": doc(notes="l")}), encoding="utf-8")
    (tmp_path / "v.json").write_text('{"acme_dev": 9}', encoding="utf-8")
    out = tmp_path / "m.json"
    code = ts.main(["merge", "--local", str(tmp_path / "local.json"), "--remote", str(tmp_path / "remote"),
                    "--versions", str(tmp_path / "v.json"), "--device", "pc-casa", "--out", str(out),
                    "--out-dir", str(tmp_path / "o")])
    assert code == 0
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["merged"]["acme_dev"]["notes"] == "r" and "acme_dev" in r["pull"]


def test_untrusted_remote_docs_are_sanitized():
    bad = doc(notes="a,b\nc \"q\"", status="Hacked", etapa="nope",
              events=[{"ts": "yesterday", "etapa": "enviada"},
                      {"ts": NEW, "etapa": "enviada", "fuente": "evil", "status": "hired", "x": 1}],
              updated_at=NEW)
    r = merge({}, {"acme_dev": bad, "wrong_id": doc("Other", "Co")})
    m = r["merged"]["acme_dev"]
    assert m["notes"] == "a - b c 'q'"
    assert m["events"] == [{"ts": NEW, "etapa": "enviada", "status": "applied", "fuente": "manual",
                            "detalle": "", "ref": ""}]
    assert m["status"] == "applied" and "wrong_id" not in r["merged"]


def test_cv_uploads_only_inside_cv_folder(tmp_path):
    (tmp_path / "cv").mkdir()
    (tmp_path / "cv" / "main_acme_dev.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF")
    r = ts.merge_docs({"acme_dev": doc(cv_file="cv/main_acme_dev.tex"),
                       "beta_qa": doc("Beta", "QA", cv_file="../secret.tex")}, {}, repo=tmp_path)
    assert list(r["cv_uploads"]) == ["acme_dev"]
    r = ts.merge_docs({"acme_dev": doc(cv_file="cv/main_acme_dev.tex")}, {}, repo=tmp_path,
                      cv_urls={"acme_dev": "https://claude.ai/x.pdf"})
    assert r["cv_uploads"] == {} and r["push"]["acme_dev"]["cv_pdf_url"] == "https://claude.ai/x.pdf"


def test_malformed_merge_input_exits_1(tmp_path, capsys):
    (tmp_path / "l.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "r.json").write_text("{not json", encoding="utf-8")
    assert ts.main(["merge", "--local", str(tmp_path / "l.json"), "--remote", str(tmp_path / "r.json")]) == 1
    (tmp_path / "r.json").write_text('{"a_b": 5}', encoding="utf-8")
    (tmp_path / "l.json").write_text("{}", encoding="utf-8")
    assert ts.main(["merge", "--local", str(tmp_path / "l.json"), "--remote", str(tmp_path / "r.json")]) == 1


# ------------------------------------------------------------------ apply

def test_apply_updates_appends_and_is_idempotent(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,portal,applied,,80,hola,cv/main_acme_dev.tex,,,",
                            "2026-10-01,Zeta,,Ops,,,drafted,,,,,,,")
    apps = tmp_path / "apps"
    later = ev("entrevista_rrhh", NEW, ref="m1")
    docs = {"acme_dev": doc(date="2026-11-01", status="interview", events=[later], notes="hola",
                            cv_file="cv/main_acme_dev.tex", channel="portal", fit_rating=80),
            "beta_qa": doc("Béta", "QA", date="2026-11-03")}
    s1 = ts.apply_docs(docs, tracker, apps)
    assert s1["updated"] == ["acme_dev"] and s1["appended"] == ["beta_qa"] and s1["events_added"] == 1
    assert (tmp_path / "job_search_tracker.csv.bak").is_file()
    first = tracker.read_bytes()
    lines = first.decode("utf-8").splitlines()
    assert lines[1] == "2026-11-01,Acme,,Dev,,portal,interview,,80,hola,cv/main_acme_dev.tex,,,"
    assert lines[2] == "2026-10-01,Zeta,,Ops,,,drafted,,,,,,,"  # untouched, order kept
    assert lines[3].startswith("2026-11-03,Béta,")
    os.remove(tmp_path / "job_search_tracker.csv.bak")
    s2 = ts.apply_docs(docs, tracker, apps)
    assert s2["updated"] == [] and s2["appended"] == [] and s2["events_added"] == 0
    assert tracker.read_bytes() == first and not (tmp_path / "job_search_tracker.csv.bak").exists()
    assert len(pe.read_events(apps / "acme_dev" / "events.jsonl")) == 1


def test_apply_legacy_13_column_rows(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,,,,,", "2026-11-02,Keep,,Me,,,applied,,,,,,",
                            header=HEADER13, newline="\r\n")
    ts.apply_docs({"acme_dev": doc(status="interview", deadline="2026-12-01")}, tracker, tmp_path / "a")
    text = tracker.read_bytes().decode("utf-8")
    assert text.split("\r\n")[0] == HEADER14
    assert "2026-11-01,Acme,,Dev,,,interview,,,,,,,2026-12-01\r\n" in text
    assert "2026-11-02,Keep,,Me,,,applied,,,,,,\r\n" in text  # legacy row left verbatim
    # a no-op apply on a legacy file does not touch it
    legacy = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,,,,,", header=HEADER13)
    before = legacy.read_bytes()
    ts.apply_docs({"acme_dev": doc(status="applied")}, legacy, tmp_path / "a")
    assert legacy.read_bytes() == before


def test_apply_never_overwrites_a_final_row(tmp_path):
    tracker = write_tracker(tmp_path, "2026-01-01,Acme,,Dev,,,rejected,,,old,,,,")
    s = ts.apply_docs({"acme_dev": doc(status="rejected", notes="changed", date="2026-01-01")},
                      tracker, tmp_path / "a")
    assert s["kept_final"] == ["acme_dev"]
    assert "2026-01-01,Acme,,Dev,,,rejected,,,old,,,," in tracker.read_text(encoding="utf-8")
    # a stale event-derived open status on the same application does not reopen it
    s = ts.apply_docs({"acme_dev": doc(status="applied", date="2026-01-01")}, tracker, tmp_path / "a")
    assert s["kept_final"] == ["acme_dev"] and s["appended"] == []
    # a later, open re-application is appended alongside; the final row stays
    s = ts.apply_docs({"acme_dev": doc(status="applied", date="2026-11-20")}, tracker, tmp_path / "a")
    assert s["appended"] == ["acme_dev"]
    lines = tracker.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "2026-01-01,Acme,,Dev,,,rejected,,,old,,,," and lines[2].startswith("2026-11-20,Acme")


def test_apply_never_moves_backwards_or_blanks(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,tech,Dev,,,interview,,80,n,,,,2026-12-01")
    s = ts.apply_docs({"acme_dev": doc(status="applied", sector="", fit_rating=None)}, tracker, tmp_path / "a")
    assert "2026-11-01,Acme,tech,Dev,,,interview,,80,n,,,,2026-12-01" in tracker.read_text(encoding="utf-8")
    assert s["warnings"]


def test_apply_accepts_full_merge_output_and_uses_pull_only(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,,,,,,")
    out = {"merged": {"acme_dev": doc(notes="push only"), "beta_qa": doc("Beta", "QA")},
           "push": {"acme_dev": doc(notes="push only")}, "pull": {"beta_qa": doc("Beta", "QA")}}
    s = ts.apply_docs(out, tracker, tmp_path / "a")
    assert s["appended"] == ["beta_qa"] and s["updated"] == []


def test_apply_creates_missing_tracker(tmp_path):
    tracker = tmp_path / "job_search_tracker.csv"
    ts.apply_docs({"acme_dev": doc(date="2026-11-01")}, tracker, tmp_path / "a")
    assert tracker.read_text(encoding="utf-8").splitlines()[0] == HEADER14


@pytest.mark.parametrize("payload", [
    [1],
    {"acme_dev": "x"},
    {"acme_dev": {"role": "Dev"}},
    {"wrong": doc()},
    {"acme_dev": {**doc(), "events": "no"}},
    {"acme_dev": {**doc(), "events": [{"ts": "bad", "etapa": "enviada"}]}},
])
def test_apply_malformed_writes_nothing(tmp_path, payload):
    tracker = write_tracker(tmp_path, "2026-11-01,Acme,,Dev,,,applied,,,,,,,")
    before = tracker.read_bytes()
    (tmp_path / "m.json").write_text(json.dumps(payload), encoding="utf-8")
    code = ts.main(["apply", "--merged", str(tmp_path / "m.json"), "--tracker", str(tracker),
                    "--apps", str(tmp_path / "apps")])
    assert code == 1
    assert tracker.read_bytes() == before
    assert not (tmp_path / "apps").exists() and not (tmp_path / "job_search_tracker.csv.bak").exists()


def test_round_trip_converges(tmp_path):
    tracker = write_tracker(tmp_path, "2026-11-01,Ingeniería SAS,,Dev,,,applied,,80,a,,,,")
    apps = tmp_path / "apps"
    remote = {"ingenieria_sas_dev": doc("Ingeniería SAS", "Dev", notes="a, b", updated_at="2099-01-01T00:00:00+00:00",
                                        events=[ev("entrevista_rrhh", NEW)])}
    r1 = merge(ts.export_docs(tracker, apps, "pc-casa"), remote)
    ts.apply_docs(r1["pull"], tracker, apps)
    r2 = merge(ts.export_docs(tracker, apps, "pc-casa"), r1["push"] or remote)
    assert r2["pull"] == {}
    assert "Ingeniería SAS,,Dev,,,interview,,80,a - b" in tracker.read_text(encoding="utf-8")
