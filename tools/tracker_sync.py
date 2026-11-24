#!/usr/bin/env python3
"""Device sync for the application tracker (docs/pipeline-contract.md section 6).

Python never talks to the artifact. `/sincronizar` moves JSON between the
artifact's `db` (collection `postulaciones`) and local files with Claude's
ArtifactData tool; this tool only converts and merges that JSON.

Usage:
  python3 tools/tracker_sync.py export [--tracker job_search_tracker.csv]
      [--apps documents/applications] [--device pc-casa] [--out local.json]
  python3 tools/tracker_sync.py merge --local local.json --remote remote.json|remote_dir/
      [--versions versions.json] [--device pc-casa] [--cv-urls cv_urls.json]
      [--out merge.json] [--out-dir DIR]
  python3 tools/tracker_sync.py apply --merged merge.json|docs.json
      [--tracker ...] [--apps ...] [--out summary.json]

export  prints {doc_id: doc} for every tracker row (contract section 6 shape).
        `updated_at` = the later of the row's latest event `ts` and the tracker
        file's mtime. The CSV has no per-row timestamp, so the file mtime is the
        only local evidence of when a row last changed; it is coarse (an edit to
        any row makes every row look that new), which is why `merge` reports
        every field both sides hold with different non-empty values under
        `conflicts`, so the user sees what the newer side overwrote.
merge   prints {"merged", "push", "pull", "push_writes", "versions",
        "conflicts", "warnings", "cv_uploads"}. `push` / `pull` map doc ids to the
        merged doc for the side that must change. `push_writes` holds ready
        ArtifactData batch entries (chunks of at most 20) carrying `if_version`
        for documents that already exist remotely; the version never enters a
        doc body. `--out-dir` also writes push/<id>.json files and points the
        batch entries at them via `file_path`.
apply   writes merged docs to the tracker CSV and events.jsonl. Given merge's
        full output it applies only `pull`; given a plain {doc_id: doc} map it
        applies all of them. Idempotent: a second run writes nothing.

Remote input: a JSON file {doc_id: doc}, or a directory of <doc_id>.json files
(ArtifactData list `out_dir`, optionally with a `postulaciones/` subfolder). A
doc may be wrapped as {"data": {...}, "version": N}; a bare doc may carry its
version as `_version`; `--versions` supplies {doc_id: version} separately.

Exit 0 on success, 1 on malformed input (nothing written), 2 on usage.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_events import (  # noqa: E402
    ETAPA_STATUS,
    ETAPAS,
    FUENTES,
    MAX_DETALLE,
    STATUS_DEFAULT_ETAPA,
    append_event,
    folder_name,
    read_events,
)

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / "job_search_tracker.csv"
APPLICATIONS = ROOT / "documents" / "applications"
CONFIG = ROOT / "pipeline.config.json"
COLLECTION = "postulaciones"
BATCH_SIZE = 20

HEADER = ["date", "company", "sector", "role", "role_type", "channel", "status",
          "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
          "source", "deadline"]
STRING_FIELDS = ["company", "role", "sector", "role_type", "channel", "contact_person",
                 "source", "deadline", "date", "notes", "cv_file", "cover_letter_file"]
# Free-text fields where a comma would be written unquoted by the prose-driven
# writers (/outcome Step 4): fold it to " - " so the CSV stays naive-split safe.
COMMA_FOLDED = {"company", "role", "sector", "role_type", "channel", "contact_person", "notes"}
SCHEMA = set(STRING_FIELDS) | {"fit_rating", "status", "etapa", "events", "cv_pdf_url",
                               "updated_at", "updated_by"}
META = {"updated_at", "updated_by"}
# Fields that never live in the local copy, so they never make a doc "differ from local".
REMOTE_ONLY = {"cv_pdf_url", "etapa"}
CANONICAL_STATUS = ["drafted", "applied", "interview", "offer", "hired", "rejected",
                    "no_response", "offer_declined", "withdrawn"]
FINAL_STATUS = {s for _, _, s, final in ETAPAS if final}
ETAPA_ORDER = {e: i for i, (e, _, _, _) in enumerate(ETAPAS)}
STATUS_RANK = {"drafted": 0, "applied": 1, "interview": 2, "offer": 3,
               **{s: 4 for s in FINAL_STATUS}}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class SyncError(ValueError):
    """Malformed input: the command exits 1 and writes nothing."""


# ---------------------------------------------------------------- normalizing

def parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def norm_status(value) -> str:
    key = str(value or "").strip().lower().replace(" ", "_")
    return key if key in STATUS_RANK else ""


def norm_string(field: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join(str(value).split())  # no line breaks inside a CSV field
    text = text.replace('"', "'")
    if field in COMMA_FOLDED:
        text = re.sub(r"\s*,\s*", " - ", text)
    return text


def norm_fit(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        try:
            num = float(str(value).strip())
        except ValueError:
            return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return int(num) if num.is_integer() else num


def norm_event(raw, warnings: list[str], where: str) -> dict | None:
    if not isinstance(raw, dict):
        warnings.append(f"{where}: dropped an event that is not an object")
        return None
    ts, etapa = raw.get("ts"), raw.get("etapa")
    if parse_ts(ts) is None or etapa not in ETAPA_STATUS:
        warnings.append(f"{where}: dropped an event with a bad ts or etapa")
        return None
    fuente = raw.get("fuente")
    if fuente not in FUENTES:
        warnings.append(f"{where}: event fuente {str(fuente)[:30]!r} unknown, kept as 'manual'")
        fuente = "manual"
    detalle = " ".join(str(raw.get("detalle") or "").split())[:MAX_DETALLE]
    ref = str(raw.get("ref") or "").strip()
    return {"ts": ts.strip(), "etapa": etapa, "status": ETAPA_STATUS[etapa],
            "fuente": fuente, "detalle": detalle, "ref": ref}


def event_key(ev: dict) -> tuple:
    return (ev["ts"], ev["etapa"], ev["ref"])


def event_sort(ev: dict) -> tuple:
    return (parse_ts(ev["ts"]) or EPOCH, ETAPA_ORDER[ev["etapa"]], ev["ts"])


def norm_doc(doc_id: str, raw, warnings: list[str], side: str) -> dict:
    """Schema-shaped copy of an untrusted doc. Unknown remote keys pass through."""
    if not isinstance(raw, dict):
        raise SyncError(f"{side} doc {doc_id!r} is not a JSON object")
    doc: dict = {}
    for field in STRING_FIELDS:
        doc[field] = norm_string(field, raw.get(field))
    doc["fit_rating"] = norm_fit(raw.get("fit_rating"))
    doc["status"] = norm_status(raw.get("status"))
    etapa = raw.get("etapa")
    doc["etapa"] = etapa if etapa in ETAPA_STATUS else ""
    events = raw.get("events", [])
    if events is None:
        events = []
    if not isinstance(events, list):
        raise SyncError(f"{side} doc {doc_id!r}: events is not a list")
    clean = [e for e in (norm_event(e, warnings, f"{side} {doc_id}") for e in events) if e]
    doc["events"] = sorted(clean, key=event_sort)
    doc["cv_pdf_url"] = norm_string("cv_pdf_url", raw.get("cv_pdf_url"))
    doc["updated_at"] = raw.get("updated_at") if parse_ts(raw.get("updated_at")) else ""
    doc["updated_by"] = norm_string("updated_by", raw.get("updated_by"))
    for key, value in raw.items():
        if key not in SCHEMA and isinstance(key, str) and not key.startswith("_") and key != "version":
            doc[key] = value
    return doc


def is_empty(value) -> bool:
    return value is None or value == "" or value == []


def doc_folder(doc: dict) -> str | None:
    try:
        return folder_name(doc.get("company", ""), doc.get("role", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------- CSV access

class Tracker:
    """The tracker CSV with each data row's raw text kept for verbatim rewrite."""

    def __init__(self, path: Path):
        self.path = path
        self.exists = path.is_file()
        self.bom = False
        self.newline = "\n"
        self.header_raw = ""
        self.header: list[str] = []
        self.rows: list[dict] = []  # {"raw": str, "fields": list[str] | None}
        if self.exists:
            self._load()
        else:
            self.header = list(HEADER)

    def _load(self) -> None:
        data = self.path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            self.bom, data = True, data[3:]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SyncError(f"{self.path}: not UTF-8 ({exc})") from exc
        lines = text.splitlines(keepends=True)
        if not lines:
            self.exists = False
            self.header = list(HEADER)
            return
        if lines[0].endswith("\r\n"):
            self.newline = "\r\n"
        reader = csv.reader(lines)
        consumed = 0
        try:
            for index, fields in enumerate(reader):
                raw = "".join(lines[consumed:reader.line_num])
                consumed = reader.line_num
                if index == 0:
                    self.header_raw = raw
                    self.header = [h.strip() for h in fields]
                    continue
                if fields and len(fields) > len(self.header):
                    raise SyncError(
                        f"{self.path} line {reader.line_num}: {len(fields)} fields for a "
                        f"{len(self.header)}-column header (an unquoted comma?). Fix the row first.")
                self.rows.append({"raw": raw, "fields": fields or None})
        except csv.Error as exc:
            raise SyncError(f"{self.path}: unreadable CSV ({exc})") from exc
        for required in ("company", "role", "status"):
            if required not in self.header:
                raise SyncError(f"{self.path}: header has no {required!r} column")

    def record(self, fields: list[str]) -> dict:
        padded = list(fields) + [""] * (len(self.header) - len(fields))
        return dict(zip(self.header, padded))

    def data_rows(self):
        for index, row in enumerate(self.rows):
            if row["fields"] is None:
                continue
            rec = self.record(row["fields"])
            try:
                doc_id = folder_name(rec.get("company", ""), rec.get("role", ""))
            except ValueError:
                doc_id = None
            yield index, rec, doc_id


