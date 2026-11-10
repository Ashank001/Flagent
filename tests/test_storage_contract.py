"""
test_storage_contract.py — Storage interface contract tests.

Runs against MemoryStorage always.
Runs against FirestoreStorage only when FIRESTORE_LIVE_TEST=1
(uses a test-prefixed root collection, cleaned up afterwards).

Usage:
    # Memory only (default, CI-safe):
    python -m pytest tests/test_storage_contract.py -v

    # Include live Firestore:
    FIRESTORE_LIVE_TEST=1 python -m pytest tests/test_storage_contract.py -v
"""

import json
import os
import sys
import time
import pytest

# Ensure src/ is on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from storage.memory import MemoryStorage
from storage.factory import reset_storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _backends():
    """Yield backend instances to test against."""
    yield MemoryStorage()

    if os.environ.get("FIRESTORE_LIVE_TEST") == "1":
        from storage.firestore import FirestoreStorage
        # Use a test-prefixed root collection to isolate
        test_root = f"test_agents_{int(time.time())}"
        os.environ["FIRESTORE_ROOT_COLLECTION"] = test_root
        fs = FirestoreStorage()
        yield fs
        # Cleanup: delete all docs under the test root
        _cleanup_firestore(fs, test_root)
        del os.environ["FIRESTORE_ROOT_COLLECTION"]


def _cleanup_firestore(fs, root_col):
    """Delete all documents under the test root collection."""
    try:
        col = fs._db.collection(root_col)
        for doc in col.stream():
            # Delete subcollections first
            for subcol_name in ("baselines", "sessions"):
                subcol = doc.reference.collection(subcol_name)
                for subdoc in subcol.stream():
                    subdoc.reference.delete()
            doc.reference.delete()
    except Exception as e:
        print(f"WARNING: Firestore cleanup failed: {e}")


@pytest.fixture(params=list(_backends()), ids=lambda b: type(b).__name__)
def storage(request):
    """Parametrized fixture yielding each storage backend."""
    reset_storage()
    return request.param


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------

class TestAgentCRUD:
    def test_create_and_get_agent(self, storage):
        data = {
            "name": "Test Agent",
            "api_key_hash": "abc123hash",
            "tool_categories": {"lookup": "retrieval"},
            "status": "active",
            "mode_default": "shadow",
            "scoring_config": {"weights": {"volume": 0.45}},
            "created_at": "2026-01-01T00:00:00Z",
        }
        storage.create_agent("agent-1", data)
        got = storage.get_agent("agent-1")
        assert got is not None
        assert got["name"] == "Test Agent"
        assert got["api_key_hash"] == "abc123hash"
        assert got["status"] == "active"

    def test_get_missing_agent_returns_none(self, storage):
        assert storage.get_agent("nonexistent") is None

    def test_duplicate_create_raises(self, storage):
        data = {"name": "A", "status": "active", "created_at": "2026-01-01T00:00:00Z"}
        storage.create_agent("dup-agent", data)
        with pytest.raises(ValueError, match="already exists"):
            storage.create_agent("dup-agent", data)

    def test_update_agent_status(self, storage):
        data = {"name": "A", "status": "active", "created_at": "2026-01-01T00:00:00Z"}
        storage.create_agent("status-agent", data)
        storage.update_agent_status("status-agent", "inactive")
        got = storage.get_agent("status-agent")
        assert got["status"] == "inactive"

    def test_update_missing_agent_raises(self, storage):
        with pytest.raises(KeyError):
            storage.update_agent_status("ghost", "inactive")


# ---------------------------------------------------------------------------
# Baseline tests
# ---------------------------------------------------------------------------

