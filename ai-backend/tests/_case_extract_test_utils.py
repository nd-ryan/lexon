from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FakePydantic:
    """Minimal stand-in for a Pydantic model used in CrewAI results."""

    data: Dict[str, Any]

    def model_dump(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return dict(self.data)


@dataclass
class FakeCrewResult:
    """
    Minimal stand-in for CrewAI result objects.

    CaseExtractFlow checks for:
    - hasattr(result, 'pydantic')
    - hasattr(result, 'model_dump')
    - hasattr(result, 'raw')
    - str(result)
    """

    pydantic: Optional[Any] = None
    raw: Optional[Any] = None
    text: str = ""

    def __str__(self) -> str:  # pragma: no cover
        return self.text or (str(self.raw) if self.raw is not None else "")