def csv_line(fields: list[str], newline: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator=newline).writerow(fields)
    return buf.getvalue()


# ---------------------------------------------------------------- export

def file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def export_docs(tracker_path: Path, apps: Path, device: str) -> dict:
    tracker = Tracker(tracker_path)
    if not tracker.exists:
        return {}
    mtime = file_mtime_iso(tracker_path)
    chosen: dict[str, dict] = {}
    for _, rec, doc_id in tracker.data_rows():
        if doc_id is None:
            print("warning: skipped a tracker row with no company/role", file=sys.stderr)
            continue
        current = chosen.get(doc_id)
        is_open = norm_status(rec.get("status")) not in FINAL_STATUS
        # One doc per folder: an open row (the live application) beats closed ones.
        if current is None or is_open or norm_status(current.get("status")) in FINAL_STATUS:
            chosen[doc_id] = rec
    out = {}
    warnings: list[str] = []
    for doc_id in sorted(chosen):
        rec = chosen[doc_id]
        events = [e for e in (norm_event(e, warnings, f"local {doc_id}")
                              for e in read_events(apps / doc_id / "events.jsonl")) if e]
        events.sort(key=event_sort)
        status = norm_status(rec.get("status"))
        etapa = events[-1]["etapa"] if events else STATUS_DEFAULT_ETAPA.get(status, "")
        updated = mtime
        if events and (parse_ts(events[-1]["ts"]) or EPOCH) > parse_ts(mtime):
            updated = events[-1]["ts"]
        doc = {field: (rec.get(field) or "").strip() for field in STRING_FIELDS}
        doc.update({"fit_rating": norm_fit(rec.get("fit_rating")), "status": status,
                    "etapa": etapa, "events": events, "updated_at": updated,
                    "updated_by": device})
        out[doc_id] = doc
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return out


