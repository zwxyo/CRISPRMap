"""Migrated from crisprevo/spacermap_viz.py; see docs/MIGRATION.md."""
from __future__ import annotations

import re
import json
from collections import Counter
from html import escape as html_escape
from io import BytesIO
from itertools import permutations
from random import Random

from .validation import validate_arrays

WONG_PALETTE = [
    "#000000",
    "#e69f00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
]

SUPPORTED_EXPORT_FORMATS = {
    "png",
    "jpg",
    "jpeg",
    "svg",
    "pdf",
    "eps",
    "ps",
    "tif",
    "tiff",
    "webp",
}

EXPORT_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "eps": "application/postscript",
    "ps": "application/postscript",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "webp": "image/webp",
}


def parse_spacer_arrays(content: str) -> dict[str, list[str]]:
    arrays: dict[str, list[str]] = {}

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "\t" in line:
            name, payload = line.split("\t", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise ValueError(
                    f"Line {line_no} must contain an array name and a comma-separated spacer list."
                )
            name, payload = parts

        name = name.strip()
        payload = payload.strip()

        if not name:
            raise ValueError(f"Line {line_no} is missing an array name.")
        if name in arrays:
            raise ValueError(f"Duplicate array name '{name}' on line {line_no}.")

        payload = payload.replace(";", ",")
        spacers = [item.strip() for item in re.split(r"[\s,]+", payload) if item.strip()]

        if not spacers:
            raise ValueError(f"Line {line_no} does not contain any spacers.")

        arrays[name] = spacers

    validate_arrays(arrays)

    return arrays


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, channel)):02X}" for channel in rgb)


def _contrast_color(hex_color: str) -> str:
    red, green, blue = _hex_to_rgb(hex_color)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#111111" if luminance > 150 else "#FFFFFF"


def _random_colour_pairs(n_pairs: int, random_seed: int | None = None) -> list[tuple[str, str]]:
    rng = Random(random_seed)
    pairs = [
        ("#%06x" % rng.randint(0, 0xFFFFFF), "#%06x" % rng.randint(0, 0xFFFFFF))
        for _ in range(n_pairs)
    ]
    return pairs


