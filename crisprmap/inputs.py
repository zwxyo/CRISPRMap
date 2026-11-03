"""Local input normalization based on SpacerMap_pkg and crisprevo/spacer_input.

All sequence inputs are clustered together using Needleman-Wunsch identity.
Rendering continues to consume dictionaries of ordered spacer IDs.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from .spacermap import parse_spacer_arrays


@dataclass
class InputResult:
    arrays: dict[str, list[str]]
    mapping: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def array_text(self):
        return "".join(f"{name}\t{','.join(ids)}\n" for name, ids in self.arrays.items())

    def mapping_text(self):
        return "Spacer_ID\tSpacer_Sequence\n" + "".join(
            f"{label}\t{sequence}\n" for label, sequence in self.mapping
        )


def reverse_complement(sequence):
    return sequence.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


def _sequence(value, location):
    if not isinstance(value, str):
        raise ValueError(f"{location}: spacer sequence must be a string.")
    sequence = value.strip().upper()
    if not sequence or not re.fullmatch("[ACGTN]+", sequence):
        raise ValueError(f"{location}: expected a non-empty DNA sequence containing A/C/G/T/N.")
    return sequence


def _direction(value):
    value = str(value or "ND").strip().lower()
    if value in {"+", "pos", "positive", "forward"}:
        return "pos"
    if value in {"-", "neg", "negative", "reverse"}:
        return "neg"
    if value in {"nd", "unknown", ""}:
        return None
    raise ValueError(f"Unsupported orientation {value!r}; use +/-, pos/neg, or ND.")


def _csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV input requires a header.")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV input contains duplicate column names.")
        required = {"Seq_Name", "Orientation", "Spacer_Sequence"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV input is missing required columns: {', '.join(sorted(missing))}.")
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV line {line}: field count does not match the header.")
            rows.append({key: value.strip() for key, value in row.items()})
        return rows, "Reverse_Complement_Sequence" in reader.fieldnames


def _json_rows(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("Sequences"), list):
        raise ValueError("CRISPRCasFinder JSON requires a top-level Sequences list.")
    rows, skipped, seen = [], 0, set()
    for sequence in data["Sequences"]:
        if not isinstance(sequence, dict) or not isinstance(sequence.get("Crisprs", []), list):
            raise ValueError("Each JSON sequence must be an object with a Crisprs list.")
        organism = str(sequence.get("Description") or "").split(",", 1)[0]
        for crispr in sequence.get("Crisprs", []):
            if not isinstance(crispr, dict):
                raise ValueError("Each JSON Crisprs entry must be an object.")
            if str(crispr.get("Evidence_Level")) not in {"3", "4"}:
                skipped += 1
                continue
            name = crispr.get("Name")
            if not isinstance(name, str) or not name.strip() or name in seen:
                raise ValueError("Evidence-level 3/4 JSON arrays require unique non-empty Name fields.")
            seen.add(name)
            orientation = crispr.get("Potential_Orientation", "ND")
            if _direction(orientation) is None:
                orientation = crispr.get("CRISPRDirection", "ND")
            if not isinstance(crispr.get("Regions", []), list):
                raise ValueError("JSON Regions must be a list.")
            for region in crispr.get("Regions", []):
                if not isinstance(region, dict):
                    raise ValueError("Each JSON region must be an object.")
                if region.get("Type") == "Spacer":
                    rows.append({"Folder": path.stem, "Organism_Name": organism,
                                 "Seq_Name": crispr.get("Name") or "",
                                 "Orientation": orientation, "Spacer_Sequence": region.get("Sequence")})
    warnings = [f"Skipped {skipped} CRISPR array(s) below evidence level 3 or with missing evidence."] if skipped else []
    return rows, warnings


def _row_groups(rows, processed):
    groups, orientations, keys = {}, {}, {}
    normalized = []
    for index, row in enumerate(rows, 1):
        name = str(row.get("Seq_Name") or "").strip()
        folder = str(row.get("Folder") or "").strip()
        if not name or any(char in name + folder for char in "\t\r\n"):
            raise ValueError(f"Row {index}: Seq_Name must be non-empty; names cannot contain tabs/newlines.")
        sequence = _sequence(row.get("Spacer_Sequence"), f"Row {index}")
        organism = str(row.get("Organism_Name") or name).strip() or name
        normalized.append((folder, name, organism, _direction(row.get("Orientation")), sequence, row))
    # Match the prototype's N-containing organism exclusion, scoped by folder.
    invalid = {(folder, organism) for folder, _, organism, _, seq, _ in normalized if "N" in seq}
    skipped = 0
    for folder, name, organism, direction, sequence, row in normalized:
        if (folder, organism) in invalid or direction is None:
            skipped += 1
            continue
        label = f"{folder}_{name}" if folder else name
        key = (folder, name)
        if keys.setdefault(label, key) != key:
            raise ValueError(f"Array name collision after combining Folder and Seq_Name: {label!r}.")
        if orientations.setdefault(label, direction) != direction:
            raise ValueError(f"Array {label!r} contains conflicting orientations.")
        if direction == "neg":
            reverse = row.get("Reverse_Complement_Sequence")
            expected = reverse_complement(sequence)
            if reverse and _sequence(reverse, label) != expected:
                raise ValueError(f"Array {label!r}: Reverse_Complement_Sequence does not match Spacer_Sequence.")
            sequence = expected
        groups.setdefault(label, []).append(sequence)
    if not groups:
        raise ValueError("No usable spacer rows remain after ND/N filtering.")
    warnings = [f"Skipped {skipped} spacer row(s) with unknown orientation or from N-containing organisms."] if skipped else []
    # Processed CSV rows are already in display order; raw rows are genomic order.
    return groups, orientations, not processed, warnings


def _fasta_records(path):
    records, name, chunks = [], None, []

    def finish():
        if name is not None:
            records.append(_sequence("".join(chunks), f"{path.name}: {name}"))

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish()
            name, chunks = line[1:].strip(), []
            if not name:
                raise ValueError(f"{path.name}: empty FASTA header.")
        elif name is None:
            raise ValueError(f"{path.name}: FASTA must start with a >header.")
        else:
            chunks.append(line)
    finish()
    if not records:
        raise ValueError(f"{path.name}: no FASTA records found.")
    return records


def _folder_groups(path, fasta_sequences):
    groups, orientations = {}, {}
    files = sorted((p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".fa", ".fasta", ".fna"}),
                   key=lambda p: p.relative_to(path).as_posix())
    for file in files:
        relative = file.relative_to(path)
        parts = (path.name, *relative.parts[:-1])
        aliases = {"pos": "pos", "positive": "pos", "forward": "pos",
                   "neg": "neg", "negative": "neg", "reverse": "neg"}
        tokens = [token for part in parts for token in re.split(r"[_\s-]+", part.lower())]
        directions = {aliases[token] for token in tokens if token in aliases}
        if len(directions) != 1:
            raise ValueError(f"{relative}: expected exactly one pos/neg direction in its directory path.")
        direction = directions.pop()
        name = relative.with_suffix("").as_posix()
        if any(char in name for char in "\t\r\n"):
            raise ValueError("FASTA paths cannot contain tabs or newlines.")
        if name in groups:
            raise ValueError(f"Duplicate FASTA array name: {name!r}.")
        sequences = _fasta_records(file)
        if any("N" in sequence for sequence in sequences):
            raise ValueError(f"{relative}: ambiguous N bases are not supported in FASTA folders.")
        if direction == "neg" and fasta_sequences == "genomic":
            sequences = [reverse_complement(seq) for seq in sequences]
        groups[name], orientations[name] = sequences, direction
    if not groups:
        raise ValueError("No .fa/.fasta/.fna files found in the spacer folder.")
    return groups, orientations


def _number_groups(groups, orientations, reverse_negative, threshold):
    # Traverse positive arrays from right to left, as in id_assignment.py.
    entries = []
    for name, sequences in groups.items():
        indexes = range(len(sequences) - 1, -1, -1) if orientations[name] == "pos" else range(len(sequences))
        entries.extend((name, index, sequences[index]) for index in indexes)
    unique = list(dict.fromkeys(seq for _, _, seq in entries))
    parent = list(range(len(unique)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left, a in enumerate(unique):
        for right in range(left + 1, len(unique)):
            if _identity(a, unique[right]) >= threshold:
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left
    labels, by_sequence = {}, {}
    for index, sequence in enumerate(unique):
        root = find(index)
        labels.setdefault(root, str(len(labels) + 1))
        by_sequence[sequence] = labels[root]
    arrays = {name: [by_sequence[seq] for seq in sequences] for name, sequences in groups.items()}
    if reverse_negative:
        for name in arrays:
            if orientations[name] == "neg":
                arrays[name].reverse()
    mapping = sorted(((label, seq) for seq, label in by_sequence.items()), key=lambda pair: (int(pair[0]), pair[1]))
    return InputResult(arrays, mapping)


def load_input(path, input_format="auto", identity_threshold=.84, csv_mode="auto",
               fasta_sequences="oriented", fasta_order="genomic"):
    """Read text, spacer CSV, CRISPRCasFinder JSON, or an oriented FASTA folder.

    Folder defaults match id_assignment.py: bases already strand-normalized,
    records still in genomic order, with negative arrays reversed for display.
    """
    path = Path(path)
    if not 0 < identity_threshold <= 1:
        raise ValueError("Identity threshold must be greater than 0 and at most 1.")
    if csv_mode not in {"auto", "raw", "processed"}:
        raise ValueError("CSV mode must be auto, raw, or processed.")
    if fasta_sequences not in {"oriented", "genomic"} or fasta_order not in {"oriented", "genomic"}:
        raise ValueError("FASTA sequence/order modes must be oriented or genomic.")
    if input_format == "auto":
        input_format = "folder" if path.is_dir() else {".csv": "csv", ".json": "json"}.get(path.suffix.lower(), "text")
    if input_format == "text":
        return InputResult(parse_spacer_arrays(path.read_text(encoding="utf-8-sig")))
    warnings = []
    if input_format == "csv":
        rows, has_reverse_column = _csv_rows(path)
        processed = csv_mode == "processed" or (csv_mode == "auto" and has_reverse_column)
        groups, orientations, reverse_negative, warnings = _row_groups(rows, processed)
    elif input_format == "json":
        rows, warnings = _json_rows(path)
        groups, orientations, reverse_negative, filter_warnings = _row_groups(rows, False)
        warnings.extend(filter_warnings)
    elif input_format == "folder":
        if not path.is_dir():
            raise ValueError("Folder input requires a directory containing pos/neg FASTA files.")
        groups, orientations = _folder_groups(path, fasta_sequences)
        reverse_negative = fasta_order == "genomic"
    else:
        raise ValueError("Input format must be auto, text, csv, json, or folder.")
    result = _number_groups(groups, orientations, reverse_negative, identity_threshold)
    result.warnings = warnings
    return result


def _identity(seq1: str, seq2: str) -> float:
    # Needleman-Wunsch identity, matching id_assignment.py defaults.
    n, m = len(seq1), len(seq2)
    matrix = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        matrix[i][0] = i * -2
    for j in range(m + 1):
        matrix[0][j] = j * -2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            matrix[i][j] = max(
                matrix[i - 1][j - 1] + (1 if seq1[i - 1] == seq2[j - 1] else -1),
                matrix[i - 1][j] - 2,
                matrix[i][j - 1] - 2,
            )
    i, j, matches, length = n, m, 0, 0
    while i or j:
        score = matrix[i][j]
        diagonal = matrix[i - 1][j - 1] + (1 if seq1[i - 1] == seq2[j - 1] else -1) if i and j else None
        if i and j and score == diagonal:
            matches += seq1[i - 1] == seq2[j - 1]
            length += 1
            i, j = i - 1, j - 1
        elif i and score == matrix[i - 1][j] - 2:
            length += 1
            i -= 1
        else:
            length += 1
            j -= 1
    return matches / length if length else 0.0