# ---------------------------------------------------------------- merge

def newer(a: dict, b: dict) -> bool:
    """True when doc a's updated_at is strictly newer than b's."""
    return (parse_ts(a.get("updated_at")) or EPOCH) > (parse_ts(b.get("updated_at")) or EPOCH)


def warn_ahead(doc_id: str, side: str, doc: dict, events: list, warnings: list[str]) -> None:
    if STATUS_RANK.get(doc["status"], -1) > STATUS_RANK[events[-1]["status"]]:
        warnings.append(
            f"{doc_id}: {side} status {doc['status']!r} is ahead of the latest event "
            f"({events[-1]['etapa']}); record that stage with pipeline_events.py add")


def merge_pair(doc_id: str, local: dict, remote: dict, conflicts: dict, warnings: list[str]) -> dict:
    # Ties go to the remote copy, the one every device already sees.
    win, lose = (local, remote) if newer(local, remote) else (remote, local)
    win_side = "local" if win is local else "remote"
    merged: dict = {}

    union: dict[tuple, dict] = {}
    for ev in local["events"] + remote["events"]:  # local copy kept on a key tie
        union.setdefault(event_key(ev), ev)
    events = sorted(union.values(), key=event_sort)
    merged["events"] = events

    if events:
        merged["etapa"] = events[-1]["etapa"]
        merged["status"] = events[-1]["status"]
        for side, doc in (("local", local), ("remote", remote)):
            warn_ahead(doc_id, side, doc, events, warnings)
    else:
        merged["status"] = win["status"] or lose["status"]
        merged["etapa"] = (win["etapa"] if win["status"] else lose["etapa"]) \
            or STATUS_DEFAULT_ETAPA.get(merged["status"], "")

    fields = STRING_FIELDS + ["fit_rating", "cv_pdf_url"]
    extras = sorted((set(local) | set(remote)) - SCHEMA)
    for field in fields + extras:
        a, b = win.get(field), lose.get(field)
        merged[field] = b if is_empty(a) and not is_empty(b) else a
        if field in fields and not is_empty(a) and not is_empty(b) and a != b:
            conflicts.setdefault(doc_id, []).append(
                {"field": field, "local": local.get(field), "remote": remote.get(field),
                 "kept": win_side})
    if not events and local["status"] and remote["status"] and local["status"] != remote["status"]:
        conflicts.setdefault(doc_id, []).append(
            {"field": "status", "local": local["status"], "remote": remote["status"],
             "kept": win_side if win["status"] else ("remote" if win is local else "local")})

    if doc_folder(merged) != doc_id:  # a rename must never move the doc
        merged["company"], merged["role"] = local["company"], local["role"]
    merged["updated_at"] = win["updated_at"] or lose["updated_at"]
    merged["updated_by"] = win["updated_by"] or lose["updated_by"]
    return merged


