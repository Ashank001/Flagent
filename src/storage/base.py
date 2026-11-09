"""
base.py — Abstract storage interface for Flagent.

Every backend (DynamoDB, Firestore, in-memory) implements this contract.
Handlers call get_storage() and use only these methods — never raw
boto3 or Firestore client calls.
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract base class for Flagent storage backends."""

    # ── Agent Registry ────────────────────────────────────────────────

    @abstractmethod
    def create_agent(self, agent_id: str, data: dict) -> None:
        """
        Create a new agent record.

        Args:
            agent_id: Unique agent identifier.
            data:     Dict with keys: name, api_key_hash, tool_categories,
                      status, mode_default, scoring_config, created_at.

        Raises:
            ValueError: If agent_id already exists.
        """

    @abstractmethod
    def get_agent(self, agent_id: str) -> dict | None:
        """
        Fetch an agent record by ID.

        Returns:
            Agent dict or None if not found.
        """

    @abstractmethod
    def update_agent_status(self, agent_id: str, status: str) -> None:
        """
        Update an agent's status field.

        Raises:
            KeyError: If agent_id does not exist.
        """

    # ── Baselines ─────────────────────────────────────────────────────

    @abstractmethod
    def put_baseline(self, agent_id: str, cluster: str,
                     fingerprint_data: dict) -> None:
        """
        Store a baseline fingerprint for one cluster.

        Args:
            agent_id:         Agent identifier.
            cluster:          Cluster name — "blended" or an intent name
                              (e.g. "retrieval", "modification").
            fingerprint_data: Dict with the fingerprint + metadata
                              (fingerprint, sample_count, min_cluster_samples,
                              scenario_count, source, created_at, …).
        """

    @abstractmethod
    def get_baseline(self, agent_id: str, cluster: str) -> dict | None:
        """
        Fetch a single baseline cluster for an agent.

        Returns:
            Baseline dict or None if not found.
        """

    @abstractmethod
    def get_all_baselines(self, agent_id: str) -> dict[str, dict]:
        """
        Fetch every baseline cluster for an agent.

        Returns:
            {cluster_name: baseline_dict, …}  (empty dict if none).
        """

    # ── Sessions ──────────────────────────────────────────────────────

    @abstractmethod
    def put_session(self, agent_id: str, session_id: str,
                    data: dict) -> None:
        """
        Store a scored session result.

        Args:
            agent_id:   Agent identifier.
            session_id: Unique session identifier.
            data:       Dict with score, classification, components, trace,
                        intent_cluster, baseline_used, created_at, …
        """

    @abstractmethod
    def get_session(self, agent_id: str,
                    session_id: str) -> dict | None:
        """
        Fetch a single session by agent_id + session_id.

        Returns:
            Session dict or None.
        """

    @abstractmethod
    def list_recent_sessions(self, agent_id: str,
                             limit: int = 20) -> list[dict]:
        """
        List recent sessions for an agent, newest first.

        Args:
            agent_id: Agent identifier.
            limit:    Max results (default 20).

        Returns:
            List of session dicts, ordered by created_at descending.
        """

