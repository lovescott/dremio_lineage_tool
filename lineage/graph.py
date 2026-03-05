"""
LineageGraph — in-memory directed graph of Dremio objects and their dependencies.
Supports layer assignment (BFS topological sort) and serialization to/from JSON.
"""

import json
import logging
from collections import defaultdict, deque

log = logging.getLogger(__name__)


class LineageGraph:
    def __init__(self):
        # node_id -> metadata dict
        self.nodes: dict[str, dict] = {}
        # upstream edges:  node_id -> set of upstream node_ids
        self.upstream: dict[str, set] = defaultdict(set)
        # downstream edges: node_id -> set of downstream node_ids
        self.downstream: dict[str, set] = defaultdict(set)

    def node_id(self, schema: str, name: str) -> str:
        return f"{schema}.{name}".lower()

    def add_node(self, schema: str, name: str, obj_type: str, view_sql: str = None):
        nid = self.node_id(schema, name)
        self.nodes[nid] = {
            "id": nid,
            "schema": schema,
            "name": name,
            "type": obj_type,
            "view_sql": view_sql or "",
            "layer": None,
        }
        self.upstream.setdefault(nid, set())
        self.downstream.setdefault(nid, set())

    def add_edge(self, upstream_id: str, downstream_id: str):
        """upstream_id feeds into downstream_id."""
        self.upstream[downstream_id].add(upstream_id)
        self.downstream[upstream_id].add(downstream_id)

    def assign_layers(self):
        """
        BFS-based topological layer assignment.
        Layer 0 = no upstream dependencies (physical sources / base tables).
        Layer N = max(upstream layers) + 1.
        """
        in_degree = {nid: len(ups) for nid, ups in self.upstream.items()}

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        for nid in queue:
            self.nodes[nid]["layer"] = 0

        while queue:
            nid = queue.popleft()
            current_layer = self.nodes[nid]["layer"]
            for downstream_id in self.downstream[nid]:
                existing = self.nodes[downstream_id].get("layer")
                new_layer = current_layer + 1
                if existing is None or new_layer > existing:
                    self.nodes[downstream_id]["layer"] = new_layer
                in_degree[downstream_id] -= 1
                if in_degree[downstream_id] == 0:
                    queue.append(downstream_id)

        for nid, node in self.nodes.items():
            if node["layer"] is None:
                node["layer"] = -1  # -1 = cycle/unresolved
                log.warning(f"  Possible circular dependency: {nid}")

    def get_layers(self) -> dict[int, list[str]]:
        layers = defaultdict(list)
        for nid, node in self.nodes.items():
            layers[node["layer"]].append(nid)
        return dict(sorted(layers.items()))

    def to_dict(self) -> dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": [
                {"upstream": u, "downstream": d}
                for d, ups in self.upstream.items()
                for u in ups
            ],
        }

    @classmethod
    def from_json(cls, json_path: str) -> "LineageGraph":
        """Reconstruct a LineageGraph from a previously saved lineage_graph.json."""
        with open(json_path) as f:
            data = json.load(f)

        graph = cls()
        for node in data.get("nodes", []):
            graph.nodes[node["id"]] = node
            graph.upstream.setdefault(node["id"], set())
            graph.downstream.setdefault(node["id"], set())

        for edge in data.get("edges", []):
            u, d = edge["upstream"], edge["downstream"]
            graph.upstream[d].add(u)
            graph.downstream[u].add(d)

        log.info(
            f"Loaded graph from {json_path}: "
            f"{len(graph.nodes)} nodes, {len(data.get('edges', []))} edges."
        )
        return graph