def content(doc: dict, drop: set, schema_only: bool = False) -> dict:
    """The fields that make two copies differ; an empty value equals an absent one."""
    return {k: v for k, v in doc.items()
            if k not in META and k not in drop and (k in SCHEMA or not schema_only)
            and not is_empty(v)}


def unwrap(raw) -> tuple:
    """(doc body, version) from a bare doc, {"data": doc, "version": N}, or a doc with _version."""
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict) and "company" not in raw:
        return raw["data"], raw.get("version")
    if isinstance(raw, dict):
        return raw, raw.get("_version")
    return raw, None


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"{path}: not readable JSON ({exc})") from exc


def load_remote(path: Path) -> dict:
    if path.is_dir():
        sub = path / COLLECTION
        folder = sub if sub.is_dir() else path
        return {p.stem: load_json(p) for p in sorted(folder.glob("*.json"))}
    data = load_json(path)
    if not isinstance(data, dict):
        raise SyncError(f"{path}: expected an object {{doc_id: doc}}")
    return data


def valid_version(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) >= 1:
        return int(value)
    return None


def merge_docs(local_raw: dict, remote_raw: dict, versions: dict | None = None,
               device: str | None = None, now: str | None = None,
               cv_urls: dict | None = None, repo: Path = ROOT) -> dict:
    if not isinstance(local_raw, dict) or not isinstance(remote_raw, dict):
        raise SyncError("local and remote must both be JSON objects {doc_id: doc}")
    warnings: list[str] = []
    conflicts: dict = {}
    local = {k: norm_doc(k, v, warnings, "local") for k, v in local_raw.items()}
    remote, remote_bodies, remote_versions = {}, {}, {}
    for doc_id, raw in remote_raw.items():
        body, version = unwrap(raw)
        doc = norm_doc(doc_id, body, warnings, "remote")
        if doc_folder(doc) != doc_id:
            warnings.append(f"remote {doc_id}: company/role do not match the doc id; skipped")
            continue
        remote[doc_id], remote_bodies[doc_id] = doc, body
        remote_versions[doc_id] = valid_version((versions or {}).get(doc_id, version))
    for doc_id, doc in local.items():
        if doc_folder(doc) != doc_id:
            raise SyncError(f"local doc {doc_id!r}: company/role do not match the doc id")

    merged: dict = {}
    for doc_id in sorted(set(local) | set(remote)):
        if doc_id in local and doc_id in remote:
            merged[doc_id] = merge_pair(doc_id, local[doc_id], remote[doc_id], conflicts, warnings)
        else:
            merged[doc_id] = dict(local.get(doc_id) or remote[doc_id])
        doc = merged[doc_id]
        if doc["events"]:  # rule 2 holds for one-sided docs too
            for side, other in (("local", local.get(doc_id)), ("remote", remote.get(doc_id))):
                if other is not None and doc_id not in (local.keys() & remote.keys()):
                    warn_ahead(doc_id, side, other, doc["events"], warnings)
            doc["etapa"], doc["status"] = doc["events"][-1]["etapa"], doc["events"][-1]["status"]
        elif not doc["etapa"]:
            doc["etapa"] = STATUS_DEFAULT_ETAPA.get(doc["status"], "")
        url = (cv_urls or {}).get(doc_id)
        if url and not doc.get("cv_pdf_url"):
            doc["cv_pdf_url"] = norm_string("cv_pdf_url", url)

    stamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    push, pull = {}, {}
    for doc_id, doc in merged.items():
        if doc_id not in remote or content(doc, set()) != content(
                {k: v for k, v in remote_bodies[doc_id].items()
                 if not k.startswith("_") and k != "version"}, set()):
            doc_out = dict(doc)
            doc_out["updated_at"] = stamp
            if device:
                doc_out["updated_by"] = device
            push[doc_id] = doc_out
            merged[doc_id] = doc_out
        if doc_id not in local or content(doc, REMOTE_ONLY, True) != content(
                local_raw[doc_id], REMOTE_ONLY, True):
            pull[doc_id] = merged[doc_id]
    for doc_id in push:
        if doc_id in remote and remote_versions.get(doc_id) is None:
            warnings.append(f"{doc_id}: remote version unknown; re-list before writing it")

    uploads = {}
    cv_root = (repo / "cv").resolve()
    for doc_id, doc in merged.items():
        cv_file = doc.get("cv_file", "")
        if doc.get("cv_pdf_url") or not cv_file:
            continue
        pdf = (repo / cv_file).with_suffix(".pdf").resolve()
        if cv_root in pdf.parents and pdf.is_file():
            uploads[doc_id] = str(pdf)

    return {"merged": merged, "push": push, "pull": pull,
            "versions": {k: remote_versions.get(k) for k in push if k in remote},
            "conflicts": conflicts, "warnings": warnings, "cv_uploads": uploads}


