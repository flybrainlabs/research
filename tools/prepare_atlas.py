"""Import the public MaleCNS type catalogue and official morphology identities.

This creates an attributed display catalogue, not a synapse-data mirror or a
simulation model. It downloads selected official skeletons and produces local
geometry and thumbnails in batches, without calling agents or an LLM.
"""
from __future__ import annotations

import hashlib
import json
import argparse
import math
import re
import time
import http.client
import ssl
import threading
import email.utils
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin, quote

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = "https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/"
CACHE = ROOT / "data/runtime/atlas-import"
DISPLAY = ROOT / "web/data/atlas"
SWC_URL = "https://www.googleapis.com/storage/v1/b/flyem-male-cns/o/v1.0%2Fsegmentation%2Fskeletons-malecns%2Fskeletons-swc%2F{}.swc?alt=media"
_HTTP = threading.local()
_SSL = ssl.create_default_context()
_LOCK = threading.Lock()
_URL_LOCKS = {}
_HOST_BACKOFF = {}
_HOSTS = {"reiserlab.github.io", "www.googleapis.com", "storage.googleapis.com"}


class SourceUnavailable(RuntimeError):
    pass


def download(url):
    """Bounded public-source GET with reusable TLS connections and backoff."""
    for attempt in range(4):
        target = url
        try:
            for _ in range(4):
                parts = urlsplit(target)
                if parts.scheme != "https" or parts.hostname not in _HOSTS or parts.port not in {None, 443}:
                    raise SourceUnavailable("Unexpected download host")
                while (delay := _HOST_BACKOFF.get(parts.hostname, 0) - time.monotonic()) > 0:
                    time.sleep(min(delay, 1))
                if not hasattr(_HTTP, "connections"):
                    _HTTP.connections = {}
                connection = _HTTP.connections.get(parts.hostname)
                if connection is None:
                    connection = http.client.HTTPSConnection(parts.hostname, timeout=45, context=_SSL)
                    _HTTP.connections[parts.hostname] = connection
                path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~") + ("?" + parts.query if parts.query else "")
                connection.request("GET", path, headers={"User-Agent": "FlyPoW-atlas-import/1.1", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                data = response.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024:
                    raise SourceUnavailable("Display source exceeds import limit")
                if response.status in {301, 302, 303, 307, 308}:
                    target = urljoin(target, response.getheader("Location") or "")
                    continue
                if response.status == 200:
                    return data
                if response.status in {404, 410}:
                    raise SourceUnavailable(f"HTTP {response.status}: {parts.path}")
                if response.status in {429, 503}:
                    retry = response.getheader("Retry-After")
                    wait = 2 ** (attempt + 1)
                    if retry:
                        try:
                            wait = max(wait, float(retry))
                        except ValueError:
                            try:
                                date = email.utils.parsedate_to_datetime(retry)
                                wait = max(wait, (date - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
                            except (ValueError, TypeError):
                                pass
                    with _LOCK:
                        _HOST_BACKOFF[parts.hostname] = max(_HOST_BACKOFF.get(parts.hostname, 0), time.monotonic() + wait)
                if response.status < 500 and response.status != 429:
                    raise SourceUnavailable(f"HTTP {response.status}: {parts.path}")
                raise OSError(f"HTTP {response.status}")
            raise SourceUnavailable("Too many source redirects")
        except SourceUnavailable:
            raise
        except (OSError, http.client.HTTPException) as exc:
            for connection in getattr(_HTTP, "connections", {}).values():
                connection.close()
            _HTTP.connections = {}
            if attempt == 3:
                raise SourceUnavailable(str(exc)) from exc
            time.sleep(2 ** attempt)
    raise SourceUnavailable("Download failed")


def fetch(url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
    with _LOCK:
        lock = _URL_LOCKS.setdefault(url, threading.Lock())
    with lock:
        if cached.exists():
            return cached.read_bytes()
        data = download(url)
        temporary = cached.with_suffix(".partial")
        temporary.write_bytes(data)
        temporary.replace(cached)
        return data


class CatalogueParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self.roi_labels = {}
        self.current = None
        self.name_parts = None
        self.name_tag = None
        self.abbr = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "neuron-card-wrapper" in classes:
            def values(key):
                return [x.strip() for x in (a.get("data-" + key) or "").split(",") if x.strip()]
            self.current = {
                "name": "", "source_path": "", "count": int(a["data-cell-count"]),
                "sides": {k: int(a.get("data-" + k + "-count") or 0) for k in ["left", "right", "middle", "undefined"]},
                "rois": values("rois"), "regions": values("region"),
                "nt": values("nt"), "superclass": values("superclass"),
                "class": values("class"), "subclass": values("subclass"),
                "dimorphism": values("dimorphism"), "neuromere": values("soma-neuromere"),
                "hemilineage": values("truman-hl"), "synonyms": values("synonyms"),
                "flywire_types": values("flywire-types"),
            }
            self.entries.append(self.current)
        if ("neuron-name-link" in classes or "neuron-name" in classes) and self.current is not None:
            if tag == "a":
                self.current["source_path"] = a.get("href", "")
            self.name_parts = []
            self.name_tag = tag
        if tag == "a" and "soma-link" in classes and self.current is not None and not self.current["source_path"]:
            self.current["source_path"] = a.get("href", "")
        if tag == "abbr" and a.get("title"):
            self.abbr = [a["title"], []]

    def handle_data(self, text):
        if self.name_parts is not None:
            self.name_parts.append(text)
        if self.abbr is not None:
            self.abbr[1].append(text)

    def handle_endtag(self, tag):
        if tag == self.name_tag and self.name_parts is not None:
            self.current["name"] = "".join(self.name_parts).strip()
            self.name_parts = None
            self.name_tag = None
        if tag == "abbr" and self.abbr is not None:
            self.roi_labels["".join(self.abbr[1]).strip()] = self.abbr[0]
            self.abbr = None


class DetailParser(HTMLParser):
    """Read text only; never execute or reuse a source page's scripts/markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = {}
        self.table = None
        self.row = None
        self.cell = None
        self.head = False
        self.stats = []
        self.stat = None
        self.capture = None
        self.div_depth = 0

    def finish_cell(self):
        if self.cell is not None and self.row is not None:
            self.cell["text"] = " ".join(self.cell.pop("parts")).strip()
            self.cell["text"] = re.sub(r"\s+", " ", self.cell["text"])
            self.row.append(self.cell)
        self.cell = None

    def finish_row(self):
        self.finish_cell()
        if self.row and self.table is not None:
            if self.head:
                self.table["headers"] = [c["text"] for c in self.row]
            else:
                self.table["rows"].append(self.row)
        self.row = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "div":
            self.div_depth += 1
            if "stat-card" in classes:
                self.stat = {"depth": self.div_depth, "value": [], "label": []}
            if self.stat is not None:
                if "stat-number" in classes:
                    self.capture = (self.div_depth, "value")
                if "stat-label" in classes:
                    self.capture = (self.div_depth, "label")
        if tag == "table":
            table_id = a.get("id")
            if table_id in {"roi-table", "upstream-table", "downstream-table"}:
                self.table = {"headers": [], "rows": []}
                self.tables[table_id] = self.table
        if self.table is not None:
            if tag in {"thead", "tbody"}:
                self.finish_row()
                self.head = tag == "thead"
            elif tag == "tr":
                self.finish_row()
                self.row = []
            elif tag in {"th", "td"}:
                self.finish_cell()
                self.cell = {"parts": [], "hint": a.get("title") or ""}
            elif tag == "a" and self.cell is not None:
                path = a.get("href") or ""
                if path.endswith(".html") and ":" not in path and ".." not in path:
                    self.cell["source_path"] = "types/" + path.removeprefix("types/")

    def handle_data(self, text):
        if self.cell is not None:
            self.cell["parts"].append(text)
        if self.stat is not None and self.capture is not None:
            self.stat[self.capture[1]].append(text)

    def handle_endtag(self, tag):
        if tag == "div":
            if self.capture is not None and self.capture[0] == self.div_depth:
                self.capture = None
            if self.stat is not None and self.stat["depth"] == self.div_depth:
                self.stats.append({k: " ".join(self.stat[k]).strip() for k in ["value", "label"]})
                self.stat = None
            self.div_depth -= 1
        if tag in {"td", "th"}:
            self.finish_cell()
        if tag == "tr":
            self.finish_row()
        if tag == "table":
            self.finish_row()
            self.table = None
            self.head = False


def parse_swc(text):
    nodes = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 7:
            raise ValueError("Malformed SWC row")
        node_id, parent = int(parts[0]), int(parts[6])
        xyz = [float(v) for v in parts[2:5]]
        if node_id in nodes or not all(math.isfinite(v) for v in xyz):
            raise ValueError("Invalid SWC identity or coordinates")
        nodes[node_id] = (xyz, parent)
    if len(nodes) < 2 or len(nodes) > 300000:
        raise ValueError("SWC node count outside display limits")
    points = [p for p, _ in nodes.values()]
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    center = [(a + b) / 2 for a, b in zip(low, high)]
    span = max(b - a for a, b in zip(low, high))
    if span <= 0:
        raise ValueError("Skeleton has no spatial extent")
    def transform(p):
        return [round((p[0]-center[0])/span*2, 5), round(-(p[2]-center[2])/span*2, 5), round((p[1]-center[1])/span*2, 5)]
    segments = []
    for p, parent in nodes.values():
        if parent >= 0:
            if parent not in nodes:
                raise ValueError("Missing SWC parent")
            segments.extend(transform(p) + transform(nodes[parent][0]))
    if not segments:
        raise ValueError("Skeleton has no edges")
    return {"nodes": len(nodes), "edges": len(segments)//6, "positions": segments, "source_center": center, "source_extent": span,
            "transform": "Centered and uniformly scaled; axes x,-z,y; original SWC retained at official URL"}


def thumbnail(geometry, name):
    coords = geometry["positions"]
    projected = []
    for i in range(0, len(coords), 3):
        x, y, z = coords[i:i+3]
        projected.append((x*.94+z*.342, y*.985-z*.174))
    xmin, xmax = min(p[0] for p in projected), max(p[0] for p in projected)
    ymin, ymax = min(p[1] for p in projected), max(p[1] for p in projected)
    scale = min(540/max(xmax-xmin, .01), 300/max(ymax-ymin, .01))
    project = lambda p: (320+(p[0]-(xmin+xmax)/2)*scale, 190-(p[1]-(ymin+ymax)/2)*scale)
    commands = []
    for i in range(0, len(projected), 2):
        a, b = project(projected[i]), project(projected[i+1])
        commands.append(f"M{a[0]:.1f},{a[1]:.1f}L{b[0]:.1f},{b[1]:.1f}")
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400" role="img"><title>{escape(name)} — real representative neuron skeleton</title><path d="{"".join(commands)}" fill="none" stroke="#dfdfdf" stroke-opacity=".76" stroke-width="1.05" stroke-linecap="round"/></svg>'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def collect_entry(entry):
    entry = dict(entry)
    key = hashlib.sha256(entry["source_path"].encode()).hexdigest()[:16]
    detail_path = DISPLAY / "details" / (key + ".json")
    if detail_path.exists():
        old = json.loads(detail_path.read_text())
        cached_entry = old.get("entry", {})
        required = [ROOT/"web"/cached_entry.get(k, "missing").removeprefix("/assets/") for k in ["thumbnail", "geometry"]]
        if old.get("schema") == "flypow-atlas-detail-v1" and all(p.is_file() for p in required):
            cached_geometry = json.loads(required[1].read_text())
            if "source_center" in cached_geometry:
                return cached_entry
    resolved_path = entry["source_path"]
    try:
        source = fetch(CATALOGUE + resolved_path)
    except SourceUnavailable as exc:
        if not str(exc).startswith(("HTTP 404", "HTTP 410")):
            raise
        source = None
        for alternative in entry.get("source_alternatives", []):
            path = alternative["path"]
            if path == entry["source_path"] or not path.startswith("types/") or not path.endswith(".html") or ".." in path:
                continue
            try:
                candidate = fetch(CATALOGUE + path)
                identity = re.search(r'currentNeuronType\s*:\s*"([^"]*)"', candidate.decode("utf-8"))
                if identity is None or identity.group(1) != entry["name"]:
                    continue
                source = candidate
                resolved_path = path
                entry["source_scope"] = alternative["scope"]
                entry["resolved_source_path"] = path
                break
            except SourceUnavailable:
                continue
        if source is None:
            raise exc
    html = source.decode("utf-8")
    parser = DetailParser()
    parser.feed(html)
    match = re.search(r"visibleNeurons\s*:\s*(\[[^\]]*\])", html)
    body_ids = [str(v) for v in json.loads(match.group(1))] if match else []
    body_ids = [v for v in body_ids if v.isdigit()]
    if not body_ids:
        raise ValueError("Source page has no representative body IDs")
    failures = []
    geometry = None
    for body in body_ids[:4]:
        try:
            swc = fetch(SWC_URL.format(body))
            geometry = parse_swc(swc.decode("utf-8"))
            geometry.update({"body_id": body, "source": SWC_URL.format(body), "source_sha256": hashlib.sha256(swc).hexdigest(), "license": "CC-BY-4.0"})
            break
        except Exception as exc:
            failures.append(str(exc))
    if geometry is None:
        raise ValueError("No usable official skeleton: " + "; ".join(failures))
    entry.update({"id": key, "body_ids": body_ids, "representative_body": geometry["body_id"],
                  "geometry": f"/assets/data/atlas/geometry/{key}.json", "thumbnail": f"/assets/data/atlas/thumbs/{key}.svg",
                  "detail": f"/assets/data/atlas/details/{key}.json", "skeleton_source": geometry["source"]})
    save_json(DISPLAY/"geometry"/(key+".json"), geometry)
    (DISPLAY/"thumbs").mkdir(parents=True, exist_ok=True)
    (DISPLAY/"thumbs"/(key+".svg")).write_text(thumbnail(geometry, entry["name"]), encoding="utf-8")
    save_json(detail_path, {"schema": "flypow-atlas-detail-v1", "entry": entry, "stats": parser.stats,
                           "tables": parser.tables, "source": CATALOGUE+resolved_path,
                           "source_sha256": hashlib.sha256(source).hexdigest(), "collected_at": int(time.time())})
    return entry


def build(limit=20, workers=3, progress_every=100, only=None):
    source_html = fetch(CATALOGUE + "types.html")
    source_index = fetch(CATALOGUE + "data/neurons.json")
    parser = CatalogueParser()
    parser.feed(source_html.decode("utf-8"))
    index = json.loads(source_index)
    canonical_names = {unquote(path): row["name"] for row in index["neurons"] for path in row["urls"].values()}
    source_pages = {row["name"]: row["urls"] for row in index["neurons"]}
    for entry in parser.entries:
        entry["name"] = canonical_names.get(unquote(entry["source_path"].removeprefix("types/")), entry["name"])
        if not entry["name"]:
            raise ValueError("Source type has no canonical name")
        entry["source_alternatives"] = [{"scope": scope, "path": "types/"+path} for scope, path in source_pages.get(entry["name"], {}).items()]
    assert len(parser.entries) == index["metadata"]["total_types"]
    for entry in parser.entries:
        if not entry["source_path"].startswith("types/") or not entry["source_path"].endswith(".html"):
            raise ValueError("Unexpected type source path")
    selection = parser.entries[:limit] if limit else parser.entries
    if only:
        selection = [e for e in parser.entries if e["name"] in set(only)]
        if {e["name"] for e in selection} != set(only):
            raise ValueError("An explicitly requested type is not in the source catalogue")
    destination = ROOT / "web/data/atlas.json"
    existing = json.loads(destination.read_text()) if destination.exists() else {}
    completed = {e["source_path"]: e for e in existing.get("entries", [])}
    errors = []
    result = {
        "schema": "flypow-neuron-atlas-v1", "dataset": "male-cns:v1.0",
        "generated": index["metadata"]["generated"], "count": len(completed), "source_total": len(parser.entries),
        "source": CATALOGUE,
        "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Reiser Lab Cell Type Explorer; HHMI Janelia FlyEM, Cambridge and Google Research",
        "modifications": "Catalogue normalized for filtering and bilingual display; skeletons rendered as previews. Not a simulation.",
        "source_sha256": {"types_html": hashlib.sha256(source_html).hexdigest(), "index": hashlib.sha256(source_index).hexdigest()},
        "roi_labels": parser.roi_labels, "entries": [], "collection_errors": errors,
    }
    started = time.monotonic()
    finished = 0
    last_saved = started
    def checkpoint(phase):
        nonlocal last_saved
        last_saved = time.monotonic()
        result["count"] = len(completed)
        result["entries"] = sorted(completed.values(), key=lambda e:e["name"].casefold())
        result["partial_source_count"] = sum(bool(e.get("source_scope")) for e in completed.values())
        save_json(destination, result)
        progress = {"phase": phase, "collected": len(completed), "finished": finished, "requested": len(selection),
                    "source_total": len(parser.entries), "failed": len(errors), "partial_sources": result["partial_source_count"], "coverage_complete": len(completed)==len(parser.entries), "elapsed_seconds": round(last_saved-started), "updated_at": int(time.time())}
        save_json(CACHE/"progress.json", progress)
        save_json(CACHE/"failures.json", errors)
        print(json.dumps(progress), flush=True)
    checkpoint("running")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(collect_entry, e): e for e in selection}
        for future in as_completed(jobs):
            entry = jobs[future]
            try:
                done = future.result()
                completed[done["source_path"]] = done
            except Exception as exc:
                errors.append({"name": entry["name"], "source_path": entry["source_path"], "error": str(exc)})
            finished += 1
            if finished % progress_every == 0 or time.monotonic()-last_saved >= 45:
                checkpoint("running")
    checkpoint("complete" if not errors else "partial")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    group = cli.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, default=20, help="Collect the first N source types; default 20. Existing collected types are retained.")
    group.add_argument("--all", action="store_true", help="Collect all source types. Can download many GB; resumes from the local cache.")
    group.add_argument("--only", nargs="+", help="Retry or collect named source types only; retain the rest of the catalogue")
    cli.add_argument("--workers", type=int, default=3, choices=range(1,7), help="Bounded parallel downloads (1–6)")
    cli.add_argument("--progress-every", type=int, default=100, help="Save the live catalogue and print a summary every N finished types (also at least every 45 seconds while progressing)")
    args = cli.parse_args()
    if args.limit < 1:
        cli.error("--limit must be positive")
    if args.progress_every < 1:
        cli.error("--progress-every must be positive")
    # One producer owns the catalogue; parallel collectors must not race writes.
    import fcntl
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE/"collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            cli.error("An atlas collector is already running")
        build(0 if args.all else args.limit, args.workers, args.progress_every, args.only)
