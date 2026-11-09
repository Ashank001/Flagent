"""
firestore.py — Google Firestore storage backend for Flagent (Spark free tier).

Collection layout:
    agents/{agent_id}                          — agent registry doc
    agents/{agent_id}/baselines/{cluster}      — one doc per cluster
    agents/{agent_id}/sessions/{session_id}    — session docs (timestamp indexed)

Credentials:
    1. FIREBASE_SERVICE_ACCOUNT_JSON env var (full JSON string, used on Render)
       → builds credentials in memory, NEVER writes to disk.
    2. GOOGLE_APPLICATION_CREDENTIALS env var (file path, local dev)
       → standard ADC fallback.

Quota-aware caching:
    In-process TTL cache on get_agent() and get_baseline() to stay within
    Spark read quotas (50k reads/day).  Write operations invalidate cache.
    TTL configurable via FIRESTORE_CACHE_TTL_SECONDS (default 60).
"""

import json
import os
import time

from storage.base import StorageBackend


def _build_firestore_client():
    """
    Build a Firestore client from available credentials.

    Priority:
        1. FIREBASE_SERVICE_ACCOUNT_JSON (JSON string in env → in-memory creds)
        2. GOOGLE_APPLICATION_CREDENTIALS (file path → standard ADC)
        3. Application Default Credentials (e.g. gcloud auth)
    """
    from google.cloud import firestore as fs

    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        from google.oauth2 import service_account
        info = json.loads(sa_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        project_id = os.environ.get(
            "FIREBASE_PROJECT_ID", info.get("project_id")
        )
        return fs.Client(project=project_id, credentials=credentials)

    # Fall back to GOOGLE_APPLICATION_CREDENTIALS or ADC
    project_id = os.environ.get("FIREBASE_PROJECT_ID")
    if project_id:
        return fs.Client(project=project_id)
    return fs.Client()


class _TTLCache:
    """Simple in-process TTL cache.  Thread-safe enough for single-worker."""

    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return val

    def set(self, key: str, value):
        self._store[key] = (time.time(), value)

    def invalidate(self, key: str):
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]


class FirestoreStorage(StorageBackend):
    """Firestore-backed storage (Spark free tier)."""

    def __init__(self):
        self._db = _build_firestore_client()
        ttl = int(os.environ.get("FIRESTORE_CACHE_TTL_SECONDS", "60"))
        self._cache = _TTLCache(ttl_seconds=ttl)
        # Root collection name (configurable for testing)
        self._root = os.environ.get("FIRESTORE_ROOT_COLLECTION", "agents")

    def _agents_col(self):
        return self._db.collection(self._root)

    # ── Agents ────────────────────────────────────────────────────────

    def create_agent(self, agent_id: str, data: dict) -> None:
        from google.cloud import firestore as fs
        doc_ref = self._agents_col().document(agent_id)

        # Conditional create via transaction
        @fs.transactional
        def txn_create(txn):
            snapshot = doc_ref.get(transaction=txn)
            if snapshot.exists:
                raise ValueError(f"Agent '{agent_id}' already exists")
            txn.set(doc_ref, data)

        txn_create(self._db.transaction())
        self._cache.invalidate(f"agent:{agent_id}")

    def get_agent(self, agent_id: str) -> dict | None:
        cache_key = f"agent:{agent_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        doc = self._agents_col().document(agent_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        self._cache.set(cache_key, data)
        return data

    def update_agent_status(self, agent_id: str, status: str) -> None:
        doc_ref = self._agents_col().document(agent_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise KeyError(f"Agent '{agent_id}' not found")
        doc_ref.update({"status": status})
        self._cache.invalidate(f"agent:{agent_id}")

    # ── Baselines ─────────────────────────────────────────────────────

    def put_baseline(self, agent_id: str, cluster: str,
                     fingerprint_data: dict) -> None:
        col = self._agents_col().document(agent_id).collection("baselines")
        col.document(cluster).set(fingerprint_data)
        self._cache.invalidate_prefix(f"baseline:{agent_id}")

    def get_baseline(self, agent_id: str, cluster: str) -> dict | None:
        cache_key = f"baseline:{agent_id}:{cluster}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        doc = (self._agents_col().document(agent_id)
               .collection("baselines").document(cluster).get())
        if not doc.exists:
            return None
        data = doc.to_dict()
        self._cache.set(cache_key, data)
        return data

    def get_all_baselines(self, agent_id: str) -> dict[str, dict]:
        docs = (self._agents_col().document(agent_id)
                .collection("baselines").stream())
        result = {}
        for doc in docs:
            result[doc.id] = doc.to_dict()
        return result

    # ── Sessions ──────────────────────────────────────────────────────

    def put_session(self, agent_id: str, session_id: str,
                    data: dict) -> None:
        save = {**data, "agent_id": agent_id, "session_id": session_id}
        (self._agents_col().document(agent_id)
         .collection("sessions").document(session_id).set(save))

    def get_session(self, agent_id: str,
                    session_id: str) -> dict | None:
        doc = (self._agents_col().document(agent_id)
               .collection("sessions").document(session_id).get())
        if not doc.exists:
            return None
        return doc.to_dict()

    def list_recent_sessions(self, agent_id: str,
                             limit: int = 20) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = (self._agents_col().document(agent_id)
                 .collection("sessions")
                 .order_by("created_at", direction="DESCENDING")
                 .limit(limit))
        return [doc.to_dict() for doc in query.stream()]