def push_writes(result: dict, out_dir: Path | None) -> list[list[dict]]:
    entries = []
    for doc_id, doc in result["push"].items():
        entry = {"op": "set", "collection": COLLECTION, "doc_id": doc_id}
        if out_dir is not None:
            entry["file_path"] = str((out_dir / "push" / f"{doc_id}.json").resolve())
        else:
            entry["data"] = doc
        version = result["versions"].get(doc_id)
        if version is not None:
            entry["if_version"] = version
        entries.append(entry)
    return [entries[i:i + BATCH_SIZE] for i in range(0, len(entries), BATCH_SIZE)]


# ---------------------------------------------------------------- apply

def cell(field: str, doc: dict) -> str:
    value = doc.get(field)
    if field == "fit_rating":
        return "" if value is None else str(value)
    if field == "status":
        return norm_status(value)
    return norm_string(field, value)


def validate_apply_docs(docs) -> dict:
    if not isinstance(docs, dict):
        raise SyncError("merged input must be a JSON object")
    if isinstance(docs.get("merged"), dict) and isinstance(docs.get("pull"), dict) and "push" in docs:
        docs = docs["pull"]
    clean = {}
    for doc_id, raw in docs.items():
        if not isinstance(raw, dict):
            raise SyncError(f"doc {doc_id!r} is not a JSON object")
        if not isinstance(raw.get("company"), str) or not isinstance(raw.get("role"), str):
            raise SyncError(f"doc {doc_id!r} has no company/role")
        if doc_folder(raw) != doc_id:
            raise SyncError(f"doc {doc_id!r}: company/role do not match the doc id")
        if not isinstance(raw.get("events", []), list):
            raise SyncError(f"doc {doc_id!r}: events is not a list")
        warnings: list[str] = []
        doc = norm_doc(doc_id, raw, warnings, "merged")
        if warnings:
            raise SyncError(f"doc {doc_id!r}: {warnings[0]}")
        clean[doc_id] = doc
    return clean


