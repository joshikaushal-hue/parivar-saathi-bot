"""Dataclasses for in-memory call session state."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class LeadData:
    age: Optional[int] = None
    duration_months: Optional[int] = None
    prior_ivf: Optional[bool] = None
    prior_treatments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "age": self.age,
            "duration_months": self.duration_months,
            "prior_ivf": self.prior_ivf,
            "prior_treatments": self.prior_treatments,
        }


@dataclass
class Session:
    call_id: str
    phone: str
    current_state: str
    lead: LeadData = field(default_factory=LeadData)
    retry_count: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    score: Optional[int] = None
    category: Optional[str] = None

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()

    def record(self, role: str, text: str) -> None:
        self.history.append({
            "role": role,
            "text": text,
            "state": self.current_state,
            "ts": datetime.utcnow().isoformat(),
        })
        self.touch()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "phone": self.phone,
            "current_state": self.current_state,
            "retry_count": self.retry_count,
            "lead": self.lead.to_dict(),
            "score": self.score,
            "category": self.category,
            "turns": len(self.history),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
