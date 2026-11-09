"""
factory.py — Storage backend factory.

Selects backend based on env var STORAGE:
    - "memory"    → MemoryStorage     (tests, default for local dev)
    - "dynamodb"  → DynamoDBStorage   (AWS/SAM deployment)
    - "firestore" → FirestoreStorage  (Render free-tier deployment)

boto3 and google-cloud-firestore are imported LAZILY — only when the
matching backend is selected.
"""

import os

from storage.base import StorageBackend

# Module-level singleton (created on first call)
_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (singleton)."""
    global _instance
    if _instance is not None:
        return _instance

    backend = os.environ.get("STORAGE", "memory").lower()

    if backend == "dynamodb":
        from storage.dynamodb import DynamoDBStorage
        _instance = DynamoDBStorage()
    elif backend == "firestore":
        from storage.firestore import FirestoreStorage
        _instance = FirestoreStorage()
    elif backend == "memory":
        from storage.memory import MemoryStorage
        _instance = MemoryStorage()
    else:
        raise ValueError(
            f"Unknown STORAGE backend: '{backend}'. "
            f"Expected: memory, dynamodb, or firestore"
        )

    return _instance


def reset_storage() -> None:
    """Reset the singleton.  Used only in tests."""
    global _instance
    _instance = None