def _seeded_palette_rotation(colours: list[str], random_seed: int) -> list[str]:
    if not colours:
        return []

    offset = int(random_seed) % len(colours)
    rotated = colours[offset:] + colours[:offset]

    if (int(random_seed) // len(colours)) % 2:
        rotated = [rotated[0], *reversed(rotated[1:])]

    return rotated


def _choose_col_scheme(
    n_colours: int,
    random_seed: int = 2,
    colour_list: list[str] | None = None,
) -> list[tuple[str, str]]:
    if colour_list:
        shuffled = _seeded_palette_rotation(colour_list, random_seed)
        if n_colours <= len(shuffled):
            return [(colour, "#000000") for colour in shuffled]
        scheme = shuffled
    elif n_colours <= len(WONG_PALETTE):
        colours = _seeded_palette_rotation(WONG_PALETTE, random_seed)
        return [(colour, "#000000") for colour in colours]
    else:
        scheme = WONG_PALETTE

    combos = [pair for pair in permutations(scheme, 2)]
    combos += [(colour, colour) for colour in scheme]

    colours = Random(random_seed).sample(combos, len(combos))

    if n_colours > len(colours):
        colours += _random_colour_pairs(n_colours - len(colours), random_seed)

    return colours


def _left_positions(rows: list[list[str]]) -> list[list[float]]:
    return [[float(index) for index in range(len(row))] for row in rows]


def _right_positions(rows: list[list[str]]) -> list[list[float]]:
    max_len = max(len(row) for row in rows)
    return [[float(max_len - len(row) + index) for index in range(len(row))] for row in rows]


def _justify_positions(rows: list[list[str]]) -> list[list[float]]:
    if not rows:
        return []

    spacer_counter = Counter(spacer for row in rows for spacer in row)
    if not any(count > 1 for count in spacer_counter.values()):
        return _right_positions(rows)

    common = {spacer for spacer, count in spacer_counter.items() if count > 1}
    targets: dict[str, float | None] = {}

    for spacer in spacer_counter:
        if spacer in common:
            positions: list[float] = []
            for row in rows:
                if spacer not in row:
                    continue
                row_len = max(len(row), 1)
                for index, current in enumerate(row):
                    if current == spacer:
                        positions.append(index / row_len)
            targets[spacer] = sum(positions) / len(positions) if positions else 0.0
        else:
            targets[spacer] = None

    def project_row(row: list[str]) -> list[list[float]]:
        projected: list[list[float]] = []
        last = -1e9

        for spacer in row:
            target = targets.get(spacer)
            column = -1.0 if target is None else target
            if column <= last:
                column = last + 0.01
            projected.append([spacer, column])
            last = column

        for index, (_, column) in enumerate(projected):
            if column != -1:
                continue

            left = projected[index - 1][1] if index > 0 else -1.0
            right_candidates = [col for _, col in projected[index + 1 :] if col != -1]
            right = right_candidates[0] if right_candidates else left + 1.0
            projected[index][1] = (left + right) / 2.0

        return projected

    projected = [project_row(row) for row in rows]

    for _ in range(6):
        actual = {spacer: [] for spacer in common}
        for row in projected:
            for spacer, column in row:
                if spacer in common:
                    actual[spacer].append(column)

        for spacer in common:
            if actual[spacer]:
                sorted_columns = sorted(actual[spacer])
                targets[spacer] = sorted_columns[len(sorted_columns) // 2]

        projected = [project_row(row) for row in rows]

    all_columns = sorted({column for row in projected for _, column in row})
    column_map = {old: index for index, old in enumerate(all_columns)}
    return [[float(column_map[column]) for _, column in row] for row in projected]


SUPPORTED_CLUSTER_MODES = {"none", "shared-spacer", "ancestral-spacer"}


def _normalize_cluster_mode(cluster_mode: str | None) -> str:
    normalized = (cluster_mode or "none").lower().strip().replace("_", "-")
    aliases = {
        "": "none",
        "off": "none",
        "no-clustering": "none",
        "shared": "shared-spacer",
        "shared-spacers": "shared-spacer",
        "ancestral": "ancestral-spacer",
        "ancestral-spacers": "ancestral-spacer",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_CLUSTER_MODES:
        raise ValueError("Cluster mode must be none, shared-spacer, or ancestral-spacer.")
    return normalized


def _cluster_mode_label(cluster_mode: str) -> str:
    return {
        "none": "No clustering",
        "shared-spacer": "Shared-spacer clustering",
        "ancestral-spacer": "Ancestral-spacer clustering",
    }[cluster_mode]


def _cluster_by_ancestral_spacers(rows: list[list[str]]) -> list[list[int]]:
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(row[-1] if row else "", []).append(index)
    return list(groups.values())


def _cluster_by_shared_spacers(rows: list[list[str]], min_shared: int = 2) -> list[list[int]]:
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(rows))}
    row_sets = [set(row) for row in rows]

    for index, spacers in enumerate(row_sets):
        for other_index in range(index + 1, len(row_sets)):
            if len(spacers & row_sets[other_index]) >= min_shared:
                adjacency[index].add(other_index)
                adjacency[other_index].add(index)

    groups: list[list[int]] = []
    used: set[int] = set()
    for index in range(len(rows)):
        if index in used:
            continue
        stack = [index]
        used.add(index)
        group: list[int] = []
        while stack:
            current = stack.pop()
            group.append(current)
            for neighbor in sorted(adjacency[current], reverse=True):
                if neighbor in used:
                    continue
                used.add(neighbor)
                stack.append(neighbor)
        groups.append(sorted(group))
    return sorted(groups, key=lambda group: group[0] if group else len(rows))


def build_cluster_network(arrays: dict[str, list[str]], cluster_mode: str) -> dict:
    """Return actual pairwise clustering links, not inferred clique membership."""
    validate_arrays(arrays)
    mode = _normalize_cluster_mode(cluster_mode)
    if mode == "none":
        return {"nodes": [], "edges": []}
    names, rows, cluster_ids, _ = _apply_clustering(
        list(arrays), [list(row) for row in arrays.values()], mode
    )
    nodes = [{"id": i, "name": name, "cluster": cluster_ids[i]}
             for i, name in enumerate(names)]
    edges = []
    row_sets = [set(row) for row in rows]
    for i, row in enumerate(rows):
        for j in range(i + 1, len(rows)):
            shared = len(row_sets[i] & row_sets[j])
            linked = (shared >= 2 if mode == "shared-spacer" else
                      bool(row and rows[j] and row[-1] == rows[j][-1]))
            if linked:
                edges.append({"source": i, "target": j, "shared": shared})
    return {"nodes": nodes, "edges": edges}


def _apply_clustering(
    names: list[str],
    rows: list[list[str]],
    cluster_mode: str,
) -> tuple[list[str], list[list[str]], list[int], list[list[str]]]:
    if cluster_mode == "ancestral-spacer":
        index_groups = _cluster_by_ancestral_spacers(rows)
    elif cluster_mode == "shared-spacer":
        index_groups = _cluster_by_shared_spacers(rows)
    else:
        index_groups = [list(range(len(rows)))]

    ordered_names: list[str] = []
    ordered_rows: list[list[str]] = []
    row_cluster_ids: list[int] = []
    named_groups: list[list[str]] = []

    for cluster_id, group in enumerate(index_groups):
        named_group: list[str] = []
        for index in group:
            ordered_names.append(names[index])
            ordered_rows.append(rows[index])
            row_cluster_ids.append(cluster_id)
            named_group.append(names[index])
        named_groups.append(named_group)

    return ordered_names, ordered_rows, row_cluster_ids, named_groups


def _build_summary(
    names: list[str],
    counts: Counter[str],
    shared_spacers: set[str],
    unique_spacers: set[str],
    align: str,
    random_seed: int,
    cluster_mode: str,
    clusters: list[list[str]],
) -> dict[str, object]:
    cluster_label = _cluster_mode_label(cluster_mode)
    notes = [
        f"{len(names)} array(s) detected with {len(counts)} spacer label(s).",
        f"{len(shared_spacers)} spacer label(s) are shared across multiple arrays.",
        "Spacers present in only one array are marked with a triangle in every copy, including repeats within that array.",
        f"Colours follow the CCTK Wong seed-based scheme (seed={random_seed}).",
    ]

    if cluster_mode == "none":
        notes.append(f"{align.title()} alignment preserves the input order while repositioning the boxes.")
    else:
        notes.append(f"{cluster_label} reordered the rows into {len(clusters)} group(s) before alignment.")
        if cluster_mode == "shared-spacer":
            notes.append("Shared-spacer groups connect arrays sharing at least two spacer labels.")
        else:
            notes.append("Ancestral-spacer groups are based on the rightmost spacer label.")
        if not any(len(group) > 1 for group in clusters):
            notes.append("No multi-row clusters were detected, so the preview stays close to input order.")

    return {
        "array_count": len(names),
        "spacer_count": len(counts),
        "shared_spacer_count": len(shared_spacers),
        "unique_spacer_count": len(unique_spacers),
        "cluster_mode": cluster_mode,
        "cluster_count": len(clusters),
        "clusters": clusters if cluster_mode != "none" else [],
        "notes": notes,
    }


def _build_layout(
    arrays: dict[str, list[str]],
    align: str = "right",
    cluster_mode: str = "none",
    random_seed: int = 2,
) -> dict[str, object]:
    validate_arrays(arrays)

    align = align.lower().strip()
    if align not in {"left", "right", "justify"}:
        raise ValueError("Align mode must be left, right, or justify.")

    cluster_mode = _normalize_cluster_mode(cluster_mode)
    names = list(arrays.keys())
    rows = [list(arrays[name]) for name in names]
    ordered_names, ordered_rows, row_cluster_ids, cluster_groups = _apply_clustering(names, rows, cluster_mode)

    positions = {
        "left": _left_positions,
        "right": _right_positions,
        "justify": _justify_positions,
    }[align](ordered_rows)

    # Preserve every box, but count each label only once per array for uniqueness.
    counts = Counter(spacer for row in ordered_rows for spacer in dict.fromkeys(row))
    unique_spacers = {spacer for spacer, count in counts.items() if count == 1}
    shared_spacers = {spacer for spacer, count in counts.items() if count > 1}
    spacer_labels = sorted(counts)
    colour_pairs = _choose_col_scheme(len(spacer_labels), random_seed=random_seed)
    spacer_colors = dict(zip(spacer_labels, colour_pairs))
    max_col = max((max(row) if row else 0.0) for row in positions)
    summary = _build_summary(
        ordered_names,
        counts,
        shared_spacers,
        unique_spacers,
        align,
        random_seed,
        cluster_mode,
        cluster_groups,
    )

    row_tops: list[float] = []
    cluster_gap = 16.0 if cluster_mode != "none" and len(cluster_groups) > 1 else 0.0
    gap_count = 0
    for index, cluster_id in enumerate(row_cluster_ids):
        if index > 0 and cluster_id != row_cluster_ids[index - 1]:
            gap_count += 1
        row_tops.append(float(index * 34 + gap_count * cluster_gap))

    return {
        "align": align,
        "cluster_mode": cluster_mode,
        "cluster_count": len(cluster_groups),
        "names": ordered_names,
        "rows": ordered_rows,
        "positions": positions,
        "row_cluster_ids": row_cluster_ids,
        "row_tops": row_tops,
        "counts": counts,
        "unique_spacers": unique_spacers,
        "shared_spacers": shared_spacers,
        "spacer_colors": spacer_colors,
        "max_col": max_col,
        "summary": summary,
    }


def build_spacermap_svg(
    arrays: dict[str, list[str]],
    align: str = "right",
    cluster_mode: str = "none",
    random_seed: int = 2,
) -> tuple[str, dict[str, object]]:
    layout = _build_layout(arrays, align=align, cluster_mode=cluster_mode, random_seed=random_seed)
    names = layout["names"]
    rows = layout["rows"]
    positions = layout["positions"]
    row_cluster_ids = layout["row_cluster_ids"]
    row_tops = layout["row_tops"]
    unique_spacers = layout["unique_spacers"]
    spacer_colors = layout["spacer_colors"]
    max_col = layout["max_col"]
    summary = layout["summary"]

    slot_width = 28
    box_width = 22
    box_height = 18
    left_margin = 28
    top_margin = 72
    label_gap = 18
    # right_margin = 180
    max_name_chars = max((len(name) for name in names), default=0)
    right_margin = max(
        180,
        int(label_gap + max_name_chars * 8 + 20),
    )
    bottom_margin = 36

    width = int(left_margin + (max_col + 1) * slot_width + right_margin)
    height = int(top_margin + (row_tops[-1] if row_tops else 0.0) + box_height + bottom_margin)

    composer_data = {
        "format": "crisprevo-spacermap", "version": 1,
        "arrays": [{"name": name, "spacers": row, "positions": pos}
                   for name, row, pos in zip(names, rows, positions)],
        "colors": {key: {"fill": pair[0], "stroke": pair[1]}
                   for key, pair in spacer_colors.items()},
        "align": align,
    }
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="SpacerMap visualization">',
        '<metadata id="crisprevo-spacermap">' + html_escape(json.dumps(composer_data, ensure_ascii=False), quote=False) + '</metadata>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    for row_index in range(len(rows) - 1):
        if row_cluster_ids[row_index] != row_cluster_ids[row_index + 1]:
            continue

        row_a = rows[row_index]
        row_b = rows[row_index + 1]
        pos_a = positions[row_index]
        pos_b = positions[row_index + 1]
        y_a = top_margin + row_tops[row_index]
        y_b = top_margin + row_tops[row_index + 1]

        for index_a, spacer_a in enumerate(row_a):
            for index_b, spacer_b in enumerate(row_b):
                if spacer_a != spacer_b:
                    continue

                fill, _ = spacer_colors[spacer_a]
                x1 = left_margin + pos_a[index_a] * slot_width + box_width / 2
                x2 = left_margin + pos_b[index_b] * slot_width + box_width / 2
                svg.append(
                    f'<line x1="{x1:.2f}" y1="{y_a + box_height:.2f}" x2="{x2:.2f}" y2="{y_b:.2f}" stroke="{fill}" stroke-width="2.6" stroke-linecap="round" stroke-opacity="0.78"/>'
                )

    for row_index, name in enumerate(names):
        row = rows[row_index]
        row_positions = positions[row_index]
        y = top_margin + row_tops[row_index]
        label_x = left_margin + (max_col + 1) * slot_width + label_gap

        for spacer_index, spacer in enumerate(row):
            fill, edge = spacer_colors[spacer]
            text_color = _contrast_color(fill)
            x = left_margin + row_positions[spacer_index] * slot_width
            svg.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{box_width}" height="{box_height}" rx="4" ry="4" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>'
            )
            if spacer in unique_spacers:
                svg.append(
                    f'<text x="{x + box_width / 2:.2f}" y="{y + box_height / 2 + 0.5:.2f}" text-anchor="middle" dominant-baseline="middle" font-family="DejaVu Sans, Arial, sans-serif" font-size="11" font-weight="700" fill="{text_color}">▲</text>'
                )

        svg.append(
            f'<text x="{label_x}" y="{y + box_height / 2 + 0.5:.2f}" font-family="DejaVu Sans, Arial, sans-serif" font-size="12" font-weight="700" fill="#16202b" dominant-baseline="middle">{html_escape(name)}</text>'
        )

    svg.append("</svg>")
    return "\n".join(svg), summary


