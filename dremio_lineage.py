"""
dremio_lineage.py — entry point.

Extracts table/view inventory, dependency lineage, and migration metadata
from Dremio using INFORMATION_SCHEMA queries + REST API lineage graph.
Generates static PNG and interactive HTML visualizations via networkx + pyvis.

Outputs:
  - lineage_graph.json          : Full dependency graph (nodes + edges)
  - migration_inventory.csv     : Per-object migration tracking matrix
  - dependency_layers.json      : Objects bucketed by migration layer (0, 1, 2, ...)
  - lineage_full.png            : Static full-graph PNG (matplotlib + networkx)
  - lineage_layered.png         : Layered hierarchy PNG highlighting migration order
  - lineage_critical_paths.png  : Subgraph of highest-depth dependency chains
  - lineage_interactive.html    : Interactive pan/zoom/hover graph (pyvis)

Usage:
  python dremio_lineage.py --host https://your-dremio-host \\
                           --user admin \\
                           --password secret \\
                           --space "your_space_name"   # optional filter

  # Skip Dremio connection — visualize from a previously saved lineage_graph.json:
  python dremio_lineage.py --from-json ./lineage_output/lineage_graph.json \\
                           --out ./lineage_output
"""

import os
import json
import argparse
import logging

from lineage.client import DremioConfig
from lineage.inventory import fetch_inventory, fetch_columns
from lineage.parser import extract_references_sqlglot
from lineage.graph import LineageGraph
from lineage.migration import build_migration_inventory
from lineage.visualize import generate_visualizations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _enrich_with_api_lineage(cfg: DremioConfig, graph: LineageGraph):
    """
    For each view node, call /catalog/{id}/graph to get Dremio-native lineage
    and add any edges not already captured via SQL parsing.
    """
    log.info("Enriching lineage via Dremio REST API ...")
    enriched = 0
    for nid, node in graph.nodes.items():
        if node["type"] != "VIEW":
            continue

        path = node["schema"].replace(".", "/") + "/" + node["name"]
        entity = cfg.get_catalog_entity(path)
        dataset_id = entity.get("id")
        if not dataset_id:
            continue

        lineage_data = cfg.get_lineage(dataset_id)
        for parent in lineage_data.get("parents", []):
            parent_path = ".".join(parent.get("path", []))
            parent_id   = parent_path.lower()
            if parent_id and parent_id != nid:
                if parent_id not in graph.nodes:
                    graph.add_node(
                        schema=".".join(parent.get("path", [])[:-1]),
                        name=parent.get("path", ["unknown"])[-1],
                        obj_type=parent.get("type", "UNKNOWN"),
                    )
                graph.add_edge(parent_id, nid)
                enriched += 1

    log.info(f"  Added {enriched} edges from REST API lineage.")


