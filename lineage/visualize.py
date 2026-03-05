"""
Visualization — static PNGs (matplotlib + networkx) and interactive HTML (pyvis).

Exports:
  generate_visualizations(graph, out_dir)  — main entry point
"""

import math
import logging
import textwrap

import networkx as nx
import matplotlib
matplotlib.use("Agg")   # headless — no display required
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from .graph import LineageGraph

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

_TYPE_COLORS = {
    "TABLE":    "#4C9BE8",   # blue
    "VIEW":     "#56C596",   # green
    "EXTERNAL": "#F4A942",   # orange
    "UNKNOWN":  "#B0B0B0",   # grey
}

_LAYER_CMAP = plt.cm.plasma


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def build_nx_graph(graph: LineageGraph) -> nx.DiGraph:
    """Convert a LineageGraph into a networkx DiGraph."""
    G = nx.DiGraph()
    for nid, node in graph.nodes.items():
        G.add_node(
            nid,
            label=node["name"],
            schema=node["schema"],
            obj_type=node["type"],
            layer=node["layer"] if node["layer"] is not None else -1,
            has_sql=bool(node["view_sql"]),
        )
    for downstream_id, upstream_set in graph.upstream.items():
        for upstream_id in upstream_set:
            if upstream_id in G and downstream_id in G:
                G.add_edge(upstream_id, downstream_id)
    return G


def _short_label(nid: str, max_len: int = 22) -> str:
    name = nid.rsplit(".", 1)[-1]
    return (name[:max_len - 1] + "…") if len(name) > max_len else name


def _layer_layout(G: nx.DiGraph) -> dict:
    """
    Hierarchical layout: x = layer, y = position within layer (evenly spaced).
    Falls back to spring_layout if all nodes share the same layer.
    """
    layers: dict[int, list] = {}
    for nid, data in G.nodes(data=True):
        layer = data.get("layer", 0) or 0
        layers.setdefault(layer, []).append(nid)

    if len(layers) <= 1:
        return nx.spring_layout(G, seed=42, k=2.5)

    pos = {}
    max_count = max(len(v) for v in layers.values())
    for layer, nodes in sorted(layers.items()):
        count = len(nodes)
        for i, nid in enumerate(sorted(nodes)):
            y = (i - (count - 1) / 2) * (max_count / max(count, 1))
            pos[nid] = (layer * 3.5, y)
    return pos


def _node_colors(G: nx.DiGraph, color_by: str = "type") -> list:
    if color_by == "type":
        return [_TYPE_COLORS.get(d.get("obj_type", "UNKNOWN"), "#B0B0B0")
                for _, d in G.nodes(data=True)]
    elif color_by == "layer":
        layers = [d.get("layer", 0) or 0 for _, d in G.nodes(data=True)]
        max_l = max(layers) if layers else 1
        return [_LAYER_CMAP(l / max(max_l, 1)) for l in layers]
    return ["#cccccc"] * G.number_of_nodes()


def _add_legend_type(ax):
    patches = [mpatches.Patch(color=c, label=t) for t, c in _TYPE_COLORS.items()]
    ax.legend(handles=patches, loc="upper left", fontsize=7,
              title="Object type", title_fontsize=7, framealpha=0.85)


def _save(fig, path: str):
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info(f"Wrote: {path}")


# ---------------------------------------------------------------------------
# Plot 1 — Full graph (spring layout, colored by type)
# ---------------------------------------------------------------------------

def plot_full_graph(G: nx.DiGraph, out_path: str,
                    title: str = "Dremio Lineage — Full Graph"):
    n = G.number_of_nodes()
    if n == 0:
        log.warning("No nodes to plot in full graph.")
        return

    fig_w = max(16, min(n * 0.5, 40))
    fig_h = max(10, min(n * 0.35, 28))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.set_title(title, color="white", fontsize=13, pad=12, fontweight="bold")
    ax.axis("off")

    k_val = 2.5 / math.sqrt(max(n, 1))
    pos = nx.spring_layout(G, seed=42, k=k_val, iterations=60)

    node_colors = _node_colors(G, "type")
    node_sizes  = [600 + 300 * G.out_degree(nid) for nid in G.nodes()]

    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color="#ffffff22", arrows=True,
        arrowstyle="-|>", arrowsize=12, width=0.8,
        connectionstyle="arc3,rad=0.08",
    )
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors, node_size=node_sizes,
        alpha=0.92, linewidths=0.5, edgecolors="#ffffff55",
    )

    label_nodes = {n for n in G.nodes() if G.out_degree(n) >= 1}
    labels = {nid: _short_label(nid) for nid in label_nodes}
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                            font_size=6, font_color="white", font_weight="bold")

    _add_legend_type(ax)
    ax.text(
        0.99, 0.01,
        f"{n} objects  |  {G.number_of_edges()} dependencies",
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=8, color="#aaaaaa",
    )
    _save(fig, out_path)