def build_spacermap_figure(
    arrays: dict[str, list[str]],
    align: str = "right",
    cluster_mode: str = "none",
    random_seed: int = 2,
):
    try:
        import matplotlib.colors as mcolors
        from matplotlib.figure import Figure
        from matplotlib.patches import Rectangle
    except ModuleNotFoundError as exc:
        raise RuntimeError("Static export requires the optional matplotlib dependency in this environment.") from exc

    layout = _build_layout(arrays, align=align, cluster_mode=cluster_mode, random_seed=random_seed)
    names = layout["names"]
    rows = layout["rows"]
    positions = layout["positions"]
    row_cluster_ids = layout["row_cluster_ids"]
    unique_spacers = layout["unique_spacers"]
    spacer_colors = layout["spacer_colors"]
    max_col = layout["max_col"]
    cluster_count = layout["cluster_count"]
    summary = layout["summary"]

    box_w = 0.5
    box_h = 0.6
    box_gap = 0.15
    link_width = 4
    link_alpha = 1
    v_gap = 1.2
    cluster_gap = 0.65 if layout["cluster_mode"] != "none" and cluster_count > 1 else 0.0
    left_margin = 1
    label_gap = 0.3
    max_len = int(max_col) + 1
    max_name_chars = max((len(name) for name in names), default=0)
    label_width = max(1.5, max_name_chars * 0.13 + 0.4)

    figure_row_tops: list[float] = []
    gap_count = 0
    for index, cluster_id in enumerate(row_cluster_ids):
        if index > 0 and cluster_id != row_cluster_ids[index - 1]:
            gap_count += 1
        figure_row_tops.append(-(index * v_gap + gap_count * cluster_gap))

    # fig_width = max(max_len * 0.4 + 4, 6)
    fig_width = max(max_len * 0.4 + label_width + 2.5, 6)
    fig_height = max(len(rows) * 0.4 + 3 + max(cluster_count - 1, 0) * 0.25, 4)
    fig = Figure(figsize=(fig_width, fig_height))
    ax = fig.subplots()

    for row_index in range(len(rows) - 1):
        if row_cluster_ids[row_index] != row_cluster_ids[row_index + 1]:
            continue

        row_a = rows[row_index]
        row_b = rows[row_index + 1]
        pos_a = positions[row_index]
        pos_b = positions[row_index + 1]

        for index_a, spacer_a in enumerate(row_a):
            for index_b, spacer_b in enumerate(row_b):
                if spacer_a != spacer_b:
                    continue

                fill, _ = spacer_colors[spacer_a]
                x1 = left_margin + pos_a[index_a] * (box_w + box_gap) + box_w / 2
                x2 = left_margin + pos_b[index_b] * (box_w + box_gap) + box_w / 2
                y1 = figure_row_tops[row_index]
                # Matplotlib y increases upward: meet the lower box at its top.
                y2 = figure_row_tops[row_index + 1] + box_h
                ax.plot([x1, x2], [y1, y2], color=fill, linewidth=link_width, alpha=link_alpha, zorder=1)

    for row_index, row in enumerate(rows):
        y = figure_row_tops[row_index]
        row_positions = positions[row_index]
        for spacer_index, spacer in enumerate(row):
            fill, edge = spacer_colors[spacer]
            x = left_margin + row_positions[spacer_index] * (box_w + box_gap)
            rect = Rectangle((x, y), box_w, box_h, facecolor=fill, edgecolor=edge, linewidth=5, zorder=2)
            ax.add_patch(rect)
            if spacer in unique_spacers:
                red, green, blue = mcolors.to_rgb(fill)
                luminance = 0.299 * red + 0.587 * green + 0.114 * blue
                text_color = "white" if luminance < 0.5 else "black"
                ax.text(
                    x + box_w / 2,
                    y + box_h / 2,
                    "▲",
                    ha="center",
                    va="center",
                    fontsize=12,
                    color=text_color,
                    weight="bold",
                    zorder=3,
                )

        plot_width = max_len * (box_w + box_gap)
        x_label = left_margin + plot_width + label_gap
        ax.text(
            x_label,
            y + box_h / 2,
            names[row_index],
            ha="left",
            va="center",
            fontsize=10,
            color="black",
            weight="bold",
            parse_math=False,
            zorder=3,
        )

    plot_width = max_len * (box_w + box_gap)
    # total_width = left_margin + plot_width + label_gap + 1.5
    total_width = left_margin + plot_width + label_gap + label_width
    ax.set_xlim(0, total_width)
    ax.set_ylim(figure_row_tops[-1] - box_h - 0.8, 2)
    ax.axis("off")
    fig.tight_layout()
    return fig, summary


