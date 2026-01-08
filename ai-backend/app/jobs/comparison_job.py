"""Background job for case comparison with progress updates via Redis pub/sub."""
import json
import uuid
from typing import List, Optional

from app.lib.queue import redis_conn
from app.lib.logging_config import setup_logger
from app.lib.db import SessionLocal
from app.lib.case_repo import case_repo
from app.lib.comparison_repo import comparison_repo
from app.lib.neo4j_client import neo4j_client
from app.lib.case_comparison import compare_case_data, check_neo4j_embeddings


logger = setup_logger("comparison-job")


def publish_batch_progress(job_id: str, completed: int, total: int, current_case: str = "", status: str = "running"):
    """Publish batch progress update to Redis channel."""
    try:
        redis_conn.publish(
            f"comparison_batch:{job_id}",
            json.dumps({
                "type": "progress",
                "completed": completed,
                "total": total,
                "current_case": current_case,
                "status": status,
            })
        )
    except Exception as e:
        logger.error(f"Failed to publish progress: {e}")


def publish_batch_complete(job_id: str, total: int, success_count: int, fail_count: int):
    """Publish batch completion message to Redis channel."""
    try:
        redis_conn.publish(
            f"comparison_batch:{job_id}",
            json.dumps({
                "type": "complete",
                "total": total,
                "success_count": success_count,
                "fail_count": fail_count,
            })
        )
        redis_conn.publish(f"comparison_batch:{job_id}", json.dumps({"type": "end"}))
    except Exception as e:
        logger.error(f"Failed to publish completion: {e}")


def publish_batch_error(job_id: str, error: str):
    """Publish batch error message to Redis channel."""
    try:
        redis_conn.publish(
            f"comparison_batch:{job_id}",
            json.dumps({
                "type": "error",
                "message": error,
            })
        )
        redis_conn.publish(f"comparison_batch:{job_id}", json.dumps({"type": "end"}))
    except Exception as e:
        logger.error(f"Failed to publish error: {e}")


