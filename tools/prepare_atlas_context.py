"""Build a lightweight, aligned context shell from official MaleCNS ROI meshes.

One shared asset; does not crawl cell types or modify the collector's catalogue.
Requires NumPy (already used by this project's dataset tools).
"""
from __future__ import annotations

import hashlib
import json
import struct
import numpy as np
from prepare_atlas import ROOT, fetch, save_json

BASE = "https://storage.googleapis.com/flyem-male-cns/rois/"
PARTS = [
    ("brain", "Central brain", "fullbrain-major-shells", "1"),
    ("optic-left", "Left optic lobe", "fullbrain-major-shells", "2"),
    ("optic-right", "Right optic lobe", "fullbrain-major-shells", "3"),
    ("vnc", "Ventral nerve cord", "vnc-neuropil-shell-v2", "1"),
]


def simplify_mesh(raw: bytes, grid_nm=4000):
    if len(raw) < 4:
        raise ValueError("Truncated mesh")
    count = struct.unpack_from("<I", raw)[0]
    offset = 4 + count * 12
    if count < 3 or offset > len(raw) or (len(raw)-offset) % 12:
        raise ValueError("Invalid Neuroglancer mesh length")
    xyz = np.frombuffer(raw, dtype="<f4", count=count*3, offset=4).reshape(-1, 3)
    faces = np.frombuffer(raw, dtype="<u4", offset=offset).reshape(-1, 3)
    if not np.isfinite(xyz).all() or not len(faces) or int(faces.max()) >= count:
        raise ValueError("Invalid mesh coordinates or indices")
    _, inverse = np.unique(np.rint(xyz/grid_nm).astype(np.int32), axis=0, return_inverse=True)
    totals = np.bincount(inverse)
    vertices = np.column_stack([np.bincount(inverse, weights=xyz[:,k])/totals for k in range(3)])
    mapped = inverse[faces]
    valid = (mapped[:,0]!=mapped[:,1]) & (mapped[:,1]!=mapped[:,2]) & (mapped[:,0]!=mapped[:,2])
    mapped = mapped[valid]
    _, unique = np.unique(np.sort(mapped, axis=1), axis=0, return_index=True)
    mapped = mapped[np.sort(unique)]
    # Standard legacy NG mesh vertices are nanometers. Existing SWC display
    # files retain coordinates in the dataset's 8 nm voxel space.
    vertices = vertices / 8.0
    return vertices, mapped, count, len(faces)


def build():
    parts = []
    for key, label, root, segment in PARTS:
        metadata_url = BASE+root+"/info"
        metadata = json.loads(fetch(metadata_url))
        prefix = BASE+root+"/"+metadata["mesh"].strip("/")+"/"
        manifest_url = prefix+segment+":0"
        manifest = json.loads(fetch(manifest_url))
        vertices, indices, sources = [], [], []
        offset = 0
        before_vertices = before_faces = 0
        for fragment in manifest["fragments"]:
            if "/" in fragment or ".." in fragment:
                raise ValueError("Unexpected mesh fragment path")
            url = prefix+fragment
            raw = fetch(url)
            xyz, faces, nv, nf = simplify_mesh(raw)
            vertices.append(xyz)
            indices.append(faces+offset)
            offset += len(xyz)
            before_vertices += nv
            before_faces += nf
            sources.append({"url": url, "sha256": hashlib.sha256(raw).hexdigest()})
        xyz, faces = np.concatenate(vertices), np.concatenate(indices)
        parts.append({"key": key, "label": label, "positions": np.round(xyz,3).ravel().tolist(), "indices": faces.ravel().tolist(),
                      "bounds": {"min": xyz.min(axis=0).tolist(), "max": xyz.max(axis=0).tolist()},
                      "original_vertices": before_vertices, "original_triangles": before_faces, "sources": sources,
                      "metadata_source": metadata_url, "manifest_source": manifest_url})
        print(f"{key}: {before_faces:,} → {len(faces):,} triangles", flush=True)
    low = np.min([p["bounds"]["min"] for p in parts], axis=0)
    high = np.max([p["bounds"]["max"] for p in parts], axis=0)
    result = {"schema": "flypow-anatomy-context-v1", "dataset": "male-cns:v1.0", "units": "8 nm voxels",
              "center": ((low+high)/2).tolist(), "extent": float(np.max(high-low)), "parts": parts,
              "license": "CC-BY-4.0", "attribution": "HHMI Janelia FlyEM, Cambridge and Google Research",
              "modifications": "Official ROI meshes vertex-clustered on a 4 micrometer grid and converted from nm to 8 nm voxels. Display context only, not an external fly-body model."}
    destination = ROOT/"web/data/atlas-context.json"
    save_json(destination, result)
    print(json.dumps({"parts": len(parts), "triangles": sum(len(p["indices"])//3 for p in parts), "bytes": destination.stat().st_size}), flush=True)


if __name__ == "__main__":
    build()
