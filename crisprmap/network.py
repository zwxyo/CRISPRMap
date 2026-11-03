"""Headless adaptation of SpacerMap_test array_cluster.visualize_clusters.

Use crisprevo's pairwise links with a spring layout per component. Compact node
numbers map to full names in a separate key, leaving network edges unobscured.
"""
from math import ceil
import textwrap

from .spacermap import build_cluster_network, _choose_col_scheme, _contrast_color


def build_network_figure(arrays, cluster_mode="shared-spacer", random_seed=2):
    from matplotlib.figure import Figure
    import networkx as nx

    data = build_cluster_network(arrays, cluster_mode)
    if not data["nodes"]:
        raise ValueError("Network plots require shared-spacer or ancestral-spacer clustering.")
    graph = nx.Graph()
    for node in data["nodes"]:
        graph.add_node(node["id"], name=node["name"], cluster=node["cluster"])
    for edge in data["edges"]:
        graph.add_edge(edge["source"], edge["target"], weight=edge["shared"])

    cluster_count = max(node["cluster"] for node in data["nodes"]) + 1
    colors = _choose_col_scheme(cluster_count, random_seed)
    components = [list(component) for component in nx.connected_components(graph)]
    columns = min(2, len(components))
    rows = ceil(len(components) / columns)
    # Wrap the name key rather than allowing long names to stretch over edges.
    labels = {node: textwrap.wrap(graph.nodes[node]["name"], width=52,
                                  replace_whitespace=False) or [""] for node in graph}
    key_lines = sum(len(lines) + .4 for lines in labels.values())
    key_width = max(3.0, max(len(line) for lines in labels.values() for line in lines) * .067 + .8)
    height = max(3.6 * rows, key_lines * .19 + .5)
    fig = Figure(figsize=(3.8 * columns + key_width, height))
    grid = fig.add_gridspec(rows, columns + 1, width_ratios=[3.8] * columns + [key_width],
                           left=.025, right=.985, bottom=.035, top=.965, wspace=.08, hspace=.15)
    max_weight = max((edge["shared"] for edge in data["edges"]), default=1)
    for index, nodes in enumerate(components):
        ax = fig.add_subplot(grid[index // columns, index % columns])
        subgraph = graph.subgraph(nodes)
        # Lay out components independently; disconnected groups no longer squeeze
        # their nodes into small corners of one large global layout.
        pos = nx.spring_layout(subgraph, seed=random_seed, weight=None, iterations=100)
        node_colors = [colors[graph.nodes[node]["cluster"]][0] for node in subgraph]
        weights = [subgraph[u][v]["weight"] for u, v in subgraph.edges()]
        nx.draw_networkx_edges(subgraph, pos, width=[.6 + 1.4 * w / max_weight for w in weights],
                               edge_color="#64748b", alpha=.65, ax=ax)
        nx.draw_networkx_nodes(subgraph, pos, node_color=node_colors, node_size=420,
                               edgecolors="white", linewidths=1, ax=ax)
        for node, color in zip(subgraph, node_colors):
            x, y = pos[node]
            ax.text(x, y, str(node + 1), color=_contrast_color(color), fontsize=8,
                    ha="center", va="center", zorder=3)
        ax.set_aspect("equal")
        ax.margins(.22)
        ax.axis("off")

    key = fig.add_subplot(grid[:, columns])
    key.axis("off")
    step = min(.19 / height / .93, .96 / max(key_lines, 1))
    y = .98
    for node in graph:
        color = colors[graph.nodes[node]["cluster"]][0]
        key.text(.02, y, str(node + 1), color=_contrast_color(color), fontsize=8,
                 ha="center", va="top", transform=key.transAxes,
                 bbox={"boxstyle": "circle,pad=.22", "facecolor": color, "edgecolor": "none"})
        for line_index, line in enumerate(labels[node]):
            key.text(.09, y - line_index * step, line, fontsize=8, color="#16202b",
                     ha="left", va="top", transform=key.transAxes, parse_math=False)
        y -= (len(labels[node]) + .4) * step
    return fig, {**data, "array_count": len(graph), "cluster_count": cluster_count,
                 "edge_weight": "number of distinct shared spacer IDs",
                 "node_labels": {str(node + 1): graph.nodes[node]["name"] for node in graph}}


def export_cluster_network(arrays, cluster_mode="shared-spacer", random_seed=2,
                           output_format="svg", dpi=300):
    from ._export import export_figure

    fig, summary = build_network_figure(arrays, cluster_mode, random_seed)
    return export_figure(fig, summary, output_format, dpi)
