import threading
import time


class AuditStore:
    def __init__(self):
        self._store: list[dict] = []
        self._lock = threading.Lock()

    def append(self, agent_id: str, tool_name: str, params: dict,
               allowed: bool, reason: str, approval_status: str | None = None):
        with self._lock:
            self._store.append({
                "timestamp": time.time(),
                "agent_id": agent_id,
                "tool_name": tool_name,
                "parameters": dict(params),
                "allowed": allowed,
                "reason": reason,
                "approval_status": approval_status,
            })

    def ingest(self, timestamp: float, agent_id: str, tool_name: str,
               parameters: dict, allowed: bool, reason: str,
               approval_status: str | None = None):
        with self._lock:
            self._store.append({
                "timestamp": timestamp or time.time(),
                "agent_id": agent_id,
                "tool_name": tool_name,
                "parameters": parameters,
                "allowed": allowed,
                "reason": reason,
                "approval_status": approval_status,
            })

    def get_recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._store[-limit:])[::-1]


audit_store = AuditStore()


class OrchHistoryStore:
    def __init__(self, max_entries: int = 100):
        self._store: list[dict] = []
        self._lock = threading.Lock()
        self._max = max_entries

    def save(self, entry: dict):
        with self._lock:
            self._store.append(entry)
            if len(self._store) > self._max:
                self._store.pop(0)

    def get_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            entries = list(self._store[-limit:])
        return sorted(entries, key=lambda x: x["timestamp"], reverse=True)


orch_history = OrchHistoryStore()


class AgentMessageLog:
    def __init__(self, max_entries: int = 500):
        self._store: list[dict] = []
        self._lock = threading.Lock()
        self._max = max_entries

    def append(self, entry: dict):
        with self._lock:
            self._store.append(entry)
            if len(self._store) > self._max:
                self._store.pop(0)

    def get_recent(self, limit: int = 100) -> list[dict]:
        with self._lock:
            entries = list(self._store[-limit:])
        return sorted(entries, key=lambda x: x["timestamp"], reverse=True)


agent_msg_log = AgentMessageLog()