def export_spacermap_bytes(
    arrays: dict[str, list[str]],
    align: str = "right",
    cluster_mode: str = "none",
    random_seed: int = 2,
    output_format: str = "svg",
    dpi: int = 300,
) -> tuple[bytes, str, str, dict[str, object]]:
    normalized_format = output_format.lower().strip()
    if normalized_format not in SUPPORTED_EXPORT_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_EXPORT_FORMATS))
        raise ValueError(f"Unsupported export format '{output_format}'. Supported formats: {supported}.")
    if dpi <= 0:
        raise ValueError("DPI must be a positive integer.")
    if normalized_format == "svg":
        svg, summary = build_spacermap_svg(arrays, align=align, cluster_mode=cluster_mode, random_seed=random_seed)
        return svg.encode("utf-8"), EXPORT_MEDIA_TYPES["svg"], "svg", summary

    save_format = {"jpg": "jpeg", "tif": "tiff"}.get(normalized_format, normalized_format)
    try:
        fig, summary = build_spacermap_figure(arrays, align=align, cluster_mode=cluster_mode, random_seed=random_seed)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    try:
        buffer = BytesIO()
        fig.savefig(buffer, format=save_format, dpi=dpi, bbox_inches="tight")
        return buffer.getvalue(), EXPORT_MEDIA_TYPES[normalized_format], normalized_format, summary
    finally:
        fig.clear()
