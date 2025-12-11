"""Repository for graph event audit logging."""

from typing import Any, Dict, List, Optional
from sqlalchemy import Table, Column, String, Text, DateTime, func, select, insert, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import Connection
import uuid
import hashlib
import json
import re


metadata = MetaData()


graph_events = Table(
    "graph_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("case_id", UUID(as_uuid=True), nullable=False),
    Column("entity_type", String, nullable=False),  # "node" or "edge"
    Column("entity_id", Text, nullable=False),      # node temp_id or edge key (from:to:label)
    Column("entity_label", String, nullable=False), # node label or edge label
    Column("action", String, nullable=False),       # ai_create, create, update, delete
    Column("user_id", String, nullable=False),
    Column("content_hash", String),
    Column("property_changes", JSONB),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def compute_content_hash(properties: Dict[str, Any]) -> str:
    """Compute a hash of node/edge properties for change detection."""
    # Sort keys for consistent hashing
    sorted_json = json.dumps(properties, sort_keys=True, default=str)
    return hashlib.sha256(sorted_json.encode()).hexdigest()[:16]


def make_edge_id(from_id: str, to_id: str, label: str) -> str:
    """Create a composite key for an edge."""
    return f"{from_id}:{to_id}:{label}"


class GraphEventsRepo:
    def log_event(
        self,
        conn: Connection,
        case_id: str,
        entity_type: str,  # "node" or "edge"
        entity_id: str,
        entity_label: str,
        action: str,  # "ai_create", "create", "update", "delete"
        user_id: str,
        properties: Optional[Dict[str, Any]] = None,
        property_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log a graph event and return the event ID."""
        event_id = uuid.uuid4()
        # Always compute hash - use empty dict if None
        content_hash = compute_content_hash(properties if properties is not None else {})
        
        conn.execute(
            insert(graph_events).values(
                id=event_id,
                case_id=uuid.UUID(case_id),
                entity_type=entity_type,
                entity_id=entity_id,
                entity_label=entity_label,
                action=action,
                user_id=user_id,
                content_hash=content_hash,
                property_changes=property_changes,
            )
        )
        return str(event_id)

    def log_node_event(
        self,
        conn: Connection,
        case_id: str,
        node_temp_id: str,
        node_label: str,
        action: str,
        user_id: str,
        properties: Optional[Dict[str, Any]] = None,
        property_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log a node event."""
        return self.log_event(
            conn=conn,
            case_id=case_id,
            entity_type="node",
            entity_id=node_temp_id,
            entity_label=node_label,
            action=action,
            user_id=user_id,
            properties=properties,
            property_changes=property_changes,
        )

    def log_edge_event(
        self,
        conn: Connection,
        case_id: str,
        from_id: str,
        to_id: str,
        edge_label: str,
        action: str,
        user_id: str,
        properties: Optional[Dict[str, Any]] = None,
        property_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log an edge event."""
        edge_id = make_edge_id(from_id, to_id, edge_label)
        return self.log_event(
            conn=conn,
            case_id=case_id,
            entity_type="edge",
            entity_id=edge_id,
            entity_label=edge_label,
            action=action,
            user_id=user_id,
            properties=properties,
            property_changes=property_changes,
        )

    def get_events_for_case(self, conn: Connection, case_id: str) -> List[Dict[str, Any]]:
        """Get all events for a case, ordered by creation time."""
        stmt = (
            select(graph_events)
            .where(graph_events.c.case_id == uuid.UUID(case_id))
            .order_by(graph_events.c.created_at.desc())
        )
        rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_events_for_entity(self, conn: Connection, entity_id: str) -> List[Dict[str, Any]]:
        """Get all events for a specific node or edge."""
        stmt = (
            select(graph_events)
            .where(graph_events.c.entity_id == entity_id)
            .order_by(graph_events.c.created_at.desc())
        )
        rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def list_events(
        self,
        conn: Connection,
        case_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List events with optional filters."""
        stmt = select(graph_events)
        
        if case_id:
            stmt = stmt.where(graph_events.c.case_id == uuid.UUID(case_id))
        if user_id:
            stmt = stmt.where(graph_events.c.user_id == user_id)
        if action:
            stmt = stmt.where(graph_events.c.action == action)
        if entity_type:
            stmt = stmt.where(graph_events.c.entity_type == entity_type)
        
        stmt = stmt.order_by(graph_events.c.created_at.desc()).limit(limit).offset(offset)
        rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_event_stats(self, conn: Connection) -> Dict[str, Any]:
        """Get summary statistics for events."""
        from sqlalchemy import func as sql_func
        
        # Count by action
        action_counts = {}
        stmt = select(
            graph_events.c.action,
            sql_func.count().label("count")
        ).group_by(graph_events.c.action)
        for row in conn.execute(stmt).mappings().all():
            action_counts[row["action"]] = row["count"]
        
        # Count by user
        user_counts = {}
        stmt = select(
            graph_events.c.user_id,
            sql_func.count().label("count")
        ).group_by(graph_events.c.user_id).order_by(sql_func.count().desc()).limit(10)
        for row in conn.execute(stmt).mappings().all():
            user_counts[row["user_id"]] = row["count"]
        
        # Total count
        stmt = select(sql_func.count()).select_from(graph_events)
        total = conn.execute(stmt).scalar() or 0
        
        return {
            "total": total,
            "by_action": action_counts,
            "top_users": user_counts,
        }

    def update_entity_ids_for_case(
        self,
        conn: Connection,
        case_id: str,
        id_mapping: Dict[str, str],
    ) -> int:
        """Update entity_ids for a case when temp_ids are replaced with UUIDs.
        
        This is called after KG submit to ensure event history uses consistent identifiers.
        
        Args:
            conn: Database connection
            case_id: The case ID
            id_mapping: Dict mapping old temp_id → new UUID
            
        Returns:
            Number of events updated
        """
        if not id_mapping:
            return 0
        
        # Get all events for this case
        events = self.get_events_for_case(conn, case_id)
        updated_count = 0
        
        for event in events:
            old_entity_id = event.get("entity_id", "")
            entity_type = event.get("entity_type", "")
            new_entity_id = None
            
            if entity_type == "node":
                # Direct mapping for nodes
                if old_entity_id in id_mapping:
                    new_entity_id = id_mapping[old_entity_id]
            elif entity_type == "edge":
                # Edge entity_id format: "from:to:label"
                # Need to update from and to parts
                parts = old_entity_id.split(":")
                if len(parts) >= 3:
                    from_id = parts[0]
                    to_id = parts[1]
                    label = ":".join(parts[2:])  # Handle labels with colons
                    
                    new_from = id_mapping.get(from_id, from_id)
                    new_to = id_mapping.get(to_id, to_id)
                    
                    if new_from != from_id or new_to != to_id:
                        new_entity_id = f"{new_from}:{new_to}:{label}"
            
            if new_entity_id and new_entity_id != old_entity_id:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Updating event {event['id']}: {old_entity_id} -> {new_entity_id}")
                conn.execute(
                    update(graph_events)
                    .where(graph_events.c.id == event["id"])
                    .values(entity_id=new_entity_id)
                )
                updated_count += 1
        
        return updated_count


graph_events_repo = GraphEventsRepo()
