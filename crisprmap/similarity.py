"""Spacer-ID edit similarity, extracted from SpacerMap_test/SpacerMap_pkg."""


import itertools
import numpy as np
from .validation import validate_arrays


def levenshtein_distance(array1, array2):

    len1, len2 = len(array1), len(array2)

    # Allocate the dynamic programming matrix.
    dp = np.zeros((len1 + 1, len2 + 1), dtype=int)

    # Initialize the first row and column.
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j

    # Fill the matrix with minimum edit costs.
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if array1[i - 1] == array2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1,  # Deletion
                           dp[i][j - 1] + 1,  # Insertion
                           dp[i - 1][j - 1] + cost)  # Substitution

    return dp[len1][len2]


def levenshtein_similarity(array1, array2):
    if not array1 and not array2:
        return 1.0
    distance = levenshtein_distance(array1, array2)
    similarity = 1 - distance / max(len(array1), len(array2))
    return similarity


def compute_similarity_matrix(arrays) -> tuple[list[str], np.ndarray]:
    validate_arrays(arrays)

    names = list(arrays.keys())
    n = len(names)
    sim_matrix = np.zeros((n, n))

    for i, j in itertools.combinations(range(n), 2):
        sim = levenshtein_similarity(arrays[names[i]], arrays[names[j]])
        sim_matrix[i, j] = sim_matrix[j, i] = sim

    np.fill_diagonal(sim_matrix, 1.0)
    return names, sim_matrix


def build_similarity_figure(arrays):
    """Adapt array_order.plot_similarity_heatmap to an isolated, returned figure.

    Distance operates on ordered spacer IDs, not nucleotide sequences.
    """
    from matplotlib.figure import Figure

    names, matrix = compute_similarity_matrix(arrays)
    size = max(6, len(names) * 0.35)
    fig = Figure(figsize=(size + 2, size))
    ax = fig.subplots()
    image = ax.imshow(matrix, cmap="viridis_r", vmin=0, vmax=1,
                      interpolation="nearest", aspect="equal")
    ax.set_xticks(range(len(names)), labels=names, rotation=90)
    ax.set_yticks(range(len(names)), labels=names)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_parse_math(False)
    fig.colorbar(image, ax=ax, label="Levenshtein similarity")
    fig.tight_layout()
    return fig, {"array_count": len(names), "names": names,
                 "metric": "1 - spacer-ID edit distance / max array length",
                 "matrix": matrix.tolist()}


def export_similarity_heatmap(arrays, output_format="svg", dpi=300):
    from ._export import export_figure

    fig, summary = build_similarity_figure(arrays)
    return export_figure(fig, summary, output_format, dpi)