class TestBaselines:
    def test_put_and_get_blended(self, storage):
        fp_data = {
            "fingerprint": {"tool_frequency": {"lookup": 0.9}},
            "min_cluster_samples": 5,
            "scenario_count": 10,
            "source": "test",
            "created_at": "2026-01-01T00:00:00Z",
        }
        storage.put_baseline("agent-bl", "blended", fp_data)
        got = storage.get_baseline("agent-bl", "blended")
        assert got is not None
        assert got["fingerprint"]["tool_frequency"]["lookup"] == 0.9

    def test_put_and_get_per_cluster(self, storage):
        storage.put_baseline("agent-cl", "retrieval", {
            "fingerprint": {"tool_frequency": {"search": 0.8}},
            "sample_count": 6,
            "created_at": "2026-01-01T00:00:00Z",
        })
        storage.put_baseline("agent-cl", "modification", {
            "fingerprint": {"tool_frequency": {"refund": 0.7}},
            "sample_count": 4,
            "created_at": "2026-01-01T00:00:00Z",
        })
        ret = storage.get_baseline("agent-cl", "retrieval")
        assert ret is not None
        assert ret["fingerprint"]["tool_frequency"]["search"] == 0.8

        mod = storage.get_baseline("agent-cl", "modification")
        assert mod is not None
        assert mod["fingerprint"]["tool_frequency"]["refund"] == 0.7

    def test_get_all_baselines(self, storage):
        storage.put_baseline("agent-all", "blended", {
            "fingerprint": {"tool_frequency": {"a": 0.5}},
            "min_cluster_samples": 5,
            "scenario_count": 10,
            "source": "test",
            "created_at": "2026-01-01T00:00:00Z",
        })
        storage.put_baseline("agent-all", "retrieval", {
            "fingerprint": {"tool_frequency": {"b": 0.3}},
            "sample_count": 5,
            "created_at": "2026-01-01T00:00:00Z",
        })
        all_bl = storage.get_all_baselines("agent-all")
        assert "blended" in all_bl
        assert "retrieval" in all_bl

    def test_get_missing_baseline_returns_none(self, storage):
        assert storage.get_baseline("ghost", "blended") is None

    def test_cache_invalidation_on_write(self, storage):
        """Writing a baseline should invalidate cached reads."""
        storage.put_baseline("agent-cache", "blended", {
            "fingerprint": {"tool_frequency": {"x": 0.1}},
            "created_at": "2026-01-01T00:00:00Z",
        })
        # Read to populate cache
        v1 = storage.get_baseline("agent-cache", "blended")
        assert v1["fingerprint"]["tool_frequency"]["x"] == 0.1

        # Overwrite
        storage.put_baseline("agent-cache", "blended", {
            "fingerprint": {"tool_frequency": {"x": 0.9}},
            "created_at": "2026-01-02T00:00:00Z",
        })
        v2 = storage.get_baseline("agent-cache", "blended")
        assert v2["fingerprint"]["tool_frequency"]["x"] == 0.9


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestSessions:
    def test_put_and_get_session(self, storage):
        storage.put_session("agent-s", "sess-1", {
            "score": 15.5,
            "classification": "normal",
            "created_at": "2026-01-01T00:00:01Z",
        })
        got = storage.get_session("agent-s", "sess-1")
        assert got is not None
        assert got["score"] == 15.5
        assert got["classification"] == "normal"

    def test_get_missing_session_returns_none(self, storage):
        assert storage.get_session("ghost", "sess-x") is None

    def test_list_recent_sessions_ordering_and_limit(self, storage):
        """Sessions should come back newest-first, respecting limit."""
        for i in range(5):
            storage.put_session("agent-order", f"sess-{i}", {
                "score": float(i),
                "classification": "normal",
                "created_at": f"2026-01-01T00:00:0{i}Z",
            })
        recent = storage.list_recent_sessions("agent-order", limit=3)
        assert len(recent) == 3
        # Newest first
        assert recent[0]["created_at"] == "2026-01-01T00:00:04Z"
        assert recent[1]["created_at"] == "2026-01-01T00:00:03Z"
        assert recent[2]["created_at"] == "2026-01-01T00:00:02Z"

    def test_list_sessions_empty(self, storage):
        assert storage.list_recent_sessions("no-sessions") == []


# ---------------------------------------------------------------------------
# Baseline file existence test
# ---------------------------------------------------------------------------

class TestBaselineFile:
    def test_canonical_baseline_file_exists(self):
        """src/data/baseline_output.json must exist and be valid."""
        path = os.path.join(_REPO_ROOT, "src", "data", "baseline_output.json")
        assert os.path.exists(path), (
            f"Canonical baseline file missing: {path}. "
            f"Legacy scoring and seeding will fail on deploy."
        )
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "fingerprint" in data, "baseline_output.json must have a 'fingerprint' key"
        fp = data["fingerprint"]
        assert "tool_frequency" in fp

    def test_baseline_resolves_from_handler_package_path(self):
        """Handler package path must resolve and read src/data/baseline_output.json."""
        from score_session import score_session
        handler_dir = os.path.dirname(os.path.abspath(score_session.__file__))
        package_root = os.path.dirname(handler_dir)
        baseline_path = os.path.join(package_root, "data", "baseline_output.json")
        assert os.path.exists(baseline_path), (
            f"Handler package cannot find baseline file at: {baseline_path}"
        )
        with open(baseline_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "fingerprint" in data, "baseline file in package path has no fingerprint"
        fp = data["fingerprint"]
        assert "avg_response_length" in fp
        assert "std_response_length" in fp

