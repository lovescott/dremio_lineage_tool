"""
Migration inventory builder — produces a per-object tracking matrix as a DataFrame.
"""

import logging

import pandas as pd

from .graph import LineageGraph

log = logging.getLogger(__name__)


def build_migration_inventory(graph: LineageGraph, columns_df: pd.DataFrame) -> pd.DataFrame:
    """Build the migration tracking matrix as a DataFrame."""
    col_counts = (
        columns_df.groupby(["TABLE_SCHEMA", "TABLE_NAME"])
        .size()
        .reset_index(name="column_count")
    ) if not columns_df.empty else pd.DataFrame()

    rows = []
    for nid, node in graph.nodes.items():
        upstream_deps = sorted(graph.upstream[nid])
        downstream_deps = sorted(graph.downstream[nid])

        col_count = 0
        if not col_counts.empty:
            match = col_counts[
                (col_counts["TABLE_SCHEMA"] == node["schema"]) &
                (col_counts["TABLE_NAME"] == node["name"])
            ]
            col_count = int(match["column_count"].values[0]) if not match.empty else 0

        layer = node["layer"] or 0
        if layer >= 3:
            complexity = "HIGH"
        elif layer >= 2:
            complexity = "MEDIUM"
        else:
            complexity = "LOW"

        rows.append({
            "dremio_id": nid,
            "dremio_schema": node["schema"],
            "dremio_object_name": node["name"],
            "object_type": node["type"],
            "dependency_layer": node["layer"],
            "complexity": complexity,
            "upstream_count": len(upstream_deps),
            "downstream_count": len(downstream_deps),
            "upstream_dependencies": " | ".join(upstream_deps),
            "downstream_dependents": " | ".join(downstream_deps),
            "column_count": col_count,
            "has_view_sql": bool(node["view_sql"]),
            # Migration tracking fields (fill in manually)
            "target_catalog": "",
            "target_schema": "",
            "target_object_name": "",
            "target_object_type": "",   # TABLE / VIEW / NOTEBOOK
            "migration_status": "PENDING",
            "sql_translated": "NO",
            "notes": "",
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(["dependency_layer", "dremio_schema", "dremio_object_name"])
    return df
