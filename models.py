from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class DTRequest:
    request_id: str
    question: str
    raw_email_id: str
    timestamp: str
    extra_context: Optional[str] = None


@dataclass
class DTAnswer:
    request_id: str
    answer_text: str
    status: str  # "ok", "error", "needs_config"


@dataclass
class Config:
    configured: bool = False
    max_lines: int = 10
    detail_level: str = "medium"  # "short" | "medium" | "full"


Profile = Dict[str, str]
