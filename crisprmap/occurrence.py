"""Array-level spacer prevalence and a shared scene for preview and export."""
from collections import Counter
from colorsys import hsv_to_rgb
from functools import lru_cache
from io import BytesIO
import math
import textwrap
from xml.etree import ElementTree as ET

from .spacermap import EXPORT_MEDIA_TYPES, SUPPORTED_EXPORT_FORMATS

from .validation import validate_arrays

MAX_CHART_SPACERS = 50
MAX_RASTER_PIXELS = 40_000_000
COLORS = ["#087bce", "#159e9c", "#16bfe8", "#ffa334", "#8d57bf", "#ff6655",
          "#4776b4", "#44aa99", "#d4a72c", "#cc79a7"]


def _linear_rgb(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]


def _lab(color):
    """sRGB to CIELAB (D65), for selecting separated categorical colors."""
    r, g, b = _linear_rgb(color)
    xyz = ((.4124564*r + .3575761*g + .1804375*b) / .95047,
           .2126729*r + .7151522*g + .0721750*b,
           (.0193339*r + .1191920*g + .9503041*b) / 1.08883)
    x, y, z = [v ** (1/3) if v > (6/29)**3 else v / (3*(6/29)**2) + 4/29 for v in xyz]
    return (116*y - 16, 500*(x-y), 200*(y-z))


@lru_cache(maxsize=1)
def occurrence_palette():
    # Keep the reference colors, then greedily maximize the minimum Lab distance
    # from every selected color. Fixed candidates/order keep all exports stable.
    selected = list(COLORS)
    candidates = sorted({"#" + "".join(f"{round(c * 255):02x}" for c in hsv_to_rgb(h/360, s, v))
                         for h in range(0, 360, 5) for s in (.5, .7, .9) for v in (.55, .7, .85, .95)} - set(selected))
    labs = [_lab(color) for color in candidates]
    distance = lambda a, b: sum((x-y)**2 for x, y in zip(a, b))
    selected_labs = [_lab(color) for color in selected]
    nearest = [min(distance(lab, other) for other in selected_labs) for lab in labs]
    while len(selected) < MAX_CHART_SPACERS:
        index = max(range(len(candidates)), key=lambda i: nearest[i])
        selected.append(candidates[index])
        nearest = [min(d, distance(lab, labs[index])) for d, lab in zip(nearest, labs)]
    return tuple(selected)


def _header_text_color(color):
    r, g, b = _linear_rgb(color)
    luminance = .2126*r + .7152*g + .0722*b
    return "#102039" if luminance > .25 else "white"


def spacer_occurrence_stats(arrays):
    validate_arrays(arrays)
    counts = Counter()
    total = 0
    for spacers in arrays.values():
        total += len(spacers)
        # Preserve first appearance as the tie breaker; count an array only once.
        counts.update(list(dict.fromkeys(spacers)))
    rows = [{"spacer_id": label, "array_count": count}
            for label, count in sorted(counts.items(), key=lambda item: -item[1])]
    allowed = 0 < len(rows) <= MAX_CHART_SPACERS
    return {"array_count": len(arrays), "spacer_count": len(rows), "total_occurrences": total,
            "rows": rows, "max_chart_spacers": MAX_CHART_SPACERS, "chart_available": allowed,
            "chart_message": ("" if allowed else
                f"Bar charts support 1–{MAX_CHART_SPACERS} distinct spacers; this result has {len(rows)}. "
                "Statistics remain available. Reduce the input and run again to plot all retained spacers.")}


def _scene(arrays, stats):
    if not stats["chart_available"]:
        raise ValueError(stats["chart_message"])
    rows = stats["rows"]
    labels = [textwrap.wrap(row["spacer_id"], 16) or [""] for row in rows]
    names = [textwrap.wrap(name, 24) or [""] for name in arrays]
    n = len(rows)
    colors = occurrence_palette()[:n]
    name_width = max(120, max(len(line) for lines in names for line in lines) * 14 + 24)
    column_width = max(100, max(len(line) for lines in labels for line in lines) * 14 + 16)
    width = max(1000, name_width + n * column_width + 50)
    left, right, top, bottom = 85, width - 25, 45, 345
    step = (right - left) / n
    label_height = max(map(len, labels)) * 17
    table_top = bottom + label_height + 65
    cell_width = min(max(115, column_width), (width - name_width - 50) / n)
    table_left = (width - name_width - cell_width * n) / 2
    header_height = label_height + 16
    row_heights = [max(32, len(lines) * 17 + 12) for lines in names]
    height = table_top + header_height + sum(row_heights) + 25
    scene = []

    def add(kind, **attrs):
        scene.append((kind, attrs))

    def text(x, y, value, size=16, anchor="middle", color="#102039", weight="normal", rotation=0):
        add("text", x=x, y=y, text=str(value), size=size, anchor=anchor,
            color=color, weight=weight, rotation=rotation)

    def lines(x, center, values, **options):
        for index, value in enumerate(values):
            text(x, center + (index - (len(values) - 1) / 2) * 17, value, **options)

    maximum = max(row["array_count"] for row in rows)
    tick_step = max(1, math.ceil(maximum / 6))
    tick_max = math.ceil(maximum / tick_step) * tick_step
    scale = (bottom - top) / (tick_max * 1.12)
    for value in range(0, tick_max + 1, tick_step):
        y = bottom - value * scale
        add("line", x1=left - 6, y1=y, x2=left, y2=y, color="#102039")
        text(left - 12, y, value, anchor="end")
    add("line", x1=left, y1=top - 4, x2=left, y2=bottom, color="#102039")
    text(25, (top + bottom) / 2, "Number of arrays", size=18, rotation=-90)
    text((left + right) / 2, bottom + label_height + 34, "Spacer ID", size=18)
    for index, (row, label) in enumerate(zip(rows, labels)):
        color = colors[index]
        x = left + (index + 0.5) * step
        bar_height = row["array_count"] * scale
        add("rect", x=x - step * .32, y=bottom - bar_height, width=step * .64,
            height=bar_height, fill=color, stroke="none")
        text(x, bottom - bar_height - 15, row["array_count"], size=19, weight="bold")
        add("line", x1=x, y1=bottom, x2=x, y2=bottom + 6, color="#102039")
        lines(x, bottom + 15 + label_height / 2, label)

    # SVG uses drawing order: paint the baseline after the bars so their fills
    # cannot cover its upper half at y=bottom.
    add("line", x1=left, y1=bottom, x2=right, y2=bottom, color="#102039")

    def cell(x, y, w, h, fill):
        add("rect", x=x, y=y, width=w, height=h, fill=fill, stroke="#b7bcc5")

    cell(table_left, table_top, name_width, header_height, "#f3f3f3")
    for index, label in enumerate(labels):
        x = table_left + name_width + index * cell_width
        cell(x, table_top, cell_width, header_height, colors[index])
        lines(x + cell_width / 2, table_top + header_height / 2, label,
              color=_header_text_color(colors[index]), size=15)
    y = table_top + header_height
    for (name, spacers), label, row_height in zip(arrays.items(), names, row_heights):
        present = set(spacers)
        cell(table_left, y, name_width, row_height, "#f3f3f3")
        lines(table_left + name_width / 2, y + row_height / 2, label, size=15)
        for index, row in enumerate(rows):
            x = table_left + name_width + index * cell_width
            cell(x, y, cell_width, row_height, "white")
            exists = row["spacer_id"] in present
            color = colors[index]
            add("circle", x=x + cell_width / 2, y=y + row_height / 2, radius=8,
                fill=color if exists else "white", stroke=color if exists else "#858c98")
        y += row_height
    return width, height, scene


