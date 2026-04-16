"""
In-memory session store. Thread-safe.
Replace with Redis for multi-worker / multi-instance deployments.
"""
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from app.models.session import Session
from app.state_machine.states import State
from app.config import SESSION_TTL_MINUTES


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()

    def get_or_create(self, call_id: str, phone: str) -> Session:
        with self._lock:
            s = self._sessions.get(call_id)
            if s is not None:
                return s
            s = Session(
                call_id=call_id,
                phone=phone,
                current_state=State.GREETING.value,
            )
            self._sessions[call_id] = s
            return s

    def get(self, call_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(call_id)

    def save(self, session: Session) -> None:
        with self._lock:
            session.touch()
            self._sessions[session.call_id] = session

    def delete(self, call_id: str) -> None:
        with self._lock:
            self._sessions.pop(call_id, None)

    def all(self) -> List[Session]:
        with self._lock:
            return list(self._sessions.values())

    def cleanup_expired(self) -> int:
        cutoff = datetime.utcnow() - timedelta(minutes=SESSION_TTL_MINUTES)
        with self._lock:
            stale = [k for k, v in self._sessions.items() if v.updated_at < cutoff]
            for k in stale:
                del self._sessions[k]
            return len(stale)


# Module-level singleton
store = InMemorySessionStore()