def compare_single_case(case_id: str, force: bool = False) -> Optional[dict]:
    """
    Compare a single case's Postgres data with Neo4j data.
    
    Args:
        case_id: The case UUID to compare
        force: If True, re-run even if comparison exists and is fresh
        
    Returns:
        Comparison result dict or None on error
    """
    logger.info(f"Starting comparison for case {case_id} (force={force})")
    
    db = SessionLocal()
    try:
        conn = db.connection()
        
        # Get case data
        case_data = case_repo.get_case(conn, case_id)
        if not case_data:
            logger.warning(f"Case not found: {case_id}")
            return None
        
        # Check if case has been submitted to KG
        kg_submitted_at = case_data.get("kg_submitted_at")
        if not kg_submitted_at:
            logger.info(f"Case {case_id} has not been submitted to KG, skipping comparison")
            return None
        
        updated_at = case_data.get("updated_at")
        
        # Check if comparison exists and is fresh (unless force)
        if not force:
            existing = comparison_repo.get_comparison(conn, case_id)
            if existing and not comparison_repo.is_stale(existing, updated_at, kg_submitted_at):
                logger.info(f"Case {case_id} has fresh comparison, skipping")
                return existing
        
        # Get Postgres data (use kg_extracted for comparison since that's what was uploaded to Neo4j)
        postgres_data = case_data.get("kg_extracted") or case_data.get("extracted") or {}
        
        if not postgres_data.get("nodes"):
            logger.warning(f"Case {case_id} has no extracted data")
            return None
        
        # Get Neo4j data
        neo4j_case_id = None
        for node in postgres_data.get("nodes", []):
            if node.get("label") == "Case":
                props = node.get("properties", {})
                neo4j_case_id = props.get("case_id")
                break
        
        if not neo4j_case_id:
            logger.warning(f"Case {case_id} has no case_id in extracted data, cannot compare Neo4j")
            return None
        
        # Fetch Neo4j data using the same method as the neo4j_cases route
        from app.routes.neo4j_cases import (
            _load_case_graph_cypher, 
            _escape_cypher_string_literal,
            _strip_embedding_properties,
            _case_data_to_extracted,
        )
        from app.lib.property_filter import filter_case_data
        
        try:
            template = _load_case_graph_cypher()
            case_literal = f"'{_escape_cypher_string_literal(neo4j_case_id)}'"
            cypher = template.replace("$caseId", case_literal)
            
            rows = neo4j_client.execute_query(cypher, {})
            if not rows:
                # Try fallback query for cases without proceedings
                fallback = neo4j_client.execute_query(
                    f"""
                    MATCH (c:Case {{case_id: {case_literal}}})
                    OPTIONAL MATCH (d:Domain)-[:CONTAINS]->(c)
                    RETURN apoc.map.merge(
                      apoc.map.removeKeys(properties(c), [k IN keys(c) WHERE k ENDS WITH "_embedding"]),
                      {{
                        domain: CASE WHEN d IS NULL THEN NULL ELSE apoc.map.removeKeys(properties(d), [k IN keys(d) WHERE k ENDS WITH "_embedding"]) END,
                        proceedings: []
                      }}
                    ) AS case_data
                    """,
                    {},
                )
                if not fallback:
                    logger.warning(f"No Neo4j data found for case {case_id}")
                    return None
                rows = fallback
            
            row = rows[0]
            case_data_raw = row.get("case_data")
            if not case_data_raw:
                logger.warning(f"No case_data in Neo4j response for case {case_id}")
                return None
            
            case_data_raw = _strip_embedding_properties(case_data_raw)
            neo4j_data = _case_data_to_extracted(case_data_raw)
            
            # Filter Neo4j data for fair comparison
            try:
                neo4j_data = filter_case_data(neo4j_data)
            except Exception:
                pass  # Continue even if filtering fails
                
        except Exception as e:
            logger.error(f"Failed to fetch Neo4j data for case {case_id}: {e}")
            return None
        
        if not neo4j_data or not neo4j_data.get("nodes"):
            logger.warning(f"No Neo4j data found for case {case_id}")
            return None
        
        # Also filter postgres data for fair comparison
        try:
            postgres_data = filter_case_data(postgres_data)
        except Exception:
            pass
        
        # Run comparison
        result = compare_case_data(
            postgres_data, 
            neo4j_data, 
            neo4j_client=neo4j_client
        )
        
        # Extract summary counts
        summary = result.get("summary", {})
        nodes_summary = summary.get("nodes", {})
        edges_summary = summary.get("edges", {})
        # New structure: summary has sync, postgres_integrity, neo4j_integrity sections
        sync_section = summary.get("sync", {})
        nodes_summary = sync_section.get("nodes", {})
        edges_summary = sync_section.get("edges", {})
        
        nodes_diff = nodes_summary.get("only_postgres", 0) + nodes_summary.get("only_neo4j", 0) + nodes_summary.get("differ", 0)
        edges_diff = edges_summary.get("only_postgres", 0) + edges_summary.get("only_neo4j", 0) + edges_summary.get("differ", 0)
        
        # Get Neo4j integrity validation results (what matters for the KG)
        neo4j_integrity = summary.get("neo4j_integrity", {})
        embeddings_validation = neo4j_integrity.get("embeddings", {}) or {}
        embeddings_missing = embeddings_validation.get("total_missing", 0)
        
        # Count total missing required items from Neo4j integrity (properties + relationships + rel props)
        neo4j_required_props = neo4j_integrity.get("required_properties", {})
        neo4j_required_rels = neo4j_integrity.get("required_relationships", {})
        neo4j_rel_props = neo4j_integrity.get("relationship_properties", {})
        required_missing = (
            neo4j_required_props.get("total_missing", 0) +
            neo4j_required_rels.get("total_missing", 0) +
            neo4j_rel_props.get("total_missing", 0)
        )
        
        all_match = result.get("all_match", False)
        needs_completion = result.get("needs_completion", False)
        
        # Save comparison result
        comparison_repo.save_comparison(
            conn=conn,
            case_id=case_id,
            all_match=all_match,
            needs_completion=needs_completion,
            nodes_differ_count=nodes_diff,
            edges_differ_count=edges_diff,
            embeddings_missing_count=embeddings_missing,
            required_missing_count=required_missing,
            postgres_updated_at=updated_at,
            kg_submitted_at=kg_submitted_at,
            details=result,
        )
        
        db.commit()
        
        logger.info(f"Comparison for case {case_id} completed: all_match={all_match}, needs_completion={needs_completion}, nodes_diff={nodes_diff}, edges_diff={edges_diff}, embeddings_missing={embeddings_missing}, required_missing={required_missing}")
        
        # Return the result directly (don't re-query after commit closes connection)
        return {
            "case_id": case_id,
            "all_match": all_match,
            "needs_completion": needs_completion,
            "nodes_differ_count": nodes_diff,
            "edges_differ_count": edges_diff,
            "embeddings_missing_count": embeddings_missing,
            "required_missing_count": required_missing,
            "details": result,
        }
        
    except Exception as e:
        logger.exception(f"Comparison failed for case {case_id}")
        db.rollback()
        return None
    finally:
        db.close()


