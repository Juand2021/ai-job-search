#!/usr/bin/env python3
"""Stage history for tracked applications (docs/pipeline-contract.md).

Each application keeps an append-only `events.jsonl` in its archive folder,
`documents/applications/<folder>/`. This tool is the only writer, so the folder
rule, the etapa vocabulary and the etapa -> tracker status mapping live in one
place instead of being re-derived in prose by every command.

Usage:
  python3 tools/pipeline_events.py folder --company "Bancolombia" --role "Analista de Datos"
  python3 tools/pipeline_events.py add --company X --role Y --etapa enviada --fuente postular \
      [--ts 2026-11-24T21:57:00-05:00] [--detalle "..."] [--ref URL]
  python3 tools/pipeline_events.py list --company X --role Y
  python3 tools/pipeline_events.py etapa-for-status applied
  python3 tools/pipeline_events.py dump [--root documents/applications]

`dump` prints {folder: [events...]} for every application as JSON, for
/dashboard. Exit 0 on success, 1 on bad input (nothing written), 2 on usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS = ROOT / "documents" / "applications"

# (etapa, UI label, tracker status, final) in funnel order. Keep in sync with
# docs/pipeline-contract.md section 2; tests/test_pipeline_events.py checks it.
ETAPAS: list[tuple[str, str, str, bool]] = [
    ("borrador", "Borrador", "drafted", False),
    ("enviada", "Enviada", "applied", False),
    ("en_revision", "En revisión", "applied", False),
    ("prueba_tecnica", "Prueba técnica", "interview", False),
    ("entrevista_rrhh", "Entrevista RRHH", "interview", False),
    ("entrevista_tecnica", "Entrevista técnica", "interview", False),
    ("entrevista_final", "Entrevista final", "interview", False),
    ("oferta", "Oferta", "offer", False),
    ("contratado", "Contratado", "hired", True),
    ("rechazado", "Rechazado", "rejected", True),
    ("sin_respuesta", "Sin respuesta", "no_response", True),
    ("oferta_rechazada", "Oferta rechazada", "offer_declined", True),
    ("retirada", "Retirada", "withdrawn", True),
]
ETAPA_STATUS = {e: s for e, _, s, _ in ETAPAS}
FUENTES = {"postular", "apply", "outcome", "gmail", "formulario", "manual"}

# Default etapa for a tracker row that has no events.jsonl yet. Legacy space
# spellings are accepted on read, as /outcome requires.
STATUS_DEFAULT_ETAPA = {
    "drafted": "borrador",
    "applied": "enviada",
    "interview": "entrevista_rrhh",
    "offer": "oferta",
    "hired": "contratado",
    "rejected": "rechazado",
    "no_response": "sin_respuesta",
    "no response": "sin_respuesta",
    "offer_declined": "oferta_rechazada",
    "offer declined": "oferta_rechazada",
    "withdrawn": "retirada",
}

MAX_DETALLE = 200


def folder_name(company: str, role: str) -> str:
    """documents/README.md Subfolder naming, after folding accents to ASCII."""
    raw = f"{company}_{role}"
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    name = folded.lower().replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        raise ValueError("company and role contain no letters or digits")
    return name


def _parse_ts(ts: str) -> str:
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError as exc:
        raise ValueError(f"ts is not ISO 8601: {ts!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"ts needs a UTC offset (e.g. -05:00): {ts!r}")
    return parsed.isoformat(timespec="seconds")


def make_event(etapa: str, fuente: str, ts: str | None = None,
               detalle: str = "", ref: str = "") -> dict:
    if etapa not in ETAPA_STATUS:
        raise ValueError(f"unknown etapa {etapa!r}; expected one of {', '.join(ETAPA_STATUS)}")
    if fuente not in FUENTES:
        raise ValueError(f"unknown fuente {fuente!r}; expected one of {', '.join(sorted(FUENTES))}")
    detalle = " ".join((detalle or "").split())
    if len(detalle) > MAX_DETALLE:
        raise ValueError(f"detalle is longer than {MAX_DETALLE} characters")
    stamp = _parse_ts(ts) if ts else datetime.now().astimezone().isoformat(timespec="seconds")
    return {"ts": stamp, "etapa": etapa, "status": ETAPA_STATUS[etapa],
            "fuente": fuente, "detalle": detalle, "ref": (ref or "").strip()}


def read_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line never hides the rest of the history
        if isinstance(obj, dict) and obj.get("etapa") in ETAPA_STATUS:
            events.append(obj)
    events.sort(key=lambda e: str(e.get("ts", "")))
    return events


def append_event(root: Path, company: str, role: str, event: dict) -> Path:
    path = root / folder_name(company, role) / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_events(path)
    key = (event["ts"], event["etapa"], event["ref"])
    if any((e.get("ts"), e.get("etapa"), e.get("ref", "")) == key for e in existing):
        return path  # idempotent: re-running a sync never duplicates history
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def dump_all(root: Path) -> dict[str, list[dict]]:
    if not root.is_dir():
        return {}
    return {p.parent.name: read_events(p) for p in sorted(root.glob("*/events.jsonl"))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("folder", "list"):
        p = sub.add_parser(name)
        p.add_argument("--company", required=True)
        p.add_argument("--role", required=True)
        p.add_argument("--root", type=Path, default=APPLICATIONS)

    p = sub.add_parser("add")
    p.add_argument("--company", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--etapa", required=True)
    p.add_argument("--fuente", required=True)
    p.add_argument("--ts")
    p.add_argument("--detalle", default="")
    p.add_argument("--ref", default="")
    p.add_argument("--root", type=Path, default=APPLICATIONS)

    p = sub.add_parser("etapa-for-status")
    p.add_argument("status")

    p = sub.add_parser("dump")
    p.add_argument("--root", type=Path, default=APPLICATIONS)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "folder":
            print(folder_name(args.company, args.role))
        elif args.cmd == "list":
            path = args.root / folder_name(args.company, args.role) / "events.jsonl"
            print(json.dumps(read_events(path), ensure_ascii=False, indent=2))
        elif args.cmd == "add":
            event = make_event(args.etapa, args.fuente, args.ts, args.detalle, args.ref)
            path = append_event(args.root, args.company, args.role, event)
            print(json.dumps({"path": str(path), "event": event}, ensure_ascii=False))
        elif args.cmd == "etapa-for-status":
            key = args.status.strip().lower()
            if key not in STATUS_DEFAULT_ETAPA:
                raise ValueError(f"unknown tracker status {args.status!r}")
            print(STATUS_DEFAULT_ETAPA[key])
        elif args.cmd == "dump":
            print(json.dumps(dump_all(args.root), ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