# ---------------------------------------------------------------------------
# Plot 2 — Layered hierarchy (left→right by migration layer)
# ---------------------------------------------------------------------------

def plot_layered_graph(G: nx.DiGraph, out_path: str,
                       title: str = "Dremio Lineage — Migration Layers"):
    n = G.number_of_nodes()
    if n == 0:
        log.warning("No nodes to plot in layered graph.")
        return

    pos = _layer_layout(G)
    layers = sorted(set(d.get("layer", 0) or 0 for _, d in G.nodes(data=True)))
    max_layer = max(layers) if layers else 0

    fig_w = max(14, (max_layer + 1) * 4.5)
    fig_h = max(10, n * 0.28)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="#0f0f1a")
    ax.set_facecolor("#0f0f1a")
    ax.set_title(title, color="white", fontsize=13, pad=12, fontweight="bold")
    ax.axis("off")

    for layer in layers:
        layer_nodes = [nid for nid, d in G.nodes(data=True) if (d.get("layer") or 0) == layer]
        if not layer_nodes:
            continue
        x_center = pos[layer_nodes[0]][0]
        color = "#ffffff08" if layer % 2 == 0 else "#ffffff04"
        ax.axvspan(x_center - 1.5, x_center + 1.5, color=color, zorder=0)
        ax.text(
            x_center, ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else -n * 0.15,
            f"Layer {layer}" if layer >= 0 else "⚠ Cycle",
            ha="center", va="top", fontsize=8,
            color="#88aaff" if layer >= 0 else "#ff6666",
            fontweight="bold",
        )

    node_colors = _node_colors(G, "layer")
    node_sizes  = [max(300, 200 * (1 + G.in_degree(nid))) for nid in G.nodes()]

    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color="#4488ff55", arrows=True,
        arrowstyle="-|>", arrowsize=14, width=1.0,
        connectionstyle="arc3,rad=0.05",
    )
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors, node_size=node_sizes,
        alpha=0.9, linewidths=0.6, edgecolors="#aaaaaa55",
    )
    labels = {nid: _short_label(nid, 18) for nid in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                            font_size=6.5, font_color="white")

    sm = plt.cm.ScalarMappable(cmap=_LAYER_CMAP,
                                norm=plt.Normalize(vmin=0, vmax=max(max_layer, 1)))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="vertical", fraction=0.015, pad=0.01)
    cbar.set_label("Dependency Layer", color="white", fontsize=8)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=7)

    _add_legend_type(ax)
    _save(fig, out_path)


# ---------------------------------------------------------------------------
# Plot 3 — Critical paths (deepest chains only)
# ---------------------------------------------------------------------------

