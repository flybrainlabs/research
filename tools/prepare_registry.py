#!/usr/bin/env python3
"""Build a draft MaleCNS v1.0 neuron registry from official body annotations.

This only freezes candidate neuron identity. It does not assert that the full
connectome graph, physiology, or a paid campaign is ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pyarrow.feather as feather

SOURCE_URL = ("https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/"
              "flat-connectome/body-annotations-male-cns-v1.0-minconf-0.5.feather")
SOURCE_SHA256 = "2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2"
REGISTRY_MAGIC = b"FBRG1\x00\x00\x00"
SCOPE_DOMAIN = b"FlyPoW/campaign-scope/v1\x00"


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(source: Path, output: Path) -> dict:
    actual = digest_file(source)
    if actual != SOURCE_SHA256:
        raise ValueError(f"official annotation SHA-256 mismatch: {actual}")
    table = feather.read_table(source, columns=["bodyId", "type", "somaSide", "status"], memory_map=True)
    rows = table.to_pylist()
    selected = [row for row in rows if row["status"] == "Traced"]
    selected.sort(key=lambda row: row["bodyId"])
    ids = [row["bodyId"] for row in selected]
    if len(ids) != len(set(ids)) or any(not isinstance(body, int) or body < 0 for body in ids):
        raise ValueError("duplicate or invalid official body ID")
    pilot = [row for row in selected if row["type"] == "aIPg10"]
    if len(pilot) != 4 or sorted(row["somaSide"] for row in pilot) != ["L", "L", "R", "R"]:
        raise ValueError("aIPg10 membership differs from the expected four cells; review source")
    output.mkdir(parents=True, exist_ok=False)
    registry = output / "neuron-registry-v1.bin"
    h = hashlib.sha256()
    with registry.open("wb") as handle:
        def write(value: bytes):
            handle.write(value)
            h.update(value)
        write(REGISTRY_MAGIC)
        write(struct.pack("<Q", len(selected)))
        for row in selected:
            name = (row["type"] or "").encode("utf-8")
            if len(name) > 65535:
                raise ValueError("type name too long")
            side = {None: 0, "L": 1, "R": 2, "M": 3}.get(row["somaSide"])
            if side is None:
                raise ValueError(f"unknown soma side: {row['somaSide']!r}")
            write(struct.pack("<QBH", row["bodyId"], side, len(name)))
            write(name)
    scope_bytes = SCOPE_DOMAIN + b"".join(struct.pack("<Q", row["bodyId"]) for row in pilot)
    report = {
        "state": "DRAFT_IDENTITY_ONLY",
        "source_url": SOURCE_URL,
        "source_sha256": actual,
        "source_row_count": len(rows),
        "inclusion_rule": "status == Traced; all other status values excluded; null type and side retained",
        "neuron_count": len(selected),
        "excluded_rows": len(rows) - len(selected),
        "missing_type_count": sum(row["type"] is None for row in selected),
        "missing_soma_side_count": sum(row["somaSide"] is None for row in selected),
        "registry_root_sha256": h.hexdigest(),
        "registry_file": registry.name,
        "pilot_type": "aIPg10",
        "pilot_members": [{"body_id": row["bodyId"], "soma_side": row["somaSide"], "model_index": ids.index(row["bodyId"])} for row in pilot],
        "pilot_campaign_scope_root_sha256": hashlib.sha256(scope_bytes).hexdigest(),
        "graph_root": None,
        "model_root": None,
        "task_manifest_root": None,
    }
    (output / "registry-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Official v1.0 body annotations Feather")
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing data is never replaced")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2, ensure_ascii=False))