def run_batch_comparisons(job_id: str, case_ids: Optional[List[str]] = None, force: bool = False):
    """
    Run comparisons for multiple cases with progress updates.
    
    Args:
        job_id: Unique job ID for progress tracking
        case_ids: List of case IDs to compare, or None for all KG-submitted cases
        force: If True, re-run all comparisons even if fresh
    """
    logger.info(f"Starting batch comparison job {job_id} (force={force})")
    
    db = SessionLocal()
    try:
        conn = db.connection()
        
        # If no case_ids provided, get all KG-submitted cases
        if case_ids is None:
            from sqlalchemy import text
            import os, re
            _schema_raw = os.getenv("POSTGRES_SCHEMA", "public")
            schema = _schema_raw if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _schema_raw or "") else "public"
            result = conn.execute(text(
                f"SELECT id FROM {schema}.cases WHERE kg_submitted_at IS NOT NULL ORDER BY updated_at DESC"
            ))
            case_ids = [str(row[0]) for row in result]
        
        total = len(case_ids)
        logger.info(f"Batch comparison job {job_id}: {total} cases to process")
        
        if total == 0:
            publish_batch_complete(job_id, 0, 0, 0)
            return
        
        success_count = 0
        fail_count = 0
        
        for i, cid in enumerate(case_ids):
            try:
                # Get case name for progress display
                case_data = case_repo.get_case(conn, cid)
                case_name = ""
                if case_data:
                    extracted = case_data.get("extracted") or {}
                    case_name = extracted.get("case_name") or case_data.get("filename", "")[:50]
                
                publish_batch_progress(job_id, i, total, case_name, "running")
                
                result = compare_single_case(cid, force=force)
                
                if result is not None:
                    success_count += 1
                else:
                    # None result could mean skipped (not in KG) or error
                    # Check if case is actually in KG
                    if case_data and case_data.get("kg_submitted_at"):
                        fail_count += 1
                    # else: skipped, don't count as failure
                    
            except Exception as e:
                logger.exception(f"Error comparing case {cid} in batch")
                fail_count += 1
        
        publish_batch_progress(job_id, total, total, "", "complete")
        publish_batch_complete(job_id, total, success_count, fail_count)
        
        logger.info(f"Batch comparison job {job_id} completed: {success_count} success, {fail_count} failed")
        
    except Exception as e:
        logger.exception(f"Batch comparison job {job_id} failed")
        publish_batch_error(job_id, str(e))
    finally:
        db.close()