def plot_critical_paths(G: nx.DiGraph, out_path: str,
                        min_layer: int = 2,
                        title: str = "Dremio Lineage — Critical Paths (High Complexity)"):
    """Show only nodes at or above min_layer AND all their ancestors."""
    deep_nodes = {nid for nid, d in G.nodes(data=True)
                  if (d.get("layer") or 0) >= min_layer}

    if not deep_nodes:
        log.info(f"No nodes at layer >= {min_layer}; skipping critical paths chart.")
        return

    subgraph_nodes = set(deep_nodes)
    for nid in deep_nodes:
        subgraph_nodes |= nx.ancestors(G, nid)

    SG = G.subgraph(subgraph_nodes).copy()
    n = SG.number_of_nodes()

    fig_w = max(14, n * 0.45)
    fig_h = max(10, n * 0.3)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")
    ax.set_title(title, color="white", fontsize=13, pad=12, fontweight="bold")
    ax.axis("off")

    pos = _layer_layout(SG)

    longest_path = []
    try:
        longest_path = nx.dag_longest_path(SG)
    except Exception:
        pass
    longest_set   = set(longest_path)
    longest_edges = set(zip(longest_path, longest_path[1:]))

    node_colors = []
    node_sizes  = []
    for nid in SG.nodes():
        layer = SG.nodes[nid].get("layer") or 0
        if nid in longest_set:
            node_colors.append("#FF4C6A")
            node_sizes.append(900)
        elif layer >= min_layer:
            node_colors.append("#FFB347")
            node_sizes.append(700)
        else:
            node_colors.append("#4C9BE8")
            node_sizes.append(450)

    edge_colors = []
    edge_widths = []
    for u, v in SG.edges():
        if (u, v) in longest_edges:
            edge_colors.append("#FF4C6A")
            edge_widths.append(2.5)
        else:
            edge_colors.append("#ffffff33")
            edge_widths.append(0.8)

    nx.draw_networkx_edges(
        SG, pos, ax=ax,
        edge_color=edge_colors, width=edge_widths,
        arrows=True, arrowstyle="-|>", arrowsize=14,
        connectionstyle="arc3,rad=0.06",
    )
    nx.draw_networkx_nodes(
        SG, pos, ax=ax,
        node_color=node_colors, node_size=node_sizes,
        alpha=0.93, linewidths=0.5, edgecolors="#ffffff44",
    )
    labels = {nid: _short_label(nid, 20) for nid in SG.nodes()}
    nx.draw_networkx_labels(SG, pos, labels=labels, ax=ax,
                            font_size=7, font_color="white", font_weight="bold")

    legend_elements = [
        mpatches.Patch(color="#FF4C6A", label="Critical path (longest chain)"),
        mpatches.Patch(color="#FFB347", label=f"High complexity (layer ≥ {min_layer})"),
        mpatches.Patch(color="#4C9BE8", label="Upstream dependency"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=7,
              framealpha=0.85, title="Node type", title_fontsize=7)

    path_str = " → ".join(_short_label(n) for n in longest_path)
    wrapped  = textwrap.fill(f"Longest chain: {path_str}", width=110)
    ax.text(0.01, 0.01, wrapped, transform=ax.transAxes, fontsize=6,
            color="#aaaaaa", va="bottom", ha="left")

    _save(fig, out_path)


# ---------------------------------------------------------------------------
# Plot 4 — Interactive HTML (pyvis)
# ---------------------------------------------------------------------------

def plot_interactive(G: nx.DiGraph, out_path: str,
                     title: str = "Dremio Lineage — Interactive"):
    """Build an interactive pan/zoom/hover graph with pyvis."""
    try:
        from pyvis.network import Network
    except ImportError:
        log.warning("pyvis not installed — skipping interactive HTML. Run: pip install pyvis")
        return

    net = Network(
        height="900px", width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="white",
        notebook=False,
        heading=title,
    )
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "hierarchicalRepulsion": {
          "centralGravity": 0.1,
          "nodeDistance": 160,
          "springLength": 120
        },
        "solver": "hierarchicalRepulsion",
        "stabilization": { "iterations": 200 }
      },
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "LR",
          "sortMethod": "directed",
          "levelSeparation": 200,
          "nodeSpacing": 100
        }
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.7 } },
        "color": { "color": "#4488ff", "highlight": "#ff4c6a" },
        "smooth": { "type": "curvedCW", "roundness": 0.1 }
      },
      "nodes": {
        "font": { "size": 12, "color": "white" },
        "borderWidth": 1.5
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    max_layer = max((d.get("layer") or 0) for _, d in G.nodes(data=True)) or 1

    for nid, data in G.nodes(data=True):
        obj_type = data.get("obj_type", "UNKNOWN")
        layer    = data.get("layer") or 0
        schema   = data.get("schema", "")
        has_sql  = data.get("has_sql", False)

        color = _TYPE_COLORS.get(obj_type, "#B0B0B0")
        size  = 18 + 8 * G.out_degree(nid)

        tooltip = (
            f"<b>{_short_label(nid, 40)}</b><br>"
            f"Schema: {schema}<br>"
            f"Type: {obj_type}<br>"
            f"Layer: {layer}<br>"
            f"Upstream deps: {G.in_degree(nid)}<br>"
            f"Downstream deps: {G.out_degree(nid)}<br>"
            f"Has SQL: {'Yes' if has_sql else 'No'}"
        )

        net.add_node(
            nid,
            label=_short_label(nid, 20),
            title=tooltip,
            color=color,
            size=size,
            level=layer,
            shape="dot" if obj_type == "TABLE" else
                  "diamond" if obj_type == "EXTERNAL" else "ellipse",
        )

    for u, v in G.edges():
        net.add_edge(u, v, title=f"{_short_label(u)} → {_short_label(v)}")

    net.save_graph(out_path)
    log.info(f"Wrote: {out_path}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_visualizations(graph: LineageGraph, out_dir: str):
    """Build all four visualizations from the LineageGraph."""
    import os
    log.info("Generating visualizations ...")
    G = build_nx_graph(graph)

    if G.number_of_nodes() == 0:
        log.warning("Graph is empty — no visualizations generated.")
        return

    plot_full_graph(G, out_path=os.path.join(out_dir, "lineage_full.png"))
    plot_layered_graph(G, out_path=os.path.join(out_dir, "lineage_layered.png"))
    plot_critical_paths(G, out_path=os.path.join(out_dir, "lineage_critical_paths.png"), min_layer=2)
    plot_interactive(G, out_path=os.path.join(out_dir, "lineage_interactive.html"))

    log.info("Visualizations complete.")