def main():
    parser = argparse.ArgumentParser(description="Dremio lineage extractor + visualizer")
    parser.add_argument("--host",     default=None, help="Dremio base URL, e.g. https://dremio.company.com")
    parser.add_argument("--user",     default=None, help="Dremio username")
    parser.add_argument("--password", default=None, help="Dremio password")
    parser.add_argument("--space",    default=None, help="Optional: filter to a specific Space name")
    parser.add_argument("--out",      default=".",  help="Output directory (default: current dir)")
    parser.add_argument("--skip-api-lineage", action="store_true",
                        help="Skip REST API lineage enrichment (SQL parsing only)")
    parser.add_argument("--skip-viz", action="store_true",
                        help="Skip all visualizations (faster, data outputs only)")
    parser.add_argument("--from-json", default=None,
                        help="Load from an existing lineage_graph.json and skip Dremio connection")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # -----------------------------------------------------------------------
    # Mode A: Re-render visualizations from a saved JSON (no Dremio needed)
    # -----------------------------------------------------------------------
    if args.from_json:
        log.info(f"Offline mode — loading from {args.from_json}")
        graph = LineageGraph.from_json(args.from_json)
        if not args.skip_viz:
            generate_visualizations(graph, args.out)
        print(f"\n  Visualizations written to: {args.out}/")
        return

    # -----------------------------------------------------------------------
    # Mode B: Full extraction from Dremio
    # -----------------------------------------------------------------------
    if not all([args.host, args.user, args.password]):
        parser.error("--host, --user, and --password are required unless --from-json is used.")

    cfg = DremioConfig(args.host, args.user, args.password)
    cfg.authenticate()

    inventory_df = fetch_inventory(cfg, args.space)
    columns_df   = fetch_columns(cfg, args.space)

    log.info("Building lineage graph from SQL parsing ...")
    graph = LineageGraph()

    for _, row in inventory_df.iterrows():
        graph.add_node(
            schema=row["TABLE_SCHEMA"],
            name=row["TABLE_NAME"],
            obj_type=row["TABLE_TYPE"],
            view_sql=row.get("VIEW_DEFINITION") or "",
        )

    view_rows = inventory_df[inventory_df["TABLE_TYPE"] == "VIEW"]
    log.info(f"  Parsing SQL for {len(view_rows)} views ...")
    for _, row in view_rows.iterrows():
        downstream_id = graph.node_id(row["TABLE_SCHEMA"], row["TABLE_NAME"])
        refs = extract_references_sqlglot(row.get("VIEW_DEFINITION") or "")
        for ref in refs:
            if ref in graph.nodes:
                graph.add_edge(ref, downstream_id)
            else:
                parts  = ref.rsplit(".", 1)
                schema = parts[0] if len(parts) == 2 else "EXTERNAL"
                name   = parts[-1]
                graph.add_node(schema=schema, name=name, obj_type="EXTERNAL")
                graph.add_edge(ref, downstream_id)

    if not args.skip_api_lineage:
        try:
            _enrich_with_api_lineage(cfg, graph)
        except Exception as e:
            log.warning(f"REST API lineage enrichment failed (continuing): {e}")

    log.info("Assigning dependency layers ...")
    graph.assign_layers()

    layers = graph.get_layers()
    log.info("Layer summary:")
    for layer, nodes in layers.items():
        label = "UNRESOLVED/CYCLE" if layer == -1 else f"Layer {layer}"
        log.info(f"  {label}: {len(nodes)} objects")

    graph_path = os.path.join(args.out, "lineage_graph.json")
    with open(graph_path, "w") as f:
        json.dump(graph.to_dict(), f, indent=2)
    log.info(f"Wrote: {graph_path}")

    layers_path = os.path.join(args.out, "dependency_layers.json")
    with open(layers_path, "w") as f:
        json.dump({str(k): v for k, v in layers.items()}, f, indent=2)
    log.info(f"Wrote: {layers_path}")

    inventory_out = build_migration_inventory(graph, columns_df)
    csv_path = os.path.join(args.out, "migration_inventory.csv")
    inventory_out.to_csv(csv_path, index=False)
    log.info(f"Wrote: {csv_path}")

    if not args.skip_viz:
        generate_visualizations(graph, args.out)

    total     = len(graph.nodes)
    views     = sum(1 for n in graph.nodes.values() if n["type"] == "VIEW")
    tables    = sum(1 for n in graph.nodes.values() if n["type"] == "TABLE")
    external  = sum(1 for n in graph.nodes.values() if n["type"] == "EXTERNAL")
    max_layer = max((n["layer"] or 0) for n in graph.nodes.values())

    print("\n" + "="*60)
    print("  DREMIO LINEAGE EXTRACTION COMPLETE")
    print("="*60)
    print(f"  Total objects  : {total}")
    print(f"  Views (VDS)    : {views}")
    print(f"  Tables         : {tables}")
    print(f"  External refs  : {external}")
    print(f"  Max depth      : Layer {max_layer}")
    print(f"  Edges (deps)   : {sum(len(v) for v in graph.upstream.values())}")
    print("="*60)
    print(f"\n  Outputs written to: {args.out}/")
    print("    lineage_graph.json")
    print("    dependency_layers.json")
    print("    migration_inventory.csv")
    if not args.skip_viz:
        print("    lineage_full.png")
        print("    lineage_layered.png")
        print("    lineage_critical_paths.png")
        print("    lineage_interactive.html")
    print()


if __name__ == "__main__":
    main()