def parse_date(value: str):
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def apply_docs(docs_raw, tracker_path: Path, apps: Path) -> dict:
    docs = validate_apply_docs(docs_raw)
    tracker = Tracker(tracker_path)
    summary = {"updated": [], "appended": [], "kept_final": [], "unchanged": [],
               "events_added": 0, "warnings": [], "backup": None}
    # /apply Step 6b: a legacy 13-column header gains `,deadline` (written only
    # together with a row change, so a no-op apply never touches the file).
    header_changed = tracker.exists and "deadline" not in tracker.header
    if header_changed:
        tracker.header.append("deadline")
    new_rows: list[str] = []
    changed = False

    for doc_id in sorted(docs):
        doc = docs[doc_id]
        matches = [(i, rec) for i, rec, rid in tracker.data_rows() if rid == doc_id]
        open_rows = [(i, rec) for i, rec in matches if norm_status(rec.get("status")) not in FINAL_STATUS]
        if open_rows:
            index, rec = open_rows[-1]
            fields = [rec.get(h, "") for h in tracker.header]
            for pos, col in enumerate(tracker.header):
                if col not in STRING_FIELDS and col not in ("fit_rating", "status"):
                    continue
                new = cell(col, doc)
                current = fields[pos]
                if new == "" and current.strip() != "":
                    continue  # absence is not a correction
                if col == "status" and STATUS_RANK.get(new, -1) < STATUS_RANK.get(norm_status(current), -1):
                    summary["warnings"].append(f"{doc_id}: kept status {current!r}; never moved backwards to {new!r}")
                    continue
                if col == "fit_rating" and norm_fit(current) == norm_fit(new) and new:
                    continue
                if new != current:
                    fields[pos] = new
            old = tracker.rows[index]["fields"]
            old_padded = list(old) + [""] * (len(tracker.header) - len(old))
            if fields != old_padded:
                tracker.rows[index] = {"raw": csv_line(fields, tracker.newline), "fields": fields}
                summary["updated"].append(doc_id)
                changed = True
            else:
                summary["unchanged"].append(doc_id)
        else:
            final_dates = [parse_date(rec.get("date", "")) for _, rec in matches]
            doc_date = parse_date(doc.get("date", ""))
            reapplied = doc["status"] not in FINAL_STATUS and doc_date is not None and all(
                d is not None and doc_date > d for d in final_dates)
            if matches and not reapplied:
                summary["kept_final"].append(doc_id)
            else:
                fields = [cell(col, doc) if (col in STRING_FIELDS or col in ("fit_rating", "status")) else ""
                          for col in tracker.header]
                new_rows.append(csv_line(fields, tracker.newline))
                summary["appended"].append(doc_id)
                changed = True

    pending_events = []
    for doc_id in sorted(docs):
        doc = docs[doc_id]
        have = {(e.get("ts"), e.get("etapa"), e.get("ref", ""))
                for e in read_events(apps / doc_id / "events.jsonl")}
        for ev in doc["events"]:
            if event_key(ev) not in have:
                pending_events.append((doc, ev))

    if changed:
        if tracker.exists:
            backup = tracker_path.with_name(tracker_path.name + ".bak")
            shutil.copy2(tracker_path, backup)
            summary["backup"] = str(backup)
            header = (csv_line(tracker.header, tracker.newline) if header_changed
                      else tracker.header_raw)
        else:
            header = csv_line(tracker.header, tracker.newline)
        body = "".join(r["raw"] for r in tracker.rows)
        text = header if header.endswith(("\n", "\r")) else header + tracker.newline
        text += body
        if new_rows and text and not text.endswith(("\n", "\r")):
            text += tracker.newline
        text += "".join(new_rows)
        atomic_write(tracker_path, text, tracker.bom)

    for doc, ev in pending_events:
        append_event(apps, doc["company"], doc["role"], ev)
        summary["events_added"] += 1
    return summary


