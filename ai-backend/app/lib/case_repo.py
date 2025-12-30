from typing import Any, Dict, List, Optional
from sqlalchemy import Table, Column, String, Text, DateTime, func, select, insert, update, delete
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
    Column("kg_extracted", JSONB),
    Column("schema_version", String),
    Column("meta", JSONB, nullable=False, server_default='{}'),
    Column("original_author_id", String, nullable=True),  # set on upload, immutable
    Column("file_key", String, nullable=True),  # Tigris object storage key for original file
    Column("kg_submitted_by", String, nullable=True),
    Column("kg_submitted_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
)


class CaseRepo:
    def create_case(
        self,
        conn: Connection,
        filename: str,
        original_author_id: Optional[str] = None,
        file_key: Optional[str] = None,
    ) -> str:
        cid = uuid.uuid4()
        conn.execute(insert(cases).values(
            id=cid, 
            filename=filename, 
            status="pending",
            original_author_id=original_author_id,
            file_key=file_key,
        ))
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
        
        # Return minimal data for list view - extract only necessary fields
        result = []
        for row in rows:
            case_dict = dict(row)
            extracted = case_dict.get("extracted") or {}
            nodes = extracted.get("nodes", [])
            edges = extracted.get("edges", [])
            
            # Find Case node for case_name and its temp_id
            case_node = next(
                (n for n in nodes if n.get("label") == "Case"),
                None
            )
            case_name = None
            case_temp_id = None
            if case_node:
                if case_node.get("properties"):
                    case_name = case_node["properties"].get("name")
                case_temp_id = case_node.get("temp_id")
            
            # Find Domain via CONTAINS edge (Domain → Case)
            # The edge's 'from' field contains the domain_id (Neo4j ID)
            domain_id = None
            if case_temp_id:
                for edge in edges:
                    if isinstance(edge, dict) and edge.get("label") == "CONTAINS" and edge.get("to") == case_temp_id:
                        domain_id = edge.get("from")
                        break
            
            # Return minimal fields only
            result.append({
                "id": case_dict.get("id"),
                "filename": case_dict.get("filename"),
                "status": case_dict.get("status"),
                "extracted": {
                    "case_name": case_name
                },
                "domain_id": domain_id,  # Send domain_id instead of domain_name
                "has_file": bool(case_dict.get("file_key")),  # Whether original file is available
                "updated_at": case_dict.get("updated_at"),
                "kg_submitted_at": case_dict.get("kg_submitted_at"),
            })
        
        return result

    def get_case(self, conn: Connection, case_id: str) -> Optional[Dict[str, Any]]:
        row = conn.execute(select(cases).where(cases.c.id == uuid.UUID(case_id))).mappings().first()
        return dict(row) if row else None

    def update_case(self, conn: Connection, case_id: str, payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(extracted=payload, updated_at=func.now())
        )
        updated = self.get_case(conn, case_id)
        assert updated is not None
        return updated

    def delete_case(self, conn: Connection, case_id: str) -> bool:
        result = conn.execute(
            delete(cases).where(cases.c.id == uuid.UUID(case_id))
        )
        # Rowcount can be -1 depending on backend; treat >0 as deleted
        try:
            affected = result.rowcount or 0
        except Exception:
            affected = 0
        return affected > 0

    def set_kg_submitted(self, conn: Connection, case_id: str, user_id: str) -> None:
        """Set kg_submitted_by and kg_submitted_at on successful KG submit."""
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(kg_submitted_by=user_id, kg_submitted_at=func.now())
        )

    def set_kg_extracted(self, conn: Connection, case_id: str, payload: Dict[str, Any]) -> None:
        """Persist the last successfully published KG snapshot for this case.

        This stores the exact graph payload that was written to Neo4j (after ID assignment),
        so we can diff 'last published' vs 'new publish' during subsequent KG submits.
        """
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(kg_extracted=payload)
        )

    def set_file_key(self, conn: Connection, case_id: str, file_key: str) -> None:
        """Set the Tigris file_key for the uploaded document."""
        conn.execute(
            update(cases)
            .where(cases.c.id == uuid.UUID(case_id))
            .values(file_key=file_key)
        )


case_repo = CaseRepo()


