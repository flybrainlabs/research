#!/usr/bin/env python3
"""Build an explicitly uncalibrated whole-graph model metadata draft.

Predicted neurotransmitter to current-sign mapping is a modeling assumption.
This output must not be used for a paid or scientifically validated campaign.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

from inspect_connectome_weights import registry_ids
from prepare_graph import sha256_file

ANNOTATION_SHA256 = "2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2"
TRANSMITTER_SHA256 = "95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621"
GRAPH_SHA256 = "6c42f6ff8e2198aca17a765acae0475b490abb0169d615e32b71c976f563deb4"
MAGIC = b"FBMD1\x00\x00\x00"

SIGN = {
    "acetylcholine": 1,
    "gaba": -1,
    "histamine": -1,
    "glutamate": 1,  # cell-specific receptors may make this wrong
    "dopamine": 1,   # assumption, not measured excitatory sign
    "octopamine": 1, # assumption
    "serotonin": 1,  # assumption
    "unclear": 1,    # explicitly retained rather than dropping connections
    None: 1,         # no official consensus; explicitly retained
}


def build(annotation: Path, transmitter: Path, registry: Path, graph: Path, output: Path) -> dict:
    if output.exists() or output.with_suffix(".json").exists():
        raise ValueError("output exists; refusing to replace model data")
    if sha256_file(annotation) != ANNOTATION_SHA256 or sha256_file(transmitter) != TRANSMITTER_SHA256:
        raise ValueError("official source object mismatch")
    if sha256_file(graph) != GRAPH_SHA256:
        raise ValueError("anatomical graph root mismatch")
    ids = registry_ids(registry)
    annotations = feather.read_table(annotation, columns=["bodyId", "status", "superclass"], memory_map=True)
    annotations = annotations.filter(pc.is_in(annotations["bodyId"], value_set=pa.array(ids)))
    annotation_map = {row["bodyId"]: row for row in annotations.to_pylist()}
    if len(annotation_map) != len(ids) or any(annotation_map[int(body)]["status"] != "Traced" for body in ids):
        raise ValueError("registry no longer agrees with official annotations")
    predictions = feather.read_table(transmitter, columns=["body", "consensus_nt"], memory_map=True)
    predictions = predictions.filter(pc.is_in(predictions["body"], value_set=pa.array(ids)))
    transmitter_map = {row["body"]: row["consensus_nt"] for row in predictions.to_pylist()}
    if len(transmitter_map) != predictions.num_rows:
        raise ValueError("duplicate neurotransmitter records")
    labels = [transmitter_map.get(int(body)) for body in ids]
    unfamiliar = set(labels) - set(SIGN)
    if unfamiliar:
        raise ValueError(f"new neurotransmitter labels require a reviewed mapping: {sorted(unfamiliar)}")
    signs = bytes(SIGN[label] & 0xff for label in labels)
    vnc = bytes(int((annotation_map[int(body)]["superclass"] or "").startswith("vnc_")) for body in ids)
    # ROI 0 is a named VNC superclass aggregate, not a complete anatomical ROI atlas.
    roi = b"".join(struct.pack("<H", bit) for bit in vnc)
    graph_root = bytes.fromhex(GRAPH_SHA256)
    data = MAGIC + struct.pack("<I", len(ids)) + graph_root + signs + vnc + roi
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    source_root = hashlib.sha256(b"FlyPoW/source-root/v0\x00" + bytes.fromhex(ANNOTATION_SHA256)
        + bytes.fromhex(TRANSMITTER_SHA256) + bytes.fromhex("e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1")).hexdigest()
    config = {
        "state": "UNCALIBRATED_DEV_ONLY",
        "model_version": "lif-point-v0-dev",
        "source_root_sha256": source_root,
        "registry_root_sha256": sha256_file(registry),
        "graph_root_sha256": GRAPH_SHA256,
        "annotation_source_sha256": ANNOTATION_SHA256,
        "transmitter_source_sha256": TRANSMITTER_SHA256,
        "model_neuron_count": len(ids),
        "time_step_us": 1000,
        "leak_divisor": 8,
        "threshold_current_units": 100,
        "reset_current_units": 0,
        "membrane_limit_current_units": 1000000,
        "refractory_steps": 2,
        "synaptic_unit_per_official_weight": 1,
        "synaptic_delay_steps": 1,
        "background_probability_u16": 256,
        "background_current_units": 10,
        "sign_mapping_assumption": {str(key): value for key, value in SIGN.items()},
        "transmitter_label_counts": {str(key): count for key, count in Counter(labels).items()},
        "vnc_group_rule": "official superclass starts with vnc_",
        "vnc_group_count": sum(vnc),
        "roi_readout_0": "same vnc_ superclass aggregate; not all anatomical ROIs",
        "metadata_bytes": len(data),
        "metadata_sha256": hashlib.sha256(data).hexdigest(),
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    config["model_root_sha256"] = hashlib.sha256(b"FlyPoW/model/v0\x00" + data + canonical).hexdigest()
    output.with_suffix(".json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["annotation", "transmitter", "registry", "graph", "output"]:
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.annotation, args.transmitter, args.registry, args.graph, args.output), indent=2))
