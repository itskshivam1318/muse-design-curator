"""Process-wide lock for the corpus embedding matrix (`embeddings.npy`) and its row numbers.

Writers hold it across read-top-row -> put -> flush -> commit so two runs never hand out the same
row; readers hold it while loading the file. `EmbeddingStore.flush` already replaces the file
atomically (temp + rename), so a reader never sees a half-written matrix.
"""

import threading
from typing import Any

import numpy as np

EMBEDDINGS_LOCK = threading.RLock()


def load_matrix(path: Any) -> np.ndarray:
    """Read the matrix under the lock (callers check `path.is_file()` first)."""
    with EMBEDDINGS_LOCK:
        return np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)