def _svg(width, height, scene):
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {width} {height}",
                              "width": str(width), "height": str(height), "role": "img",
                              "aria-label": "Spacer occurrence: number of arrays and presence/absence matrix"})
    ET.SubElement(root, "desc").text = "Filled circles indicate presence; hollow circles indicate absence. Each array counts once per spacer."
    ET.SubElement(root, "rect", {"width": "100%", "height": "100%", "fill": "white"})
    for kind, attrs in scene:
        a = dict(attrs)
        if kind == "text":
            value = a.pop("text")
            angle = a.pop("rotation")
            a.update({"font-size": a.pop("size"), "text-anchor": a.pop("anchor"),
                      "fill": a.pop("color"), "font-weight": a.pop("weight"),
                      "font-family": "Arial, sans-serif", "dominant-baseline": "central"})
            if angle:
                a["transform"] = f"rotate({angle} {a['x']} {a['y']})"
            ET.SubElement(root, kind, {k: str(v) for k, v in a.items()}).text = value
        else:
            if kind == "line":
                a["stroke"] = a.pop("color")
            if kind == "circle":
                a["cx"], a["cy"], a["r"] = a.pop("x"), a.pop("y"), a.pop("radius")
            ET.SubElement(root, kind, {k: str(v) for k, v in a.items()})
    return ET.tostring(root, encoding="utf-8")


def export_spacer_occurrence(arrays, output_format="svg", dpi=300):
    fmt = output_format.lower().strip()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError("Unsupported occurrence export format.")
    if not 36 <= dpi <= 2400:
        raise ValueError("DPI must be between 36 and 2400.")
    stats = spacer_occurrence_stats(arrays)
    width, height, scene = _scene(arrays, stats)
    if fmt == "svg":
        return _svg(width, height, scene), EXPORT_MEDIA_TYPES[fmt], fmt, stats
    if fmt not in {"pdf", "eps", "ps"} and width * height * (dpi / 96) ** 2 > MAX_RASTER_PIXELS:
        raise ValueError("This raster image exceeds 40 megapixels. Lower the DPI or choose SVG/PDF.")
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle, Rectangle
    # Use isolated figures, without pyplot's shared current figure state.
    fig = Figure(figsize=(width / 96, height / 96), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1], xlim=(0, width), ylim=(height, 0))
    ax.axis("off")
    for kind, a in scene:
        if kind == "text":
            ax.text(a["x"], a["y"], a["text"], fontsize=a["size"] * .75, color=a["color"],
                    weight=a["weight"], rotation=-a["rotation"], rotation_mode="anchor",
                    ha={"middle": "center", "end": "right"}.get(a["anchor"], "left"),
                    va="center", fontfamily="DejaVu Sans", parse_math=False, zorder=3)
        elif kind == "line":
            ax.plot([a["x1"], a["x2"]], [a["y1"], a["y2"]], color=a["color"], linewidth=.75, zorder=2)
        else:
            shape = (Circle((a["x"], a["y"]), a["radius"]) if kind == "circle" else
                     Rectangle((a["x"], a["y"]), a["width"], a["height"]))
            shape.set(facecolor=a["fill"], edgecolor=a["stroke"], linewidth=.75, zorder=1)
            ax.add_patch(shape)
    try:
        buffer = BytesIO()
        fig.savefig(buffer, format={"jpg": "jpeg", "tif": "tiff"}.get(fmt, fmt), dpi=dpi)
        return buffer.getvalue(), EXPORT_MEDIA_TYPES[fmt], fmt, stats
    finally:
        fig.clear()
