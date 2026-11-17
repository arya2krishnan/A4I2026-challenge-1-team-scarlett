#!/usr/bin/env python3
"""Acquire a bounded OpenStreetMap walking-network pilot in the Chicago Loop.

Default saves a small official OSM map extract, nodes/edges, and sample walks to
listed indoor cooling sites. Citywide Overpass access is currently unavailable.
The main OSM editing API is intentionally used for ONE small pilot, not citywide
bulk extraction. Distances cannot establish route safety or wheelchair access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import heapq
import json
import math
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BBOX = (-87.633, 41.872, -87.623, 41.882)  # west, south, east, north
EXCLUDED_HIGHWAYS = {"motorway", "motorway_link", "trunk", "trunk_link", "construction",
                     "proposed", "raceway", "bus_guideway"}
DENIED = {"no", "private"}
SCHEMAS = {
    "walking_network_nodes": [("node_id", "INT64"), ("latitude", "FLOAT64"), ("longitude", "FLOAT64")],
    "walking_network_edges": [("way_id", "INT64"), ("from_node", "INT64"), ("to_node", "INT64"),
                              ("length_m", "FLOAT64"), ("highway", "STRING"), ("surface", "STRING"),
                              ("sidewalk", "STRING"), ("wheelchair", "STRING"), ("oneway_foot", "STRING")],
    "cooling_walk_access_pilot": [("origin_latitude", "FLOAT64"), ("origin_longitude", "FLOAT64"),
                                  ("site_name", "STRING"), ("latitude", "FLOAT64"), ("longitude", "FLOAT64"),
                                  ("network_distance_m", "FLOAT64"), ("connector_distance_m", "FLOAT64"),
                                  ("estimated_walk_minutes", "FLOAT64"), ("walking_speed_m_per_min", "FLOAT64"),
                                  ("status", "STRING"), ("open_for_event", "BOOL")],
}


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def walk_allowed(tags: dict[str, str]) -> bool:
    if tags.get("highway") in EXCLUDED_HIGHWAYS or not tags.get("highway"):
        return False
    if tags.get("foot") in DENIED:
        return False
    return tags.get("access") not in DENIED or tags.get("foot") in {"yes", "designated", "permissive"}


def normalize_network(payload: bytes) -> tuple[list[dict], list[dict]]:
    root = ET.fromstring(payload)
    coords: dict[int, tuple[float, float]] = {}
    blocked: set[int] = set()
    for node in root.findall("node"):
        key = int(node.attrib["id"])
        coords[key] = (float(node.attrib["lat"]), float(node.attrib["lon"]))
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
        if tags.get("foot") in DENIED or (tags.get("access") in DENIED and tags.get("foot") not in {"yes", "designated", "permissive"}):
            blocked.add(key)
    edges: list[dict] = []
    used: set[int] = set()
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if not walk_allowed(tags):
            continue
        refs = [int(node.attrib["ref"]) for node in way.findall("nd")]
        for a, b in zip(refs, refs[1:]):
            if a not in coords or b not in coords or a in blocked or b in blocked:
                continue
            used.update((a, b))
            edges.append({"way_id": int(way.attrib["id"]), "from_node": a, "to_node": b,
                          "length_m": distance_m(coords[a], coords[b]), "highway": tags["highway"],
                          "surface": tags.get("surface"), "sidewalk": tags.get("sidewalk"),
                          "wheelchair": tags.get("wheelchair"), "oneway_foot": tags.get("oneway:foot")})
    nodes = [{"node_id": key, "latitude": coords[key][0], "longitude": coords[key][1]} for key in sorted(used)]
    return nodes, edges


def shortest_paths(edges: list[dict], origin: int) -> dict[int, float]:
    graph: dict[int, list[tuple[int, float]]] = {}
    for edge in edges:
        a, b, weight = edge["from_node"], edge["to_node"], edge["length_m"]
        if edge["oneway_foot"] != "-1":
            graph.setdefault(a, []).append((b, weight))
        if edge["oneway_foot"] not in {"yes", "1", "true"}:
            graph.setdefault(b, []).append((a, weight))
    best: dict[int, float] = {origin: 0.0}
    queue = [(0.0, origin)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > best[node]:
            continue
        for neighbor, weight in graph.get(node, []):
            candidate = cost + weight
            if candidate < best.get(neighbor, math.inf):
                best[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return best


def nearest_node(nodes: list[dict], point: tuple[float, float]) -> tuple[int, float]:
    return min(((row["node_id"], distance_m(point, (row["latitude"], row["longitude"]))) for row in nodes), key=lambda x: x[1])


def cooling_walks(nodes: list[dict], edges: list[dict], facilities: list[dict],
                  origin: tuple[float, float], bbox: tuple[float, ...], speed: float = 60.0) -> list[dict]:
    if speed <= 0 or not math.isfinite(speed):
        raise ValueError("walking speed must be positive and finite")
    if not nodes:
        raise ValueError("no pedestrian-network nodes returned")
    origin_node, origin_snap = nearest_node(nodes, origin)
    paths = shortest_paths(edges, origin_node)
    west, south, east, north = bbox
    rows = []
    for facility in facilities:
        lat, lon = facility["latitude"], facility["longitude"]
        if not facility["is_indoor"] or not (south <= lat <= north and west <= lon <= east):
            continue
        destination, destination_snap = nearest_node(nodes, (lat, lon))
        status = "network_estimate_with_unverified_connectors"
        network = paths.get(destination)
        if max(origin_snap, destination_snap) > 150:
            network, status = None, "unmapped_connector_over_150m"
        elif network is None:
            status = "disconnected_in_pilot_extract"
        connector = origin_snap + destination_snap
        rows.append({"origin_latitude": origin[0], "origin_longitude": origin[1],
                     "site_name": facility["site_name"], "latitude": lat, "longitude": lon,
                     "network_distance_m": network, "connector_distance_m": connector,
                     "estimated_walk_minutes": (network + connector) / speed if network is not None else None,
                     "walking_speed_m_per_min": speed, "status": status, "open_for_event": None})
    return rows


def load_tables(tables: dict[str, list[dict]], project: str, dataset: str, location: str) -> None:
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.schema import SchemaField

    client = Client(project=project, location=location)
    for name, rows in tables.items():
        if not rows:
            continue
        schema = SCHEMAS[name] + [("source", "STRING"), ("retrieved_at", "TIMESTAMP")]
        job = LoadJobConfig(schema=[SchemaField(n, t) for n, t in schema], write_disposition="WRITE_TRUNCATE")
        client.load_table_from_json(rows, f"{project}.{dataset}.{name}", job_config=job).result()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/enrichment/walkability")
    parser.add_argument("--source-xml", type=Path, help="Reuse a previously downloaded OSM map extract")
    parser.add_argument("--facilities-file", type=Path, default=ROOT / "data/enrichment/facilities/cooling_inventory_snapshot.jsonl")
    parser.add_argument("--bbox", type=float, nargs=4, default=BBOX, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--origin", type=float, nargs=2, default=(41.8781, -87.6298), metavar=("LAT", "LON"))
    parser.add_argument("--walking-speed", type=float, default=60.0, help="Metres/minute, default 3.6 km/h")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = parser.parse_args()
    west, south, east, north = args.bbox
    if not (-88 < west < east < -87 and 41.5 < south < north < 42.2) or (east - west) * (north - south) > 0.0004:
        parser.error("use a small Chicago pilot bbox (area <= 0.0004 square degrees); citywide acquisition needs a bulk extract")
    if not (south <= args.origin[0] <= north and west <= args.origin[1] <= east):
        parser.error("origin must lie inside the acquired bbox")
    if not args.facilities_file.exists():
        parser.error("fetch the cooling inventory first, or provide --facilities-file")
    if args.load and not args.project:
        parser.error("--load requires --project or GOOGLE_CLOUD_PROJECT")
    if not math.isfinite(args.walking_speed) or args.walking_speed <= 0:
        parser.error("walking speed must be positive and finite")
    url = "https://api.openstreetmap.org/api/0.6/map?" + urllib.parse.urlencode({"bbox": ",".join(map(str, args.bbox))})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if args.source_xml:
        payload = args.source_xml.read_bytes()
        # Re-normalizing a local file is not a new acquisition.
        previous = args.source_xml.parent / "manifest.json"
        if previous.exists():
            meta = json.loads(previous.read_text())
            retrieved_at, url = meta.get("retrieved_at", retrieved_at), meta.get("source", url)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "heat-dispatch-agent/1.0 (Chicago walking-access pilot)"})
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read()
    (args.output_dir / "map.osm").write_bytes(payload)
    nodes, edges = normalize_network(payload)
    facilities = [json.loads(line) for line in args.facilities_file.read_text().splitlines() if line.strip()]
    walks = cooling_walks(nodes, edges, facilities, tuple(args.origin), tuple(args.bbox), args.walking_speed)
    tables: dict[str, list[dict[str, Any]]] = {"walking_network_nodes": nodes, "walking_network_edges": edges, "cooling_walk_access_pilot": walks}
    for name, rows in tables.items():
        for row in rows:
            row.update({"source": url, "retrieved_at": retrieved_at})
        with (args.output_dir / f"{name}.jsonl").open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, allow_nan=False) + "\n")
    manifest = {"source": url, "retrieved_at": retrieved_at, "sha256": hashlib.sha256(payload).hexdigest(),
                "bbox": args.bbox, "origin": args.origin, "source_bytes": len(payload),
                "row_counts": {name: len(rows) for name, rows in tables.items()},
                "coverage": "Small Loop pilot only; no citywide walking coverage",
                "attribution": "© OpenStreetMap contributors", "license": "ODbL 1.0",
                "terms_url": "https://www.openstreetmap.org/copyright",
                "limitations": ["Shortest paths use the acquired mapped network; paths beyond the bbox may be missing",
                                "Facility and origin connectors are unverified straight-line estimates",
                                "Pedestrian access tags are respected; incomplete tags cannot establish safety or accessibility",
                                "General walking routes include steps; wheelchair routes are not established",
                                "Cooling-site inventory does not confirm the site is open for this event",
                                "Default walking speed is an assumption, not measured resident mobility"]}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    if args.load:
        load_tables(tables, args.project, args.dataset, args.location)
    return 0


if __name__ == "__main__":
    sys.exit(main())
