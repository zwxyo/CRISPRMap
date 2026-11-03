"""Validation shared by file input and the public plotting functions."""


def validate_arrays(arrays):
    if not isinstance(arrays, dict) or not arrays:
        raise ValueError("Provide at least one named spacer array.")
    for name, row in arrays.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Array names must be non-empty strings.")
        if not isinstance(row, (list, tuple)) or not row:
            raise ValueError(f"Array {name!r} must contain at least one spacer ID.")
        if any(not isinstance(label, str) or not label.strip() for label in row):
            raise ValueError(f"Array {name!r} contains an empty or non-string spacer ID.")
