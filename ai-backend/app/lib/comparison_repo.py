"""Repository for case comparison results."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Boolean,
    Integer,
    MetaData,
    String,
    Table,
    select,
    delete,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.sql import func


metadata = MetaData()

case_comparisons = Table(
    "case_comparisons",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("case_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("compared_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("postgres_updated_at", DateTime(timezone=True), nullable=True),
    Column("kg_submitted_at", DateTime(timezone=True), nullable=True),
    Column("all_match", Boolean, nullable=False),
    Column("needs_completion", Boolean, default=False),
    Column("nodes_differ_count", Integer, default=0),
    Column("edges_differ_count", Integer, default=0),
    Column("embeddings_missing_count", Integer, default=0),
    Column("required_missing_count", Integer, default=0),
    Column("details", JSONB, nullable=True),
)


class ComparisonRepo:
    """Repository for managing case comparison results."""

    def save_comparison(
        self,
        conn: Connection,
        case_id: str,
        all_match: bool,
        needs_completion: bool = False,
        nodes_differ_count: int = 0,
        edges_differ_count: int = 0,
        embeddings_missing_count: int = 0,
        required_missing_count: int = 0,
        postgres_updated_at: Optional[datetime] = None,
        kg_submitted_at: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Upsert a comparison result for a case."""
        # Check if exists
        existing = self.get_comparison(conn, case_id)
        
        if existing:
            # Update existing
            from sqlalchemy import update
            conn.execute(
                update(case_comparisons)
                .where(case_comparisons.c.case_id == uuid.UUID(case_id))
                .values(
                    compared_at=func.now(),
                    all_match=all_match,
                    needs_completion=needs_completion,
                    nodes_differ_count=nodes_differ_count,
                    edges_differ_count=edges_differ_count,
                    embeddings_missing_count=embeddings_missing_count,
                    required_missing_count=required_missing_count,
                    postgres_updated_at=postgres_updated_at,
                    kg_submitted_at=kg_submitted_at,
                    details=details,
                )
            )
        else:
            # Insert new
            conn.execute(
                case_comparisons.insert().values(
                    id=uuid.uuid4(),
                    case_id=uuid.UUID(case_id),
                    all_match=all_match,
                    needs_completion=needs_completion,
                    nodes_differ_count=nodes_differ_count,
                    edges_differ_count=edges_differ_count,
                    embeddings_missing_count=embeddings_missing_count,
                    required_missing_count=required_missing_count,
                    postgres_updated_at=postgres_updated_at,
                    kg_submitted_at=kg_submitted_at,
                    details=details,
                )
            )
        
        return self.get_comparison(conn, case_id)

    def get_comparison(self, conn: Connection, case_id: str) -> Optional[Dict[str, Any]]:
        """Get comparison result for a single case."""
        stmt = select(case_comparisons).where(
            case_comparisons.c.case_id == uuid.UUID(case_id)
        )
        row = conn.execute(stmt).mappings().first()
        if row:
            return self._row_to_dict(row)
        return None

    def get_comparisons_for_cases(
        self, conn: Connection, case_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Batch fetch comparison results for multiple cases."""
        if not case_ids:
            return {}
        
        uuids = [uuid.UUID(cid) for cid in case_ids]
        stmt = select(case_comparisons).where(
            case_comparisons.c.case_id.in_(uuids)
        )
        rows = conn.execute(stmt).mappings().all()
        
        return {str(row["case_id"]): self._row_to_dict(row) for row in rows}

    def delete_comparison(self, conn: Connection, case_id: str) -> bool:
        """Delete comparison result for a case."""
        result = conn.execute(
            delete(case_comparisons).where(
                case_comparisons.c.case_id == uuid.UUID(case_id)
            )
        )
        return result.rowcount > 0

    def is_stale(
        self,
        comparison: Optional[Dict[str, Any]],
        case_updated_at: Optional[datetime],
        case_kg_submitted_at: Optional[datetime],
    ) -> bool:
        """
        Check if a comparison result is stale and needs re-running.
        
        A comparison is stale if:
        - No comparison exists
        - Postgres was updated after comparison ran
        - KG was re-submitted after comparison ran
        """
        if not comparison:
            return True
        
        compared_at = comparison.get("compared_at")
        if not compared_at:
            return True
        
        # If Postgres was updated after comparison
        if case_updated_at and case_updated_at > compared_at:
            return True
        
        # If KG was re-submitted after comparison
        if case_kg_submitted_at and case_kg_submitted_at > compared_at:
            return True
        
        return False

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a database row to a dictionary."""
        return {
            "id": str(row["id"]),
            "case_id": str(row["case_id"]),
            "compared_at": row["compared_at"],
            "postgres_updated_at": row["postgres_updated_at"],
            "kg_submitted_at": row["kg_submitted_at"],
            "all_match": row["all_match"],
            "needs_completion": row.get("needs_completion", False),
            "nodes_differ_count": row["nodes_differ_count"],
            "edges_differ_count": row["edges_differ_count"],
            "embeddings_missing_count": row["embeddings_missing_count"],
            "required_missing_count": row.get("required_missing_count", 0),
            "details": row["details"],
        }


# Singleton instance
comparison_repo = ComparisonRepo()

