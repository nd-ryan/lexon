from typing import Any, Dict, List, Optional
from sqlalchemy import Table, Column, String, Text, DateTime, func, select, insert, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import Connection
import uuid
import time


metadata = MetaData()


cases = Table(
    "cases",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("filename", Text, nullable=False),
    Column("status", String, nullable=False, default="pending"),
    Column("extracted", JSONB),
    Column("schema_version", String),
    Column("revisions", JSONB, nullable=False, server_default='[]'),
    Column("meta", JSONB, nullable=False, server_default='{}'),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
)


class CaseRepo:
    def create_case(self, conn: Connection, filename: str) -> str:
        cid = uuid.uuid4()
        conn.execute(insert(cases).values(id=cid, filename=filename, status="pending"))
        return str(cid)

    def save_extraction(self, conn: Connection, case_id: str, data: Dict[str, Any]):
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(extracted=data, status="success", updated_at=func.now())
        )

    def list_cases(self, conn: Connection, q: Optional[str], limit: int, offset: int) -> List[Dict[str, Any]]:
        stmt = select(cases).order_by(cases.c.updated_at.desc()).limit(limit).offset(offset)
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def get_case(self, conn: Connection, case_id: str) -> Optional[Dict[str, Any]]:
        row = conn.execute(select(cases).where(cases.c.id == uuid.UUID(case_id))).mappings().first()
        return dict(row) if row else None

    def update_case(self, conn: Connection, case_id: str, payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        current = self.get_case(conn, case_id)
        revisions = (current.get("revisions") or []) + [{
            "timestamp": int(time.time()),
            "userId": user_id,
            "before": current.get("extracted") or {},
            "after": payload
        }]
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(extracted=payload, revisions=revisions, updated_at=func.now())
        )
        updated = self.get_case(conn, case_id)
        assert updated is not None
        return updated


case_repo = CaseRepo()


