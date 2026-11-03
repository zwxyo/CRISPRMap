"""Small file-based entry point; plotting functions remain independently usable."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .spacermap import export_spacermap_bytes, SUPPORTED_EXPORT_FORMATS
from .occurrence import export_spacer_occurrence, spacer_occurrence_stats
from .inputs import load_input


def make_parser():
    parser = argparse.ArgumentParser(prog="crisprmap", description="Plot ordered CRISPR spacer-ID arrays locally.")
    parser.add_argument("--version", action="version", version=f"CRISPRMap {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("map", "Spacer array boxes and shared-spacer links"),
        ("occurrence", "Spacer prevalence bars and presence/absence matrix"),
        ("heatmap", "Pairwise spacer-ID Levenshtein similarity"),
        ("network", "Pairwise clustering network"),
        ("stats", "Spacer prevalence statistics as JSON, with no chart limit"),
    ]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("-i", "--input", required=True, type=Path, help="Array text, spacer CSV, CRISPRCasFinder JSON, or pos/neg FASTA directory")
        cmd.add_argument("--input-format", choices=["auto", "text", "csv", "json", "folder"], default="auto")
        cmd.add_argument("--identity-threshold", type=float, default=.84,
                         help="Sequence clustering identity threshold in (0, 1], default: 0.84")
        cmd.add_argument("--csv-mode", choices=["auto", "raw", "processed"], default="auto",
                         help="Auto treats a Reverse_Complement_Sequence column as processed row order")
        cmd.add_argument("--fasta-sequences", choices=["oriented", "genomic"], default="oriented",
                         help="Folder bases already strand-normalized (default), or reverse-complement negative sequences")
        cmd.add_argument("--fasta-order", choices=["genomic", "oriented"], default="genomic",
                         help="Reverse negative FASTA record order (default), or preserve already oriented order")
        cmd.add_argument("--numbered-out", type=Path, help="Save normalized array IDs as reusable text")
        cmd.add_argument("--mapping-out", type=Path, help="Save ID-to-sequence TSV for sequence input")
        cmd.add_argument("-o", "--output", required=True, type=Path, help="Output file; image format is inferred from suffix")
        cmd.add_argument("--force", action="store_true", help="Overwrite existing output files")
        if name != "stats":
            cmd.add_argument("--format", choices=sorted(SUPPORTED_EXPORT_FORMATS), help="Explicit output image format")
            cmd.add_argument("--dpi", type=int, default=300)
            cmd.add_argument("--summary", type=Path, help="Also write plot statistics as JSON")
        if name in {"map", "network"}:
            cmd.add_argument("--seed", type=int, default=2, help="Non-negative color/layout seed")
            modes = ["shared-spacer", "ancestral-spacer"]
            cmd.add_argument("--cluster", choices=(["none"] + modes if name == "map" else modes),
                             default="none" if name == "map" else "shared-spacer")
        if name == "map":
            cmd.add_argument("--align", choices=["left", "right", "justify"], default="right")
    return parser


def _json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        outputs = [args.output]
        if getattr(args, "summary", None):
            outputs.append(args.summary)
        outputs.extend(path for path in (args.numbered_out, args.mapping_out) if path is not None)
        resolved = [path.resolve() for path in outputs]
        if args.input.resolve() in resolved or len(set(resolved)) != len(resolved):
            raise ValueError("Input and all output paths must be different.")
        if args.input.is_dir() and any(path.is_relative_to(args.input.resolve()) for path in resolved):
            raise ValueError("Write output files outside the input FASTA folder to protect source data.")
        for path in outputs:
            if path.exists() and not args.force:
                raise ValueError(f"Output already exists: {path}; use --force to overwrite.")
        normalized = load_input(args.input, input_format=args.input_format,
                                identity_threshold=args.identity_threshold, csv_mode=args.csv_mode,
                                fasta_sequences=args.fasta_sequences, fasta_order=args.fasta_order)
        arrays = normalized.arrays
        if args.mapping_out and not normalized.mapping:
            raise ValueError("ID-to-sequence mapping requires CSV, JSON, or FASTA folder input.")
        for message in normalized.warnings:
            print(f"crisprmap: warning: {message}", file=sys.stderr)
        if args.command == "stats":
            payload = _json_bytes(spacer_occurrence_stats(arrays))
            summary = None
        else:
            fmt = args.format or args.output.suffix.lstrip(".").lower()
            if fmt not in SUPPORTED_EXPORT_FORMATS:
                raise ValueError("Use a supported output suffix or specify --format.")
            if not 36 <= args.dpi <= 2400:
                raise ValueError("DPI must be between 36 and 2400.")
            if hasattr(args, "seed") and not 0 <= args.seed < 2**32:
                raise ValueError("Seed must be an integer between 0 and 4294967295.")
            options = dict(output_format=fmt, dpi=args.dpi)
            if args.command == "map":
                result = export_spacermap_bytes(arrays, align=args.align, cluster_mode=args.cluster,
                                                random_seed=args.seed, **options)
            elif args.command == "occurrence":
                result = export_spacer_occurrence(arrays, **options)
            elif args.command == "heatmap":
                from .similarity import export_similarity_heatmap
                result = export_similarity_heatmap(arrays, **options)
            else:
                from .network import export_cluster_network
                result = export_cluster_network(arrays, cluster_mode=args.cluster,
                                                random_seed=args.seed, **options)
            payload, _, _, summary = result
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
        if getattr(args, "summary", None):
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_bytes(_json_bytes(summary))
        for path, content in ((args.numbered_out, normalized.array_text()),
                              (args.mapping_out, normalized.mapping_text())):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        print(f"Wrote {args.output}")
        return 0
    except (OSError, ValueError, ImportError, RuntimeError) as exc:
        print(f"crisprmap: error: {exc}", file=sys.stderr)
        return 2
