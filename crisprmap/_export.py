"""Shared export adapter for matplotlib figures."""
from io import BytesIO

from .spacermap import EXPORT_MEDIA_TYPES, SUPPORTED_EXPORT_FORMATS


def export_figure(fig, summary, output_format="svg", dpi=300):
    try:
        fmt = output_format.lower().strip()
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            raise ValueError(f"Unsupported export format: {output_format}")
        if not 36 <= dpi <= 2400:
            raise ValueError("DPI must be between 36 and 2400.")
        buffer = BytesIO()
        fig.savefig(buffer, format={"jpg": "jpeg", "tif": "tiff"}.get(fmt, fmt),
                    dpi=dpi, bbox_inches="tight")
        return buffer.getvalue(), EXPORT_MEDIA_TYPES[fmt], fmt, summary
    finally:
        fig.clear()
