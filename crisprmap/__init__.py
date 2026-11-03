"""CRISPR array visualization for local, headless workflows."""

__version__ = "0.1.0"

from .spacermap import (
    build_cluster_network,
    build_spacermap_figure,
    build_spacermap_svg,
    export_spacermap_bytes,
    parse_spacer_arrays,
)
from .occurrence import export_spacer_occurrence, spacer_occurrence_stats
from .inputs import load_input, InputResult

__all__ = [
    "build_cluster_network", "build_spacermap_figure", "build_spacermap_svg",
    "export_spacermap_bytes", "parse_spacer_arrays", "export_spacer_occurrence",
    "spacer_occurrence_stats",
    "load_input", "InputResult",
]
