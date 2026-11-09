"""
memory.py — In-memory storage backend for tests.

Thread-safe for single-process use.  Data lives only in the process.
"""

import copy
import threading
from storage.base import StorageBackend


class MemoryStorage(StorageBackend):
    """Dict-of-dicts storage backend for unit tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, dict] = {}
        self._baselines: dict[str, dict[str, dict]] = {}   # agent_id → {cluster → data}
        self._sessions: dict[str, dict[str, dict]] = {}    # agent_id → {session_id → data}

    # ── Agents ────────────────────────────────────────────────────────

    def create_agent(self, agent_id: str, data: dict) -> None:
        with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent '{agent_id}' already exists")
            self._agents[agent_id] = copy.deepcopy(data)

    def get_agent(self, agent_id: str) -> dict | None:
        with self._lock:
            item = self._agents.get(agent_id)
            return copy.deepcopy(item) if item else None

    def update_agent_status(self, agent_id: str, status: str) -> None:
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"Agent '{agent_id}' not found")
            self._agents[agent_id]["status"] = status

    # ── Baselines ─────────────────────────────────────────────────────

    def put_baseline(self, agent_id: str, cluster: str,
                     fingerprint_data: dict) -> None:
        with self._lock:
            if agent_id not in self._baselines:
                self._baselines[agent_id] = {}
            self._baselines[agent_id][cluster] = copy.deepcopy(fingerprint_data)

    def get_baseline(self, agent_id: str, cluster: str) -> dict | None:
        with self._lock:
            agent_bl = self._baselines.get(agent_id, {})
            item = agent_bl.get(cluster)
            return copy.deepcopy(item) if item else None

    def get_all_baselines(self, agent_id: str) -> dict[str, dict]:
        with self._lock:
            agent_bl = self._baselines.get(agent_id, {})
            return copy.deepcopy(agent_bl)

    # ── Sessions ──────────────────────────────────────────────────────

    def put_session(self, agent_id: str, session_id: str,
                    data: dict) -> None:
        with self._lock:
            if agent_id not in self._sessions:
                self._sessions[agent_id] = {}
            save = copy.deepcopy(data)
            save["session_id"] = session_id
            save["agent_id"] = agent_id
            self._sessions[agent_id][session_id] = save

    def get_session(self, agent_id: str,
                    session_id: str) -> dict | None:
        with self._lock:
            agent_sess = self._sessions.get(agent_id, {})
            item = agent_sess.get(session_id)
            return copy.deepcopy(item) if item else None

    def list_recent_sessions(self, agent_id: str,
                             limit: int = 20) -> list[dict]:
        with self._lock:
            agent_sess = self._sessions.get(agent_id, {})
            items = list(agent_sess.values())
            # Sort by created_at descending (ISO 8601 strings sort correctly)
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return copy.deepcopy(items[:limit])