def atomic_write(path: Path, text: str, bom: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- CLI

def config_device() -> str | None:
    if CONFIG.is_file():
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        value = data.get("device_name") if isinstance(data, dict) else None
        return value if isinstance(value, str) and value.strip() else None
    return None


def emit(obj, out: Path | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if out is None:
        sys.stdout.write(text)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # a Windows console is cp1252 otherwise
        except (OSError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export")
    p.add_argument("--tracker", type=Path, default=TRACKER)
    p.add_argument("--apps", type=Path, default=APPLICATIONS)
    p.add_argument("--device")
    p.add_argument("--out", type=Path)

    p = sub.add_parser("merge")
    p.add_argument("--local", type=Path, required=True)
    p.add_argument("--remote", type=Path, required=True)
    p.add_argument("--versions", type=Path)
    p.add_argument("--cv-urls", type=Path)
    p.add_argument("--device")
    p.add_argument("--now")
    p.add_argument("--out", type=Path)
    p.add_argument("--out-dir", type=Path)

    p = sub.add_parser("apply")
    p.add_argument("--merged", type=Path, required=True)
    p.add_argument("--tracker", type=Path, default=TRACKER)
    p.add_argument("--apps", type=Path, default=APPLICATIONS)
    p.add_argument("--out", type=Path)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            device = args.device or config_device()
            if not device:
                raise SyncError("no device name: pass --device or set device_name in pipeline.config.json")
            emit(export_docs(args.tracker, args.apps, device), args.out)
        elif args.cmd == "merge":
            if args.now is not None and parse_ts(args.now) is None:
                raise SyncError("--now must be ISO 8601 with an offset")
            versions = load_json(args.versions) if args.versions else None
            cv_urls = load_json(args.cv_urls) if args.cv_urls else None
            for name, value in (("versions", versions), ("cv-urls", cv_urls)):
                if value is not None and not isinstance(value, dict):
                    raise SyncError(f"--{name} must be a JSON object keyed by doc id")
            result = merge_docs(load_json(args.local), load_remote(args.remote), versions,
                                args.device or config_device(), args.now, cv_urls)
            result["push_writes"] = push_writes(result, args.out_dir)
            if args.out_dir is not None:
                push_dir = args.out_dir / "push"
                push_dir.mkdir(parents=True, exist_ok=True)
                for doc_id, doc in result["push"].items():
                    (push_dir / f"{doc_id}.json").write_text(
                        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            emit(result, args.out)
        elif args.cmd == "apply":
            emit(apply_docs(load_json(args.merged), args.tracker, args.apps), args.out)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
