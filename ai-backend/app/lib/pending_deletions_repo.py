"""Repository for pending KG deletion requests requiring admin approval."""

from typing import Any, Dict, List, Optional
from sqlalchemy import Table, Column, String, Text, DateTime, func, select, insert, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import Connection
import uuid


metadata = MetaData()


pending_kg_deletions = Table(
    "pending_kg_deletions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("case_id", UUID(as_uuid=True), nullable=False),
    Column("node_label", String, nullable=False),
    Column("node_id", String, nullable=False),  # the *_id property value
    Column("node_name", String),  # display name for admin UI
    Column("requested_by", String, nullable=False),
    Column("requested_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("status", String, nullable=False, server_default="pending"),  # pending, approved, rejected
    Column("resolved_by", String),
    Column("resolved_at", DateTime(timezone=True)),
)


class PendingDeletionsRepo:
    def create_deletion_request(
        self,
        conn: Connection,
        case_id: str,
        node_label: str,
        node_id: str,
        node_name: Optional[str],
        requested_by: str,
    ) -> str:
        """Create a pending deletion request and return its ID."""
        request_id = uuid.uuid4()
        conn.execute(
            insert(pending_kg_deletions).values(
                id=request_id,
                case_id=uuid.UUID(case_id),
                node_label=node_label,
                node_id=node_id,
                node_name=node_name,
                requested_by=requested_by,
                status="pending",
            )
        )
        return str(request_id)

    def list_pending(self, conn: Connection, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List pending deletion requests, optionally filtered by status."""
        stmt = select(pending_kg_deletions).order_by(pending_kg_deletions.c.requested_at.desc())
        if status:
            stmt = stmt.where(pending_kg_deletions.c.status == status)
        rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_by_id(self, conn: Connection, request_id: str) -> Optional[Dict[str, Any]]:
        """Get a deletion request by ID."""
        stmt = select(pending_kg_deletions).where(
            pending_kg_deletions.c.id == uuid.UUID(request_id)
        )
        row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def approve(self, conn: Connection, request_id: str, resolved_by: str) -> bool:
        """Approve a deletion request."""
        result = conn.execute(
            update(pending_kg_deletions)
            .where(pending_kg_deletions.c.id == uuid.UUID(request_id))
            .where(pending_kg_deletions.c.status == "pending")
            .values(status="approved", resolved_by=resolved_by, resolved_at=func.now())
        )
        return result.rowcount > 0

    def reject(self, conn: Connection, request_id: str, resolved_by: str) -> bool:
        """Reject a deletion request."""
        result = conn.execute(
            update(pending_kg_deletions)
            .where(pending_kg_deletions.c.id == uuid.UUID(request_id))
            .where(pending_kg_deletions.c.status == "pending")
            .values(status="rejected", resolved_by=resolved_by, resolved_at=func.now())
        )
        return result.rowcount > 0

    def check_existing_request(
        self, conn: Connection, node_label: str, node_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if there's already a pending request for this node."""
        stmt = (
            select(pending_kg_deletions)
            .where(pending_kg_deletions.c.node_label == node_label)
            .where(pending_kg_deletions.c.node_id == node_id)
            .where(pending_kg_deletions.c.status == "pending")
        )
        row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None


pending_deletions_repo = PendingDeletionsRepo()
