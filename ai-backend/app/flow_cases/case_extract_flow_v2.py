from crewai.flow.flow import Flow, listen, start
from crewai import Crew, Process
from pydantic import BaseModel, Field, create_model
from typing import Dict, Any, List, Optional
from .crews.case_crew.case_crew import CaseCrew
from .tools.io_tools import read_document, fetch_neo4j_schema
from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models, validate_case_graph, render_spec_text, build_relationship_property_models, get_relationship_label_for_edge, get_all_assigned_relationship_labels
from app.models.case_graph import CaseGraph
from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
import json
from datetime import datetime


logger = setup_logger("case-extract-flow-v2")


class CaseExtractState(BaseModel):
    file_path: str = ""
    filename: str = ""
    case_id: str = ""
    # Progress callback for job tracking
    progress_callback: Any = None  # Callable[[str, str, int], None] but Any for Pydantic
    # Runtime additions shared across flow steps
    schema_spec: Dict[str, Any] | None = None
    schema_spec_text: str = ""
    models_by_label: Dict[str, Any] | None = None
    rels_by_label: Dict[str, Dict[str, str]] | None = None
    props_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]] | None = None
    label_flags_by_label: Dict[str, Dict[str, bool]] | None = None
    # Relationship property validators keyed by (source_label, rel_label)
    rel_prop_models_by_key: Dict[tuple[str, str], Any] | None = None
    rel_prop_meta_by_key: Dict[tuple[str, str], Dict[str, Dict[str, Any]]] | None = None
    # Full schema payload (with relationship property schemas) if available
    schema_full: Any | None = None
    existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] | None = None
    # Working context
    document_text: str = ""
    nodes_accumulated: List[Dict[str, Any]] | None = None
    edges_accumulated: List[Dict[str, Any]] | None = None


class CaseExtractFlow(Flow[CaseExtractState]):
    @start()
    def phase0_kickoff(self) -> Dict[str, Any]:
        # Log initial kickoff context
        try:
            logger.info(f"Kickoff: file_path='{self.state.file_path}', filename='{self.state.filename}', case_id='{self.state.case_id}'")
        except Exception:
            pass
        return {
            "file_path": self.state.file_path,
            "filename": self.state.filename,
            "case_id": self.state.case_id,
            "status": "initialized"
        }

    @listen(phase0_kickoff)
    def phase0_prepare_schema(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("prepare_schema: starting")
        print("[prepare_schema] starting")
        # Build pruned spec and models up front so we can pass spec to the crew
        try:
            schema_res = fetch_neo4j_schema()
            schema_payload = schema_res.get('schema') if isinstance(schema_res, dict) else None
        except Exception:
            schema_payload = None

        spec = prune_ui_schema_for_llm(schema_payload) if schema_payload is not None else {"labels": []}
        models_by_label, rels_by_label, props_meta_by_label, label_flags_by_label = build_property_models(spec)
        spec_text = render_spec_text(spec)
        # Persist on state for later listeners
        self.state.schema_spec = spec
        self.state.schema_spec_text = spec_text
        self.state.models_by_label = models_by_label
        self.state.rels_by_label = rels_by_label
        self.state.props_meta_by_label = props_meta_by_label
        self.state.label_flags_by_label = label_flags_by_label
        # Relationship property models from full schema when available
        try:
            rel_models, rel_meta = build_relationship_property_models(schema_payload)
            self.state.rel_prop_models_by_key = rel_models  # type: ignore[assignment]
            self.state.rel_prop_meta_by_key = rel_meta  # type: ignore[assignment]
        except Exception:
            self.state.rel_prop_models_by_key = {}
            self.state.rel_prop_meta_by_key = {}
        self.state.schema_full = schema_payload

        # Read document once and store text
        try:
            logger.info(f"Reading document: file_path='{self.state.file_path}', filename='{self.state.filename}'")
            
            # Add file existence check with detailed logging
            import os
            if not os.path.exists(self.state.file_path):
                error_msg = f"File not found: {self.state.file_path}"
                logger.error(error_msg)
                logger.error(f"Current working directory: {os.getcwd()}")
                logger.error(f"Directory contents: {os.listdir(os.path.dirname(self.state.file_path) if os.path.dirname(self.state.file_path) else '.')}")
                self.state.document_text = ""
                return ctx
            
            file_size = os.path.getsize(self.state.file_path)
            logger.info(f"File exists, size: {file_size} bytes")
            
            doc_res = read_document(self.state.file_path, self.state.filename)
            logger.info(f"Document read result type: {type(doc_res)}, is_dict: {isinstance(doc_res, dict)}")
            if isinstance(doc_res, dict):
                logger.info(f"Document read result keys: {list(doc_res.keys())}, ok={doc_res.get('ok')}")
                if doc_res.get("ok"):
                    text_content = doc_res.get("text") or ""
                    self.state.document_text = str(text_content)
                    logger.info(f"Document text loaded successfully, length: {len(self.state.document_text)}")
                else:
                    error_msg = doc_res.get("error", "Unknown error")
                    logger.error(f"Document read failed: {error_msg}")
                    self.state.document_text = ""
            else:
                logger.warning(f"Document read returned unexpected type: {type(doc_res)}")
                self.state.document_text = ""
        except Exception as e:
            logger.error(f"Exception while reading document: {e}", exc_info=True)
            self.state.document_text = ""

        # Build existing catalogs for:
        # - labels where can_create_new is False 
        # - labels where case_unique is False and can_create_new is True
        try:
            existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] = {}
            for ldef in (spec.get("labels") if isinstance(spec, dict) else []) or []:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str):
                    continue
                flags = (label_flags_by_label or {}).get(lbl, {})
                if flags.get("ai_ignore"):
                    continue
                # Skip preloading Party catalog; phase 8 performs on-demand fuzzy lookup
                if lbl == "Party":
                    continue
                should_fetch = False
                try:
                    is_creatable = flags.get("can_create_new") is True
                    is_non_creatable = flags.get("can_create_new") is False
                    is_case_unique = flags.get("case_unique") is True

                    if is_non_creatable:
                        should_fetch = True
                    elif (not is_case_unique) and is_creatable:
                        should_fetch = True
                except Exception:
                    should_fetch = False

                if should_fetch:
                    # Project common identifier props
                    props = [p.get("name") for p in (ldef.get("properties") or []) if isinstance(p, dict) and isinstance(p.get("name"), str)]
                    projection = "properties(n) AS props" if not props else "properties(n) AS props"
                    query = f"MATCH (n:`{lbl}`) RETURN {projection} LIMIT 1000"
                    try:
                        rows = neo4j_client.execute_query(query)
                        cleaned: List[Dict[str, Any]] = []
                        for r in rows:
                            props_map = r.get("props") if isinstance(r.get("props"), dict) else None
                            if props_map is None:
                                # If direct properties were returned
                                props_map = {k: v for k, v in r.items() if k != "props"}
                            if isinstance(props_map, dict):
                                cleaned.append(props_map)
                        existing_catalog_by_label[lbl] = cleaned
                    except Exception as e:
                        logger.error(f"Failed to fetch existing catalog for {lbl}: {e}")
                        existing_catalog_by_label[lbl] = []
            self.state.existing_catalog_by_label = existing_catalog_by_label
        except Exception as e:
            logger.warning(f"existing catalog fetch failed: {e}")
            self.state.existing_catalog_by_label = {}

        # Init accumulators
        self.state.nodes_accumulated = []
        self.state.edges_accumulated = []
        try:
            labels_cnt = len((self.state.schema_spec or {}).get("labels", [])) if isinstance(self.state.schema_spec, dict) else 0
            doc_len = len(self.state.document_text or "")
            catalog_cnt = len(self.state.existing_catalog_by_label or {}) if isinstance(self.state.existing_catalog_by_label, dict) else 0
            logger.info(f"prepare_schema: completed (labels={labels_cnt}, doc_len={doc_len}, catalogs={catalog_cnt})")
        except Exception:
            logger.info("prepare_schema: completed")
        print("[prepare_schema] completed")
        return ctx

    @listen(phase0_prepare_schema)
    def phase1_extract_foundation(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 1: extract Case, Proceeding, Issue nodes and create edges between them
        logger.info(f"Phase 1 (foundation): starting for file {self.state.filename}")
        tools = []

        # Load flow_map to determine ordering and instructions/examples
        try:
            import os
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
            with open(flow_map_path, "r") as f:
                flow_map = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load flow_map.json; falling back to schema order: {e}")
            flow_map = []

        # Build list of Phase 1 labels: only Case, Proceeding, Issue
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        def_map = {ld.get("label"): ld for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str)}

        # Phase 1: Case, Proceeding, Issue only
        fm_phase1 = [e for e in (flow_map or []) if isinstance(e, dict) and e.get("phase") == 1 and not e.get("ai_ignore")]
        
        # Filter to only Case, Proceeding, Issue
        phase1_target_labels = {"Case", "Proceeding", "Issue"}
        ordered_labels: List[str] = []
        fm_labels = [e.get("label") for e in fm_phase1 if isinstance(e.get("label"), str)]
        for lbl in fm_labels:
            if lbl in phase1_target_labels and lbl in def_map and lbl not in ordered_labels:
                ordered_labels.append(lbl)

        # Prepare crew and iterate per label
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements={},
        )

        next_idx = 1 + len(self.state.nodes_accumulated or [])
        produced_labels: List[str] = []

        # Log target labels for Phase 1
        try:
            preview = ", ".join(ordered_labels[:10]) + ("..." if len(ordered_labels) > 10 else "")
            logger.info(f"Phase 1: target labels count={len(ordered_labels)} [{preview}]")
        except Exception:
            pass

        nodes_before_p1 = len(self.state.nodes_accumulated or [])

        for label in ordered_labels:
            try:
                # Build single-label spec for properties rendering
                ldef = def_map.get(label)
                if not isinstance(ldef, dict):
                    continue
                # Build properties-only spec for Phase 1 (omit relationships)
                ldef_props_only = {
                    "label": ldef.get("label"),
                    "properties": ldef.get("properties", []),
                }
                props_spec_text = render_spec_text({"labels": [ldef_props_only]})

                # Pull instructions/examples from flow_map entry
                fm_entry = None
                for e in (flow_map or []):
                    if isinstance(e, dict) and e.get("label") == label:
                        fm_entry = e
                        break
                instructions = (fm_entry or {}).get("instructions") or ""
                examples_json = json.dumps((fm_entry or {}).get("examples") or [], ensure_ascii=False)

                # Model for properties
                props_model = (self.state.models_by_label or {}).get(label)
                if props_model is None:
                    continue

                # Build per-node task description (common guidance + label-specific)
                task_desc = (
                    "Analyse the document text (provided below) and identify data as described by the instructions below.\n\n"
                    "CRITICAL: Extract information ONLY from the provided case text. Do not use general knowledge, external information, or assumptions. If information is not explicitly or implicitly present in the text, do not include it.\n\n"
                    "INSTRUCTIONS:\n" + instructions + "\n\n"
                    "Be comprehensive; do not miss any information that IS in the text."
                    "Return ONLY JSON matching the schema properties for this node type:\n\n"
                    "SCHEMA PROPERTIES for '" + label + "':\n" + props_spec_text + "\n\n"                   
                    "Guidance:\n"
                    "- Extract ONLY from the case text provided below - do not rely on general knowledge.\n"
                    "- Include all properties you can confidently extract from the text.\n"
                    "- For required properties, provide your best inference from the text if not explicitly stated.\n"
                    "- Enforce types, enums, and date formats exactly as specified.\n"
                    "- Use facts present in the text; do not invent or assume.\n"
                    "- Do not output temp_id or label here. Properties only.\n\n"
                    "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                    
                )

                # Decide single vs multi extraction
                # In Phase 1: Issue can have multiple instances
                allow_multiple = label in {"Issue"}
                if allow_multiple:
                    multi_desc = (
                        "Analyse the document text (provided below) and extract ALL distinct nodes for the label '" + label + "'.\n\n"
                        "CRITICAL: Extract information ONLY from the provided case text. Do not use general knowledge, external information, or assumptions. If information is not explicitly or implicitly present in the text, do not include it.\n\n"
                        "INSTRUCTIONS:\n" + instructions + "\n\n"
                        "Return a JSON object: { items: [ { ...properties... }, ... ] }.\n"
                        "Each item must match the schema properties exactly; include required properties; enforce types/enums/dates.\n"
                        "Extract ONLY from the case text provided - do not rely on general knowledge or make assumptions.\n"
                        "Do not include temp_id or label in the items.\n\n"
                        "SCHEMA PROPERTIES for '" + label + "':\n" + props_spec_text + "\n\n"
                        "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                        "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                    )
                    
                    try:
                        # Create a dynamic Pydantic model for the list of items
                        list_model = create_model(
                            f'{label}List',
                            items=(List[props_model], ...)  # type: ignore
                        )
                        logger.info(f"Phase 1: extracting multi-node label '{label}'")
                        dyn_task = crew.phase1_extract_multi_nodes_task(multi_desc, list_model)
                        single_crew = Crew(
                            agents=[crew.phase1_extract_agent()],
                            tasks=[dyn_task],
                            process=Process.sequential,
                        )
                        result = single_crew.kickoff()
                        logger.info(f"Phase 1: '{label}' extraction completed, result type: {type(result).__name__}")
                        
                        # CrewAI returns a CrewOutput that wraps the Pydantic result
                        # Access the actual Pydantic model via .pydantic or .raw
                        actual_result = None
                        if hasattr(result, 'pydantic'):
                            actual_result = result.pydantic
                        elif hasattr(result, 'raw'):
                            actual_result = result.raw
                        else:
                            actual_result = result
                        
                        logger.info(f"Phase 1: '{label}' unwrapped result type: {type(actual_result).__name__}, has items: {hasattr(actual_result, 'items')}")
                        
                        # Now extract items from the Pydantic model
                        if not hasattr(actual_result, 'items'):
                            logger.warning(f"Phase 1: '{label}' result has no 'items' attribute. Result: {actual_result}")
                            items = []
                        elif not isinstance(actual_result.items, list):
                            logger.warning(f"Phase 1: '{label}' result.items is not a list. Type: {type(actual_result.items).__name__}")
                            items = []
                        else:
                            items = actual_result.items
                            logger.info(f"Phase 1: '{label}' returned {len(items)} items")

                        nodes_added_count = 0
                        for idx, item in enumerate(items):
                            try:
                                # Each item is already a validated Pydantic model instance
                                properties = item.model_dump(exclude_none=True)
                                node = {"temp_id": f"n{next_idx}", "label": label, "properties": properties}
                                next_idx += 1
                                self.state.nodes_accumulated.append(node)
                                nodes_added_count += 1
                            except Exception as e:
                                logger.warning(f"Phase 1: Failed to process item {idx} for '{label}': {e}")
                                continue
                        
                        logger.info(f"Phase 1: '{label}' added {nodes_added_count} nodes")
                        if nodes_added_count > 0:
                            produced_labels.append(label)
                    except Exception as e:
                        logger.error(f"Phase 1: Multi-node extraction for '{label}' failed with error: {e}", exc_info=True)
                        continue
                else:
                    # Single-instance labels
                    dyn_task = crew.phase1_extract_single_node_task(task_desc, props_model)  # type: ignore[arg-type]
                    single_crew = Crew(
                        agents=[crew.phase1_extract_agent()],
                        tasks=[dyn_task],
                        process=Process.sequential,
                    )
                    result = single_crew.kickoff()

                    # Unwrap CrewOutput to get the actual Pydantic model
                    actual_result = None
                    if hasattr(result, 'pydantic'):
                        actual_result = result.pydantic
                    elif hasattr(result, 'model_dump'):
                        actual_result = result
                    else:
                        actual_result = result

                    # Parse pydantic output into properties dict
                    if hasattr(actual_result, 'model_dump'):
                        properties = actual_result.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                    elif isinstance(actual_result, dict):
                        properties = actual_result
                    else:
                        properties = json.loads(str(actual_result))

                    node = {"temp_id": f"n{next_idx}", "label": label, "properties": properties}
                    next_idx += 1
                    self.state.nodes_accumulated.append(node)
                    produced_labels.append(label)
            except Exception as e:
                logger.warning(f"Phase 1 per-node task for {label} failed: {e}")
                continue

        # Ensure a Case node exists; if missing, add minimal fallback
        if "Case" in ordered_labels and ("Case" not in produced_labels):
            try:
                node = {"temp_id": f"n{next_idx}", "label": "Case", "properties": {"name": self.state.filename}}
                self.state.nodes_accumulated.append(node)
            except Exception:
                pass

        # Create edges: Case → Proceeding and Proceeding → Issue
        try:
            # Helper to find temp_id by label
            def find_first_temp_id(label: str) -> Optional[str]:
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                        return n.get("temp_id")
                return None
            
            def find_all_temp_ids(label: str) -> List[str]:
                return [n.get("temp_id") for n in (self.state.nodes_accumulated or []) 
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str)]
            
            case_id = find_first_temp_id("Case")
            proceeding_id = find_first_temp_id("Proceeding")
            issue_ids = find_all_temp_ids("Issue")
            
            edges_before = len(self.state.edges_accumulated or [])
            
            # Case → Proceeding (HAS_PROCEEDING)
            if case_id and proceeding_id:
                rel_label = get_relationship_label_for_edge("Case", "Proceeding", self.state.rels_by_label or {})
                if rel_label:
                    self.state.edges_accumulated.append({
                        "from": case_id, 
                        "to": proceeding_id, 
                        "label": rel_label, 
                        "properties": {}
                    })
                    logger.info(f"Phase 1: Created edge Case → Proceeding ({rel_label})")
            
            # Proceeding → Issue (ADDRESSES) for each Issue
            if proceeding_id and issue_ids:
                rel_label = get_relationship_label_for_edge("Proceeding", "Issue", self.state.rels_by_label or {})
                if rel_label:
                    for issue_id in issue_ids:
                        self.state.edges_accumulated.append({
                            "from": proceeding_id, 
                            "to": issue_id, 
                            "label": rel_label, 
                            "properties": {}
                        })
                    logger.info(f"Phase 1: Created {len(issue_ids)} edges Proceeding → Issue ({rel_label})")
            
            edges_after = len(self.state.edges_accumulated or [])
            edges_added = max(0, edges_after - edges_before)
        except Exception as e:
            logger.warning(f"Phase 1: Failed to create edges: {e}")
            edges_added = 0

        try:
            nodes_after_p1 = len(self.state.nodes_accumulated or [])
            added = max(0, nodes_after_p1 - nodes_before_p1)
            preview_prod = ", ".join(produced_labels[:10]) + ("..." if len(produced_labels) > 10 else "")
            logger.info(f"Phase 1: completed (nodes_added={added}, edges_added={edges_added}, produced_labels={len(produced_labels)} [{preview_prod}])")
        except Exception:
            logger.info("Phase 1 (foundation): completed")
        
        # Publish progress if callback is set
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 1 complete: Extracted foundation nodes", "phase1", 10)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        
        return {"status": "phase1_done"}


    @listen(phase1_extract_foundation)
    def phase2_assign_forum_jurisdiction(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2: select Forum and programmatically fetch Jurisdiction; create edges to Proceeding
        logger.info("Phase 2: assigning Forum and Jurisdiction")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Build catalog for Forum only (no ReliefType in this phase)
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in ["Forum"]:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                entries: List[Dict[str, Any]] = []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Select Forum based on case text
            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.phase5_select_existing_task()
            single_crew_sel = Crew(
                agents=[crew_sel.phase5_select_existing_agent()],
                tasks=[task_sel],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result_sel = single_crew_sel.kickoff()
            selected: Dict[str, List[str]] = {}
            try:
                text = str(result_sel)
                data = json.loads(text) if isinstance(result_sel, str) else (result_sel if isinstance(result_sel, dict) else json.loads(str(result_sel)))
                sel = data.get("selected") if isinstance(data, dict) else None
                if isinstance(sel, dict):
                    for k, v in sel.items():
                        if isinstance(k, str) and isinstance(v, list):
                            selected[k] = [str(x) for x in v]
            except Exception:
                selected = {}

            # Create selected Forum nodes by ID lookup
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl in ["Forum"]:
                forum_ids = selected.get(lbl) or []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                allowed_keys = [k for k in (props_meta.keys() if isinstance(props_meta, dict) else []) if isinstance(k, str)]
                catalog_rows = catalogs.get(lbl, [])
                
                # Lookup catalog entry by forum_id
                def find_catalog_by_id(forum_id: str) -> Dict[str, Any] | None:
                    for row in catalog_rows:
                        if isinstance(row, dict) and str(row.get("forum_id")) == str(forum_id):
                            return row
                    return None
                
                for forum_id in forum_ids:
                    entry = find_catalog_by_id(forum_id)
                    if not entry:
                        logger.warning(f"Phase 2: Forum ID '{forum_id}' not found in catalog; skipping (can_create_new=false)")
                        continue
                    
                    # Use all properties from catalog entry
                    props: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if entry.get(k) is not None:
                            props[k] = entry.get(k)
                    # Ensure ID fields are included
                    for k, v in entry.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                    
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": props}
                    next_idx += 1
                    self.state.nodes_accumulated.append(node)

            # Create edges: Proceeding → Forum
            try:
                def find_first_temp_id(label: str) -> Optional[str]:
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                            return n.get("temp_id")
                    return None

                p_id = find_first_temp_id("Proceeding")
                f_id = find_first_temp_id("Forum")

                if p_id and f_id:
                    rel_proceeding_forum = get_relationship_label_for_edge("Proceeding", "Forum", self.state.rels_by_label or {})
                    if rel_proceeding_forum:
                        self.state.edges_accumulated.append({"from": p_id, "to": f_id, "label": rel_proceeding_forum, "properties": {}})
                        logger.info(f"Phase 2: Created edge Proceeding → Forum ({rel_proceeding_forum})")

                # Programmatically fetch Jurisdiction for selected Forum
                if f_id:
                    forum_nodes = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("temp_id") == f_id]
                    forum_name = None
                    if forum_nodes:
                        props = forum_nodes[0].get("properties") or {}
                        forum_name = props.get("name") or props.get("text") or props.get("description")
                    if isinstance(forum_name, str) and forum_name.strip():
                        rel_forum_jurisdiction = get_relationship_label_for_edge("Forum", "Jurisdiction", self.state.rels_by_label or {})
                        
                        if rel_forum_jurisdiction:
                            query = f"MATCH (f:Forum {{name: $name}})-[:{rel_forum_jurisdiction}]->(j:Jurisdiction) RETURN properties(j) AS props LIMIT 1"
                            rows = neo4j_client.execute_query(query, parameters={"name": forum_name})
                            if rows:
                                j_props = rows[0].get("props") if isinstance(rows[0], dict) else None
                                if isinstance(j_props, dict):
                                    j_node_id = find_first_temp_id("Jurisdiction")
                                    if not j_node_id:
                                        j_node_id = f"n{next_idx}"
                                        next_idx += 1
                                        self.state.nodes_accumulated.append({"temp_id": j_node_id, "label": "Jurisdiction", "properties": j_props})
                                    # Forum → Jurisdiction
                                    self.state.edges_accumulated.append({"from": f_id, "to": j_node_id, "label": rel_forum_jurisdiction, "properties": {}})
                                    logger.info(f"Phase 2: Created edge Forum → Jurisdiction ({rel_forum_jurisdiction})")
            except Exception as e:
                logger.warning(f"Phase 2: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 2: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 2: Forum and Jurisdiction completed")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 2 complete: Assigned forum and jurisdiction", "phase2", 20)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase2_done"}
        except Exception as e:
            logger.warning(f"Phase 2: Forum/Jurisdiction assignment failed: {e}")
            return {"status": "phase2_skipped"}

    @listen(phase2_assign_forum_jurisdiction)
    def phase3_extract_parties(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: extract/dedupe Parties and create Proceeding->Party edges with roles
        logger.info("Phase 3: extracting and deduplicating Parties; assigning roles")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Party catalog can be extremely large; skip preloading and use fuzzy lookup per generated name
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Party": []}

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task = crew.phase8_party_task()
            single_crew = Crew(
                agents=[crew.phase8_party_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
            parties = data.get("parties") if isinstance(data, dict) else None
            roles = data.get("case_roles") if isinstance(data, dict) else None
            if not isinstance(parties, list):
                parties = []
            if not isinstance(roles, list):
                roles = []

            # Validate/dedup parties by name
            party_model = (self.state.models_by_label or {}).get("Party")
            existing_names = set()
            for n in (self.state.nodes_accumulated or []):
                if isinstance(n, dict) and n.get("label") == "Party":
                    nm = ((n.get("properties") or {}).get("name") or "").strip()
                    if nm:
                        existing_names.add(nm)

            # Fuzzy lookup using Neo4j for each generated party name
            def _lookup_existing_party(raw_name: str) -> tuple[str, Optional[str]]:
                try:
                    q = (raw_name or "").strip()
                    if not q:
                        return raw_name, None
                    query = (
                        "MATCH (p:Party) "
                        "WHERE p.name IS NOT NULL AND (toLower(p.name) CONTAINS toLower($q) OR toLower($q) CONTAINS toLower(p.name)) "
                        "RETURN properties(p) AS props LIMIT 25"
                    )
                    rows = neo4j_client.execute_query(query, {"q": q})
                    candidates: List[Dict[str, Any]] = []
                    for r in rows:
                        props = r.get("props") if isinstance(r.get("props"), dict) else None
                        if isinstance(props, dict):
                            nm = props.get("name")
                            if isinstance(nm, str) and nm.strip():
                                candidates.append(props)
                    if not candidates:
                        return raw_name, None
                    # Prefer case-insensitive exact
                    for props in candidates:
                        n = str(props.get("name") or "")
                        if n.lower() == q.lower():
                            pid = props.get("party_id")
                            return n, (str(pid) if isinstance(pid, (str, int)) else None)
                    # Heuristic: choose the closest by containment and length similarity
                    def score(candidate_name: str) -> float:
                        c = candidate_name.lower()
                        qq = q.lower()
                        contain = (1.0 if (c in qq or qq in c) else 0.0)
                        len_ratio = min(len(c), len(qq)) / max(len(c), len(qq)) if max(len(c), len(qq)) > 0 else 0.0
                        return contain * 0.7 + len_ratio * 0.3
                    best_props = max(candidates, key=lambda p: score(str(p.get("name") or "")))
                    best_name = str(best_props.get("name") or "")
                    if score(best_name) >= 0.75:
                        pid = best_props.get("party_id")
                        return best_name, (str(pid) if isinstance(pid, (str, int)) else None)
                    return raw_name, None
                except Exception:
                    return raw_name, None

            next_idx = 1 + len(self.state.nodes_accumulated or [])
            created_ids_by_index: Dict[int, str] = {}
            for idx, p in enumerate(parties):
                if not isinstance(p, dict):
                    continue
                try:
                    if party_model is not None:
                        inst = party_model(**p)
                        clean = inst.model_dump(exclude_none=True)
                    else:
                        clean = {k: v for k, v in p.items() if isinstance(k, str)}
                except Exception:
                    clean = {k: v for k, v in p.items() if isinstance(k, str)}
                nm = (clean.get("name") or "").strip()
                if nm:
                    standardized_name, matched_party_id = _lookup_existing_party(nm)
                    if standardized_name and standardized_name != nm:
                        clean["name"] = standardized_name
                        nm = standardized_name
                    if matched_party_id:
                        clean["party_id"] = matched_party_id
                if nm and nm in existing_names:
                    # find existing temp_id
                    tid = None
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == "Party":
                            if ((n.get("properties") or {}).get("name") or "").strip() == nm and isinstance(n.get("temp_id"), str):
                                tid = n.get("temp_id")
                                break
                    if isinstance(tid, str):
                        created_ids_by_index[idx] = tid
                        continue
                # create new party
                tid = f"n{next_idx}"
                next_idx += 1
                (self.state.nodes_accumulated or []).append({"temp_id": tid, "label": "Party", "properties": clean})
                created_ids_by_index[idx] = tid
                if nm:
                    existing_names.add(nm)

            # Create Proceeding → Party edges (with role properties)
            try:
                rel_proceeding_party = get_relationship_label_for_edge("Proceeding", "Party", self.state.rels_by_label or {})
                
                if not rel_proceeding_party:
                    logger.warning("Phase 3: No relationship found in schema for Proceeding -> Party")
                    return {"status": "phase3_skipped"}
                
                pr_id = None
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == "Proceeding" and isinstance(n.get("temp_id"), str):
                        pr_id = n.get("temp_id")
                        break
                if isinstance(pr_id, str):
                    existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
                    for r in roles:
                        if not isinstance(r, dict):
                            continue
                        p_idx = r.get("party_index")
                        role = r.get("role")
                        if not (isinstance(p_idx, int) and isinstance(role, str)):
                            continue
                        p_id = created_ids_by_index.get(p_idx)
                        if not isinstance(p_id, str):
                            continue
                        key = (pr_id, p_id, rel_proceeding_party)
                        if key not in existing_edges:
                            props = {"role": role}
                            self.state.edges_accumulated.append({"from": pr_id, "to": p_id, "label": rel_proceeding_party, "properties": props})
                            existing_edges.add(key)
                    logger.info(f"Phase 3: Created {len(roles)} edges Proceeding → Party ({rel_proceeding_party})")
            except Exception as e:
                logger.warning(f"Phase 3: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 3: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 3: party extraction/dedup and relationships completed")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 3 complete: Extracted and linked parties", "phase3", 30)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase3_done"}
        except Exception as e:
            logger.warning(f"Phase 3: party extraction failed: {e}")
            return {"status": "phase3_skipped"}

    @listen(phase3_extract_parties)
    def phase4_assign_issue_concepts(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: per Issue, select/generate Doctrine, Policy, FactPattern with dedup and create edges
        logger.info("Phase 4: assigning Doctrine/Policy/FactPattern per Issue with catalog dedup")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            issues = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Issue" and isinstance(n.get("temp_id"), str)
            ]
            if not issues:
                logger.info("Phase 4: no Issue nodes present; skipping")
                return {"status": "phase4_skipped"}

            # Build catalogs using schema-defined properties
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Doctrine": [], "Policy": [], "FactPattern": []}
            try:
                for lbl in list(catalogs.keys()):
                    rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                    entries: List[Dict[str, Any]] = []
                    props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                    allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        entry: Dict[str, Any] = {}
                        for k in allowed_keys:
                            if r.get(k) is not None:
                                v = r.get(k)
                                try:
                                    entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                                except Exception:
                                    entry[k] = str(v)
                        for k, v in r.items():
                            if isinstance(k, str) and k.endswith("_id") and v is not None:
                                try:
                                    entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                                except Exception:
                                    entry[k] = str(v)
                        if entry:
                            entries.append(entry)
                    catalogs[lbl] = entries
            except Exception:
                pass

            # Build schema spec snippets
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            def get_def(lbl: str) -> Dict[str, Any] | None:
                return next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == lbl), None)
            defs_props_only: List[Dict[str, Any]] = []
            for lbl in ["Doctrine", "Policy", "FactPattern"]:
                d = get_def(lbl)
                if isinstance(d, dict):
                    defs_props_only.append({"label": d.get("label"), "properties": d.get("properties", [])})
            spec_text = render_spec_text({"labels": defs_props_only})

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "ISSUES_JSON": json.dumps({"issues": issues}, ensure_ascii=False),
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                    "SCHEMA_SPEC_TEXT": spec_text,
                },
            )
            task = crew.phase7_issue_related_task()
            single_crew = Crew(
                agents=[crew.phase7_issue_related_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            # Parse
            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
            doctrines = data.get("doctrines") if isinstance(data, dict) else None
            policies = data.get("policies") if isinstance(data, dict) else None
            factpatterns = data.get("factpatterns") if isinstance(data, dict) else None
            issue_map = data.get("issue_map") if isinstance(data, dict) else None
            if not isinstance(doctrines, list):
                doctrines = []
            if not isinstance(policies, list):
                policies = []
            if not isinstance(factpatterns, list):
                factpatterns = []
            if not isinstance(issue_map, list):
                issue_map = []

            # Models
            doctrine_model = (self.state.models_by_label or {}).get("Doctrine")
            policy_model = (self.state.models_by_label or {}).get("Policy")
            fp_model = (self.state.models_by_label or {}).get("FactPattern")

            # Dedup signatures and add nodes
            def build_signature(lbl: str, props: Dict[str, Any]) -> str:
                if lbl == "Doctrine":
                    return f"{props.get('name','')}//{props.get('category','')}".strip()
                if lbl == "Policy":
                    return f"{props.get('name','')}//{props.get('discipline','')}".strip()
                return f"{props.get('name','')}".strip()

            existing_sig: Dict[str, set[str]] = {"Doctrine": set(), "Policy": set(), "FactPattern": set()}
            for n in (self.state.nodes_accumulated or []):
                if not isinstance(n, dict):
                    continue
                lbl = n.get("label")
                if lbl not in existing_sig:
                    continue
                props = n.get("properties") or {}
                sig = build_signature(lbl, props)
                if sig:
                    existing_sig[lbl].add(sig)

            created_ids: Dict[str, Dict[int, str]] = {"Doctrine": {}, "Policy": {}, "FactPattern": {}}
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            def add_items(lbl: str, items: List[Dict[str, Any]], model) -> None:
                nonlocal next_idx
                for idx, iprops in enumerate(items):
                    if not isinstance(iprops, dict):
                        continue
                    try:
                        if model is not None:
                            inst = model(**iprops)
                            clean = inst.model_dump(exclude_none=True)
                        else:
                            clean = {k: v for k, v in iprops.items() if isinstance(k, str)}
                    except Exception:
                        clean = {k: v for k, v in iprops.items() if isinstance(k, str)}
                    sig = build_signature(lbl, clean)
                    if sig and sig in existing_sig[lbl]:
                        # find existing temp_id
                        tid = None
                        for n in (self.state.nodes_accumulated or []):
                            if isinstance(n, dict) and n.get("label") == lbl:
                                props = n.get("properties") or {}
                                if build_signature(lbl, props) == sig and isinstance(n.get("temp_id"), str):
                                    tid = n.get("temp_id")
                                    break
                        if isinstance(tid, str):
                            created_ids[lbl][idx] = tid
                            continue
                    tid = f"n{next_idx}"
                    next_idx += 1
                    self.state.nodes_accumulated.append({"temp_id": tid, "label": lbl, "properties": clean})
                    created_ids[lbl][idx] = tid
                    if sig:
                        existing_sig[lbl].add(sig)

            add_items("Doctrine", doctrines, doctrine_model)
            add_items("Policy", policies, policy_model)
            add_items("FactPattern", factpatterns, fp_model)

            # Create Issue relationships (get labels from schema)
            rel_label_doctrine = get_relationship_label_for_edge("Issue", "Doctrine", self.state.rels_by_label or {})
            rel_label_policy = get_relationship_label_for_edge("Issue", "Policy", self.state.rels_by_label or {})
            rel_label_factpattern = get_relationship_label_for_edge("Issue", "FactPattern", self.state.rels_by_label or {})
            
            existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for m in issue_map:
                if not isinstance(m, dict):
                    continue
                i_id = m.get("issue_temp_id")
                di = m.get("doctrine_index")
                pi = m.get("policy_index")
                fi = m.get("factpattern_index")
                if isinstance(i_id, str) and isinstance(di, int) and rel_label_doctrine:
                    d_id = created_ids["Doctrine"].get(di)
                    if isinstance(d_id, str):
                        key = (i_id, d_id, rel_label_doctrine)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": d_id, "label": rel_label_doctrine, "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(pi, int) and rel_label_policy:
                    p_id = created_ids["Policy"].get(pi)
                    if isinstance(p_id, str):
                        key = (i_id, p_id, rel_label_policy)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": p_id, "label": rel_label_policy, "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(fi, int) and rel_label_factpattern:
                    f_id = created_ids["FactPattern"].get(fi)
                    if isinstance(f_id, str):
                        key = (i_id, f_id, rel_label_factpattern)
                        if key not in existing_edges:
                            self.state.edges_accumulated.append({"from": i_id, "to": f_id, "label": rel_label_factpattern, "properties": {}})
                            existing_edges.add(key)

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 4: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 4: issue-related assignment completed")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 4 complete: Assigned issue concepts", "phase4", 40)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase4_done"}
        except Exception as e:
            logger.warning(f"Phase 4: issue-related assignment failed: {e}")
            return {"status": "phase4_skipped"}

    @listen(phase4_assign_issue_concepts)
    def phase5_create_holdings(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 5: for each Issue, create ONE Holding and link Issue → Holding
        logger.info("Phase 5: creating Holdings per Issue (one-to-one)")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            
            # Load flow_map for Holding instructions
            try:
                import os
                flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
                with open(flow_map_path, "r") as f:
                    flow_map = json.load(f)
            except Exception:
                flow_map = []
            
            fm_holding = None
            for e in (flow_map or []):
                if isinstance(e, dict) and e.get("label") == "Holding":
                    fm_holding = e
                    break
            instructions = (fm_holding or {}).get("instructions") or ""
            examples_json = json.dumps((fm_holding or {}).get("examples") or [], ensure_ascii=False)
            
            # Get Holding schema
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            holding_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Holding"), None)
            holding_spec_text = ""
            if isinstance(holding_def, dict):
                holding_def_props_only = {"label": holding_def.get("label"), "properties": holding_def.get("properties", [])}
                holding_spec_text = render_spec_text({"labels": [holding_def_props_only]})
            
            holding_model = (self.state.models_by_label or {}).get("Holding")
            
            # Collect all Issues
            issues = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Issue"]
            if not issues:
                logger.info("Phase 5: no Issue nodes present; skipping Holdings")
                return {"status": "phase5_skipped"}
            
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={},
            )
            
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            holdings_created = 0
            edges_created = 0
            
            # For each Issue, create ONE Holding
            for issue_node in issues:
                try:
                    issue_temp_id = issue_node.get("temp_id")
                    issue_props = issue_node.get("properties") or {}
                    issue_ctx_json = json.dumps(issue_props, ensure_ascii=False)
                    
                    # Compose task: create Holding for THIS Issue
                    desc = (
                        "Read the document text (provided below) and create a Holding for the following Issue.\n\n"
                        "CRITICAL: Extract information ONLY from the provided case text. State the court's holding for THIS specific issue only.\n\n"
                        "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                        "Issue (properties JSON):\n" + issue_ctx_json + "\n\n"
                        "Guidance:\n"
                        "- State the court's holding as a clear, outcome-determinative rule or answer to THIS specific legal question.\n"
                        "- Avoid reasoning; focus on the bottom-line legal conclusion for this issue.\n"
                        "- Return ONLY JSON matching the schema properties for Holding.\n"
                        "- Extract from the case text provided above.\n\n"
                        "INSTRUCTIONS (from flow map):\n" + instructions + "\n\n"
                        "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                        "SCHEMA PROPERTIES for 'Holding':\n" + holding_spec_text + "\n\n"
                    )
                    
                    dyn_task = crew.phase1_extract_single_node_task(desc, holding_model)  # type: ignore[arg-type]
                    single_crew = Crew(
                        agents=[crew.phase1_extract_agent()],
                        tasks=[dyn_task],
                        process=Process.sequential,
                    )
                    result = single_crew.kickoff()
                    
                    # Unwrap CrewOutput
                    actual_result = None
                    if hasattr(result, 'pydantic'):
                        actual_result = result.pydantic
                    elif hasattr(result, 'model_dump'):
                        actual_result = result
                    else:
                        actual_result = result
                    
                    # Parse pydantic output
                    if hasattr(actual_result, 'model_dump'):
                        properties = actual_result.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                    elif isinstance(actual_result, dict):
                        properties = actual_result
                    else:
                        properties = json.loads(str(actual_result))
                    
                    # Create Holding node
                    holding_temp_id = f"n{next_idx}"
                    next_idx += 1
                    holding_node = {"temp_id": holding_temp_id, "label": "Holding", "properties": properties}
                    self.state.nodes_accumulated.append(holding_node)
                    holdings_created += 1
                    
                    # Create edge: Holding → Issue (ON_ISSUE)
                    rel_label = get_relationship_label_for_edge("Holding", "Issue", self.state.rels_by_label or {})
                    if rel_label and isinstance(issue_temp_id, str):
                        self.state.edges_accumulated.append({
                            "from": holding_temp_id,
                            "to": issue_temp_id,
                            "label": rel_label,
                            "properties": {}
                        })
                        edges_created += 1
                    else:
                        logger.warning("Phase 5: No relationship found in schema for Holding -> Issue")
                
                except Exception as e:
                    logger.warning(f"Phase 5: Failed to create Holding for an Issue: {e}")
                    continue
            
            logger.info(f"Phase 5: completed (holdings_created={holdings_created}, edges_created={edges_created})")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 5 complete: Created holdings per issue", "phase5", 45)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase5_done"}
        except Exception as e:
            logger.warning(f"Phase 5: Holdings creation failed: {e}")
            return {"status": "phase5_skipped"}

    @listen(phase5_create_holdings)
    def phase6_extract_ruling_and_arguments(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 6: for each Holding, create/select Ruling and extract Arguments; create edges
        logger.info("Phase 6: extracting Ruling and Arguments per Holding")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            
            # Load flow_map for Ruling and Argument instructions
            try:
                import os
                flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
                with open(flow_map_path, "r") as f:
                    flow_map = json.load(f)
            except Exception:
                flow_map = []
            
            fm_ruling = None
            fm_argument = None
            for e in (flow_map or []):
                if isinstance(e, dict):
                    if e.get("label") == "Ruling":
                        fm_ruling = e
                    if e.get("label") == "Argument":
                        fm_argument = e
            
            ruling_instructions = (fm_ruling or {}).get("instructions") or ""
            ruling_examples_json = json.dumps((fm_ruling or {}).get("examples") or [], ensure_ascii=False)
            argument_instructions = (fm_argument or {}).get("instructions") or ""
            argument_examples_json = json.dumps((fm_argument or {}).get("examples") or [], ensure_ascii=False)
            
            # Get schemas
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            ruling_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Ruling"), None)
            argument_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Argument"), None)
            
            ruling_spec_text = ""
            if isinstance(ruling_def, dict):
                ruling_def_props_only = {"label": ruling_def.get("label"), "properties": ruling_def.get("properties", [])}
                ruling_spec_text = render_spec_text({"labels": [ruling_def_props_only]})
            
            argument_spec_text = ""
            if isinstance(argument_def, dict):
                argument_def_props_only = {"label": argument_def.get("label"), "properties": argument_def.get("properties", [])}
                argument_spec_text = render_spec_text({"labels": [argument_def_props_only]})
            
            ruling_model = (self.state.models_by_label or {}).get("Ruling")
            argument_model = (self.state.models_by_label or {}).get("Argument")
            
            # Collect all Holdings
            holdings = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Holding"]
            if not holdings:
                logger.info("Phase 6: no Holding nodes present; skipping Ruling/Arguments")
                return {"status": "phase6_skipped"}
            
            # Build mapping of Holding → Issue for context
            holding_to_issue: Dict[str, Dict[str, Any]] = {}
            for edge in (self.state.edges_accumulated or []):
                if isinstance(edge, dict):
                    rel_label = get_relationship_label_for_edge("Holding", "Issue", self.state.rels_by_label or {})
                    if edge.get("label") == rel_label:
                        holding_id = edge.get("from")
                        issue_id = edge.get("to")
                        if isinstance(issue_id, str) and isinstance(holding_id, str):
                            issue_node = next((n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("temp_id") == issue_id), None)
                            if issue_node:
                                holding_to_issue[holding_id] = issue_node
            
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={},
            )
            
            # Helper function to find first node by label
            def find_first_temp_id(label: str) -> Optional[str]:
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                        return n.get("temp_id")
                return None
            
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            rulings_created = 0
            arguments_created = 0
            edges_created = 0
            
            # Track created Rulings for deduplication (same Ruling can apply to multiple Holdings)
            ruling_signatures: Dict[str, str] = {}  # signature -> temp_id
            
            # For each Holding, create Ruling and Arguments
            for holding_node in holdings:
                try:
                    holding_temp_id = holding_node.get("temp_id")
                    holding_props = holding_node.get("properties") or {}
                    issue_node = holding_to_issue.get(holding_temp_id) if isinstance(holding_temp_id, str) else None
                    issue_props = (issue_node.get("properties") or {}) if issue_node else {}
                    
                    context_json = json.dumps({
                        "holding": holding_props,
                        "issue": issue_props
                    }, ensure_ascii=False)
                    
                    # Task 1: Create or reuse Ruling
                    ruling_desc = (
                        "Read the document text (provided below) and create/identify the Ruling.\n\n"
                        "CRITICAL: Extract information ONLY from the provided case text.\n\n"
                        "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                        "Context (Holding and Issue):\n" + context_json + "\n\n"
                        "Guidance:\n"
                        "- Summarize the court's disposition (affirmed, reversed, remanded, etc.).\n"
                        "- A single ruling may apply to multiple issues/holdings in the case.\n"
                        "- Return ONLY JSON matching the schema properties for Ruling.\n\n"
                        "INSTRUCTIONS (from flow map):\n" + ruling_instructions + "\n\n"
                        "EXAMPLES (illustrative):\n" + ruling_examples_json + "\n\n"
                        "SCHEMA PROPERTIES for 'Ruling':\n" + ruling_spec_text + "\n\n"
                    )
                    
                    ruling_task = crew.phase1_extract_single_node_task(ruling_desc, ruling_model)  # type: ignore[arg-type]
                    ruling_crew = Crew(
                        agents=[crew.phase1_extract_agent()],
                        tasks=[ruling_task],
                        process=Process.sequential,
                    )
                    ruling_result = ruling_crew.kickoff()
                    
                    # Parse Ruling
                    actual_ruling = None
                    if hasattr(ruling_result, 'pydantic'):
                        actual_ruling = ruling_result.pydantic
                    elif hasattr(ruling_result, 'model_dump'):
                        actual_ruling = ruling_result
                    else:
                        actual_ruling = ruling_result
                    
                    if hasattr(actual_ruling, 'model_dump'):
                        ruling_properties = actual_ruling.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                    elif isinstance(actual_ruling, dict):
                        ruling_properties = actual_ruling
                    else:
                        ruling_properties = json.loads(str(actual_ruling))
                    
                    # Dedup Ruling by signature (label + decision_date)
                    ruling_sig = f"{ruling_properties.get('label', '')}|{ruling_properties.get('decision_date', '')}".strip()
                    if ruling_sig and ruling_sig in ruling_signatures:
                        # Reuse existing Ruling
                        ruling_temp_id = ruling_signatures[ruling_sig]
                        logger.debug(f"Phase 6: Reusing existing Ruling ({ruling_temp_id})")
                    else:
                        # Create new Ruling
                        ruling_temp_id = f"n{next_idx}"
                        next_idx += 1
                        ruling_node = {"temp_id": ruling_temp_id, "label": "Ruling", "properties": ruling_properties}
                        self.state.nodes_accumulated.append(ruling_node)
                        rulings_created += 1
                        if ruling_sig:
                            ruling_signatures[ruling_sig] = ruling_temp_id
                    
                    # Create edge: Ruling → Holding (SETS)
                    rel_label_sets = get_relationship_label_for_edge("Ruling", "Holding", self.state.rels_by_label or {})
                    if rel_label_sets and isinstance(holding_temp_id, str):
                        self.state.edges_accumulated.append({
                            "from": ruling_temp_id,
                            "to": holding_temp_id,
                            "label": rel_label_sets,
                            "properties": {}
                        })
                        edges_created += 1
                    
                    # Create edge: Proceeding → Ruling (RESULTS_IN)
                    proceeding_temp_id = find_first_temp_id("Proceeding")
                    rel_label_results_in = get_relationship_label_for_edge("Proceeding", "Ruling", self.state.rels_by_label or {})
                    if rel_label_results_in and proceeding_temp_id:
                        self.state.edges_accumulated.append({
                            "from": proceeding_temp_id,
                            "to": ruling_temp_id,
                            "label": rel_label_results_in,
                            "properties": {}
                        })
                        edges_created += 1
                    
                    # Task 2: Extract Arguments relevant to this Holding/Issue
                    argument_desc = (
                        "Read the document text (provided below) and extract ALL Arguments relevant to this Holding/Issue.\n\n"
                        "CRITICAL: Extract information ONLY from the provided case text.\n\n"
                        "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                        "Context (Holding and Issue):\n" + context_json + "\n\n"
                        "Guidance:\n"
                        "- Extract ALL principal arguments advanced by any party that are relevant to this specific issue.\n"
                        "- Return a JSON object: { items: [ { ...properties... }, ... ] }.\n"
                        "- Each item must match the Argument schema properties exactly.\n"
                        "- Extract from text only; do not invent.\n\n"
                        "INSTRUCTIONS (from flow map):\n" + argument_instructions + "\n\n"
                        "EXAMPLES (illustrative):\n" + argument_examples_json + "\n\n"
                        "SCHEMA PROPERTIES for 'Argument':\n" + argument_spec_text + "\n\n"
                    )
                    
                    # Create list model for Arguments
                    from pydantic import create_model
                    argument_list_model = create_model(
                        f'ArgumentList',
                        items=(List[argument_model], ...)  # type: ignore
                    )
                    
                    argument_task = crew.phase1_extract_multi_nodes_task(argument_desc, argument_list_model)
                    argument_crew = Crew(
                        agents=[crew.phase1_extract_agent()],
                        tasks=[argument_task],
                        process=Process.sequential,
                    )
                    argument_result = argument_crew.kickoff()
                    
                    # Parse Arguments
                    actual_arg_result = None
                    if hasattr(argument_result, 'pydantic'):
                        actual_arg_result = argument_result.pydantic
                    elif hasattr(argument_result, 'raw'):
                        actual_arg_result = argument_result.raw
                    else:
                        actual_arg_result = argument_result
                    
                    if not hasattr(actual_arg_result, 'items'):
                        arguments_list = []
                    elif not isinstance(actual_arg_result.items, list):
                        arguments_list = []
                    else:
                        arguments_list = actual_arg_result.items
                    
                    # Create Argument nodes and edges
                    rel_label_eval = get_relationship_label_for_edge("Argument", "Holding", self.state.rels_by_label or {})
                    for arg_item in arguments_list:
                        try:
                            arg_properties = arg_item.model_dump(exclude_none=True)
                            arg_temp_id = f"n{next_idx}"
                            next_idx += 1
                            arg_node = {"temp_id": arg_temp_id, "label": "Argument", "properties": arg_properties}
                            self.state.nodes_accumulated.append(arg_node)
                            arguments_created += 1
                            
                            # Create edge: Argument → Holding (EVALUATED_IN)
                            if rel_label_eval and isinstance(holding_temp_id, str):
                                self.state.edges_accumulated.append({
                                    "from": arg_temp_id,
                                    "to": holding_temp_id,
                                    "label": rel_label_eval,
                                    "properties": {}
                                })
                                edges_created += 1
                        except Exception as e:
                            logger.warning(f"Phase 6: Failed to process an Argument: {e}")
                            continue
                
                except Exception as e:
                    logger.warning(f"Phase 6: Failed to process a Holding: {e}")
                    continue
            
            logger.info(f"Phase 6: completed (rulings_created={rulings_created}, arguments_created={arguments_created}, edges_created={edges_created})")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 6 complete: Created rulings and arguments", "phase6", 60)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase6_done"}
        except Exception as e:
            logger.warning(f"Phase 6: Ruling/Arguments extraction failed: {e}")
            return {"status": "phase6_skipped"}

    @listen(phase6_extract_ruling_and_arguments)
    def phase7_assign_laws(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 7: for each Argument, select or create Law(s) with dedup and add Argument->Law edges
        logger.info("Phase 7: assigning Laws to Arguments with catalog dedup")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Collect Arguments
            arguments = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Argument" and isinstance(n.get("temp_id"), str)
            ]
            if not arguments:
                logger.info("Phase 7: no Argument nodes present; skipping law assignment")
                return {"status": "phase7_skipped"}

            # Build Law catalog using schema-defined properties
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Law": []}
            try:
                rows = (self.state.existing_catalog_by_label or {}).get("Law") or []
                entries: List[Dict[str, Any]] = []
                law_props_meta = (self.state.props_meta_by_label or {}).get("Law") or {}
                allowed_keys = [k for k in law_props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs["Law"] = entries
            except Exception:
                catalogs = {"Law": []}

            # Law schema spec text for validation context
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            law_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Law"), None)
            law_spec_text = ""
            if isinstance(law_def, dict):
                law_def_props_only = {"label": law_def.get("label"), "properties": law_def.get("properties", [])}
                law_spec_text = render_spec_text({"labels": [law_def_props_only]})

            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "ARGUMENTS_JSON": json.dumps({"arguments": arguments}, ensure_ascii=False),
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                    "SCHEMA_SPEC_TEXT": law_spec_text,
                },
            )
            task = crew.phase6_law_task()
            single_crew = Crew(
                agents=[crew.phase6_law_agent()],
                tasks=[task],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result = single_crew.kickoff()

            # Parse output
            try:
                data = json.loads(str(result)) if not isinstance(result, dict) else result
            except Exception:
                data = {}
            laws_list = data.get("laws") if isinstance(data, dict) else None
            arg_map_list = data.get("argument_to_law") if isinstance(data, dict) else None
            if not isinstance(laws_list, list):
                laws_list = []
            if not isinstance(arg_map_list, list):
                arg_map_list = []

            # Validate/dedup laws and add nodes
            law_model = (self.state.models_by_label or {}).get("Law")
            existing_signatures: set[str] = set()
            for n in (self.state.nodes_accumulated or []):
                if isinstance(n, dict) and n.get("label") == "Law":
                    props = n.get("properties") or {}
                    sig = (props.get("citation") or props.get("name") or "").strip()
                    if sig:
                        existing_signatures.add(sig)

            created_ids_by_index: Dict[int, str] = {}
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for idx, lprops in enumerate(laws_list):
                if not isinstance(lprops, dict):
                    continue
                try:
                    if law_model is not None:
                        inst = law_model(**lprops)
                        clean_props = inst.model_dump(exclude_none=True)
                    else:
                        clean_props = {k: v for k, v in lprops.items() if isinstance(k, str)}
                except Exception:
                    clean_props = {k: v for k, v in lprops.items() if isinstance(k, str)}

                sig = (clean_props.get("citation") or clean_props.get("name") or "").strip()
                if sig and sig in existing_signatures:
                    temp_id = None
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == "Law":
                            props = n.get("properties") or {}
                            s = (props.get("citation") or props.get("name") or "").strip()
                            if s == sig and isinstance(n.get("temp_id"), str):
                                temp_id = n.get("temp_id")
                                break
                    if isinstance(temp_id, str):
                        created_ids_by_index[idx] = temp_id
                        continue
                temp_id = f"n{next_idx}"
                next_idx += 1
                self.state.nodes_accumulated.append({"temp_id": temp_id, "label": "Law", "properties": clean_props})
                created_ids_by_index[idx] = temp_id
                if sig:
                    existing_signatures.add(sig)

            # Create Argument -> Law edges
            rel_label_arg_law = get_relationship_label_for_edge("Argument", "Law", self.state.rels_by_label or {})
            if not rel_label_arg_law:
                logger.warning("Phase 7: No relationship found in schema for Argument -> Law")
                return {"status": "phase7_skipped"}
            
            existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for m in arg_map_list:
                if not isinstance(m, dict):
                    continue
                a_id = m.get("argument_temp_id")
                l_index = m.get("law_index")
                if not (isinstance(a_id, str) and isinstance(l_index, int)):
                    continue
                l_id = created_ids_by_index.get(l_index)
                if not isinstance(l_id, str):
                    continue
                key = (a_id, l_id, rel_label_arg_law)
                if key not in existing_edges:
                    self.state.edges_accumulated.append({"from": a_id, "to": l_id, "label": rel_label_arg_law, "properties": {}})
                    existing_edges.add(key)

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 7: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 7: law assignment completed")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 7 complete: Assigned laws", "phase7", 70)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase7_done"}
        except Exception as e:
            logger.warning(f"Phase 7: law assignment failed: {e}")
            return {"status": "phase7_skipped"}

    @listen(phase7_assign_laws)
    def phase8_assign_relief_types(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 8: select ReliefType(s) based on Ruling and create Ruling->ReliefType edges
        logger.info("Phase 8: assigning ReliefTypes per Ruling")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Build catalog for ReliefType
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in ["ReliefType"]:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                entries: List[Dict[str, Any]] = []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl) or {}
                allowed_keys = [k for k in props_meta.keys() if isinstance(k, str)]
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if r.get(k) is not None:
                            v = r.get(k)
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    for k, v in r.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            try:
                                entry[k] = v if isinstance(v, (int, float, bool)) else str(v)
                            except Exception:
                                entry[k] = str(v)
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Extract Ruling properties
            rulings = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Ruling"]
            ruling_props = (rulings[0].get("properties") if rulings and isinstance(rulings[0].get("properties"), dict) else {})

            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "RULING_JSON": json.dumps(ruling_props, ensure_ascii=False),
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.phase5_select_existing_task()
            single_crew_sel = Crew(
                agents=[crew_sel.phase5_select_existing_agent()],
                tasks=[task_sel],
                process=Process.sequential,
            )
            edges_before = len(self.state.edges_accumulated or [])
            nodes_before = len(self.state.nodes_accumulated or [])
            result_sel = single_crew_sel.kickoff()
            selected: Dict[str, List[str]] = {}
            try:
                text = str(result_sel)
                data = json.loads(text) if isinstance(result_sel, str) else (result_sel if isinstance(result_sel, dict) else json.loads(str(result_sel)))
                sel = data.get("selected") if isinstance(data, dict) else None
                if isinstance(sel, dict):
                    for k, v in sel.items():
                        if isinstance(k, str) and isinstance(v, list):
                            selected[k] = [str(x) for x in v]
            except Exception:
                selected = {}

            # Create selected ReliefType nodes by ID lookup
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl in ["ReliefType"]:
                relief_type_ids = selected.get(lbl) or []
                props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                allowed_keys = [k for k in (props_meta.keys() if isinstance(props_meta, dict) else []) if isinstance(k, str)]
                catalog_rows = catalogs.get(lbl, [])
                
                # Lookup catalog entry by relief_type_id
                def find_catalog_by_id(relief_type_id: str) -> Dict[str, Any] | None:
                    for row in catalog_rows:
                        if isinstance(row, dict) and str(row.get("relief_type_id")) == str(relief_type_id):
                            return row
                    return None
                
                for relief_type_id in relief_type_ids:
                    entry = find_catalog_by_id(relief_type_id)
                    if not entry:
                        logger.warning(f"Phase 8: ReliefType ID '{relief_type_id}' not found in catalog; skipping (can_create_new=false)")
                        continue
                    
                    # Use all properties from catalog entry
                    props: Dict[str, Any] = {}
                    for k in allowed_keys:
                        if entry.get(k) is not None:
                            props[k] = entry.get(k)
                    # Ensure ID fields are included
                    for k, v in entry.items():
                        if isinstance(k, str) and k.endswith("_id") and v is not None:
                            props[k] = str(v) if not isinstance(v, (int, float, bool)) else v
                    
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": props}
                    next_idx += 1
                    self.state.nodes_accumulated.append(node)

            # Create edges: Ruling → ReliefType
            try:
                def find_first_temp_id(label: str) -> Optional[str]:
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                            return n.get("temp_id")
                    return None
                
                def find_all_temp_ids(label: str) -> List[str]:
                    return [n.get("temp_id") for n in (self.state.nodes_accumulated or []) 
                            if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str)]

                ruling_ids = find_all_temp_ids("Ruling")
                relief_type_ids = find_all_temp_ids("ReliefType")

                rel_ruling_relief = get_relationship_label_for_edge("Ruling", "ReliefType", self.state.rels_by_label or {})
                
                if rel_ruling_relief and ruling_ids and relief_type_ids:
                    existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
                    # Create edges from each Ruling to each selected ReliefType
                    for r_id in ruling_ids:
                        for rt_id in relief_type_ids:
                            key = (r_id, rt_id, rel_ruling_relief)
                            if key not in existing_edges:
                                self.state.edges_accumulated.append({"from": r_id, "to": rt_id, "label": rel_ruling_relief, "properties": {}})
                                existing_edges.add(key)
                    logger.info(f"Phase 8: Created edges Ruling → ReliefType ({rel_ruling_relief})")
            except Exception as e:
                logger.warning(f"Phase 8: Failed to create edges: {e}")

            try:
                nodes_after = len(self.state.nodes_accumulated or [])
                edges_after = len(self.state.edges_accumulated or [])
                logger.info(f"Phase 8: completed (nodes_added={max(0, nodes_after - nodes_before)}, edges_added={max(0, edges_after - edges_before)})")
            except Exception:
                logger.info("Phase 8: ReliefType assignment completed")
            
            if self.state.progress_callback:
                try:
                    self.state.progress_callback("Phase 8 complete: Assigned relief types", "phase8", 75)
                except Exception as e:
                    logger.warning(f"Failed to publish progress: {e}")
            
            return {"status": "phase8_done"}
        except Exception as e:
            logger.warning(f"Phase 8: ReliefType assignment failed: {e}")
            return {"status": "phase8_skipped"}
    @listen(phase8_assign_relief_types)
    def phase9_extract_facts(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # New Phase 2: generate Fact nodes per Argument; many facts may support each argument
        logger.info("Phase 9: generating Facts per Argument")
        tools = []

        # Load flow_map for Fact instructions/examples
        try:
            import os
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
            with open(flow_map_path, "r") as f:
                flow_map = json.load(f)
        except Exception:
            flow_map = []

        fm_fact = None
        for e in (flow_map or []):
            if isinstance(e, dict) and e.get("label") == "Fact":
                fm_fact = e
                break
        instructions = (fm_fact or {}).get("instructions") or ""
        examples_json = json.dumps((fm_fact or {}).get("examples") or [], ensure_ascii=False)

        # Properties model and spec for Fact
        fact_model = (self.state.models_by_label or {}).get("Fact")
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        fact_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Fact"), None)
        spec_text = ""
        if isinstance(fact_def, dict):
            fact_def_props_only = {"label": fact_def.get("label"), "properties": fact_def.get("properties", [])}
            spec_text = render_spec_text({"labels": [fact_def_props_only]})

        # Collect existing Arguments from Phase 1 output
        arguments: List[Dict[str, Any]] = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Argument"]
        if not arguments:
            logger.info("Phase 9: no Argument nodes present; skipping Facts generation")
            return {"status": "facts_phase9_skipped"}

        # Prepare crew using Phase 2 agent config
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements={},
        )

        next_idx = 1 + len(self.state.nodes_accumulated or [])
        facts_created_total = 0
        
        # Build cumulative catalog of facts as we process arguments
        # AI will check this catalog and decide whether to reuse or create new
        facts_catalog: List[Dict[str, Any]] = []

        for arg_idx, arg_node in enumerate(arguments):
            try:
                arg_props = arg_node.get("properties") or {}
                arg_ctx_json = json.dumps(arg_props, ensure_ascii=False)
                
                # Prepare facts catalog for AI to check for reuse
                facts_catalog_json = json.dumps(facts_catalog, ensure_ascii=False)
                
                # Compose task: generate multiple facts supporting this argument
                desc = (
                    "Read the document text (provided below) and extract Facts that support the following Argument.\n\n"
                    "CRITICAL: Extract information ONLY from the provided case text. Do not use general knowledge, external information, or assumptions. If information is not explicitly or implicitly present in the text, do not include it.\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                    "Argument (properties JSON):\n" + arg_ctx_json + "\n\n"
                    "EXISTING FACTS (already created):\n" + facts_catalog_json + "\n\n"
                    "Guidance:\n"
                    "- BE COMPREHENSIVE: Extract ALL facts from the case text that support this argument.\n"
                    "- Check the existing facts catalog above. ONLY reuse a fact if it is EXACTLY the same fact (same content, same alleged_by, same proved status).\n"
                    "- When in doubt, create a new fact rather than reusing. It's better to have distinct facts than to conflate different facts.\n"
                    "- Produce a JSON object: { facts: [ { temp_id?: string, fact?: <Fact properties> }, ... ] }.\n"
                    "- For REUSING an IDENTICAL existing fact: include only 'temp_id' (omit 'fact').\n"
                    "- For CREATING a new fact: include only 'fact' with properties (omit 'temp_id').\n"
                    "- Each fact MUST be relevant to this argument and MUST be present in the case text above.\n"
                    "- There can be many facts per argument - extract all of them from the text.\n"
                    "- Match the Fact schema properties exactly (include all required; optional when supported).\n"
                    "- Enforce types/enums/date formats; extract from text only; avoid invention.\n\n"
                    "INSTRUCTIONS (from flow map):\n" + instructions + "\n\n"
                    "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                    "SCHEMA PROPERTIES for 'Fact':\n" + spec_text + "\n\n"
                )
                task = crew.phase2_extract_facts_task(desc)
                single_crew = Crew(
                    agents=[crew.phase2_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                result = single_crew.kickoff()
                # Parse facts array
                if isinstance(result, str):
                    data = json.loads(result)
                elif isinstance(result, dict):
                    data = result
                else:
                    data = json.loads(str(result))
                facts_list = data.get("facts") if isinstance(data, dict) else None
                if not isinstance(facts_list, list):
                    facts_list = []

                # Process each fact - AI decides to reuse or create
                for item in facts_list:
                    if not isinstance(item, dict):
                        continue
                    
                    reuse_temp_id = item.get("temp_id")
                    fact_props = item.get("fact")
                    
                    # Determine if reusing or creating
                    if isinstance(reuse_temp_id, str) and reuse_temp_id:
                        # AI chose to reuse existing fact
                        fact_temp_id = reuse_temp_id
                        logger.debug(f"Phase 9: AI reusing existing Fact ({fact_temp_id})")
                    elif isinstance(fact_props, dict):
                        # AI creating new fact
                        try:
                            if fact_model is not None:
                                inst = fact_model(**fact_props)
                                clean_props = inst.model_dump(exclude_none=True)
                            else:
                                clean_props = fact_props
                        except Exception:
                            clean_props = {k: v for k, v in fact_props.items() if isinstance(k, str)}

                        fact_temp_id = f"n{next_idx}"
                        next_idx += 1
                        node = {"temp_id": fact_temp_id, "label": "Fact", "properties": clean_props}
                        self.state.nodes_accumulated.append(node)
                        facts_created_total += 1
                        
                        # Add to catalog for future iterations (minimal info: text summary)
                        fact_text = clean_props.get("text", "")
                        fact_text_short = fact_text[:150] if isinstance(fact_text, str) else ""
                        facts_catalog.append({
                            "temp_id": fact_temp_id,
                            "text": fact_text_short,
                            "alleged_by": clean_props.get("alleged_by"),
                            "proved": clean_props.get("proved")
                        })
                    else:
                        logger.warning(f"Phase 9: Fact item has neither temp_id nor fact: {item}")
                        continue
                    
                    # Create edge: Argument -> Fact (get relationship label from schema)
                    try:
                        arg_temp_id = arg_node.get("temp_id")
                        if isinstance(arg_temp_id, str) and arg_temp_id:
                            # Get the correct relationship label from schema
                            rel_label = get_relationship_label_for_edge("Argument", "Fact", self.state.rels_by_label or {})
                            if rel_label:
                                edge = {"from": arg_temp_id, "to": fact_temp_id, "label": rel_label, "properties": {}}
                                self.state.edges_accumulated.append(edge)
                            else:
                                logger.warning("Phase 2: No relationship found in schema for Argument -> Fact")
                    except Exception as e:
                        logger.warning(f"Phase 9: Failed to create edge for fact: {e}")
            except Exception as e:
                logger.warning(f"Phase 9: fact generation for an Argument failed: {e}")
                continue

        try:
            unique_facts = len(facts_catalog)
            logger.info(f"Phase 2: completed (facts_created={facts_created_total})")
            logger.info(f"Phase 2: total unique facts - {unique_facts} (AI-driven deduplication)")
        except Exception:
            logger.info("Phase 9: Facts generation completed")
        
        # Publish progress
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 9 complete: Generated facts for arguments", "phase9", 85)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        
        return {"status": "facts_phase9_done"}

    @listen(phase9_extract_facts)
    def phase10_extract_supports(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: generate Witnesses and Evidence for each Fact, and link via SUPPORTED_BY_WITNESS/EVIDENCE
        logger.info("Phase 10: generating Witnesses and Evidence per Fact and linking edges")
        tools = []

        # Load flow_map entries for Witness and Evidence
        try:
            import os
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
            with open(flow_map_path, "r") as f:
                flow_map = json.load(f)
        except Exception:
            flow_map = []

        def get_fm_entry(lbl: str) -> Dict[str, Any]:
            for e in (flow_map or []):
                if isinstance(e, dict) and e.get("label") == lbl:
                    return e
            return {}

        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        def_map = {ld.get("label"): ld for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str)}

        witness_model = (self.state.models_by_label or {}).get("Witness")
        evidence_model = (self.state.models_by_label or {}).get("Evidence")
        witness_spec = ""
        if def_map.get("Witness"):
            wdef = def_map.get("Witness")
            wdef_props_only = {"label": wdef.get("label"), "properties": wdef.get("properties", [])}
            witness_spec = render_spec_text({"labels": [wdef_props_only]})
        evidence_spec = ""
        if def_map.get("Evidence"):
            edef = def_map.get("Evidence")
            edef_props_only = {"label": edef.get("label"), "properties": edef.get("properties", [])}
            evidence_spec = render_spec_text({"labels": [edef_props_only]})

        fm_w = get_fm_entry("Witness")
        fm_e = get_fm_entry("Evidence")
        instructions_w = fm_w.get("instructions") or ""
        instructions_e = fm_e.get("instructions") or ""
        examples_w = json.dumps(fm_w.get("examples") or [], ensure_ascii=False)
        examples_e = json.dumps(fm_e.get("examples") or [], ensure_ascii=False)

        facts = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Fact"]
        if not facts:
            logger.info("Phase 10: no Fact nodes present; skipping supports generation")
            return {"status": "supports_phase10_skipped"}

        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements={},
        )

        next_idx = 1 + len(self.state.nodes_accumulated or [])
        witnesses_created = 0
        evidence_created = 0
        edges_created = 0
        
        # Build cumulative catalog of witnesses and evidence as we process facts
        # AI will check these catalogs and decide whether to reuse or create new
        witnesses_catalog: List[Dict[str, Any]] = []
        evidence_catalog: List[Dict[str, Any]] = []

        for fact_idx, fact in enumerate(facts):
            try:
                fact_props = fact.get("properties") or {}
                fact_ctx_json = json.dumps(fact_props, ensure_ascii=False)
                
                # Prepare catalogs for AI to check for reuse
                witnesses_catalog_json = json.dumps(witnesses_catalog, ensure_ascii=False)
                evidence_catalog_json = json.dumps(evidence_catalog, ensure_ascii=False)
                
                desc = (
                    "Read the document text (provided below) and generate Witnesses and Evidence that support the following Fact.\n\n"
                    "CRITICAL: Extract information ONLY from the provided case text. Do not use general knowledge, external information, or assumptions. If information is not explicitly or implicitly present in the text, do not include it.\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                    "Fact (properties JSON):\n" + fact_ctx_json + "\n\n"
                    "EXISTING WITNESSES (already created):\n" + witnesses_catalog_json + "\n\n"
                    "EXISTING EVIDENCE (already created):\n" + evidence_catalog_json + "\n\n"
                    "Guidance:\n"
                    "- BE COMPREHENSIVE: Extract ALL witnesses and evidence from the case text that support this fact.\n"
                    "- Check the existing catalogs above. ONLY reuse if it is EXACTLY the same witness/evidence (same person/document).\n"
                    "- When in doubt, create new rather than reusing. It's better to have distinct items than to conflate different ones.\n"
                    "- Return JSON as { witnesses: [ { temp_id?: string, node?: <Witness properties>, support_strength: number } ], evidence: [ { temp_id?: string, node?: <Evidence properties>, support_strength: number } ] }.\n"
                    "- For REUSING an IDENTICAL existing item: include only 'temp_id' and 'support_strength' (omit 'node').\n"
                    "- For CREATING a new item: include only 'node' and 'support_strength' (omit 'temp_id').\n"
                    "- Each item MUST support this Fact and MUST be mentioned in the case text above.\n"
                    "- support_strength: 0 to 100 (percent) based on what's in the text.\n"
                    "- Match schema properties strictly; include required; enforce types/enums/dates.\n"
                    "- Extract from text only; do not invent or assume details not in the text.\n\n"
                    "WITNESS INSTRUCTIONS:\n" + instructions_w + "\n\n"
                    "WITNESS EXAMPLES (partial):\n" + examples_w + "\n\n"
                    "SCHEMA PROPERTIES for 'Witness':\n" + witness_spec + "\n\n"
                    "EVIDENCE INSTRUCTIONS:\n" + instructions_e + "\n\n"
                    "EVIDENCE EXAMPLES (partial):\n" + examples_e + "\n\n"
                    "SCHEMA PROPERTIES for 'Evidence':\n" + evidence_spec + "\n\n"
                )
                task = crew.phase3_extract_supports_task(desc)
                single_crew = Crew(
                    agents=[crew.phase2_extract_agent()],
                    tasks=[task],
                    process=Process.sequential,
                )
                result = single_crew.kickoff()

                if isinstance(result, str):
                    data = json.loads(result)
                elif isinstance(result, dict):
                    data = result
                else:
                    data = json.loads(str(result))

                witnesses = data.get("witnesses") if isinstance(data, dict) else None
                evidences = data.get("evidence") if isinstance(data, dict) else None
                if not isinstance(witnesses, list):
                    witnesses = []
                if not isinstance(evidences, list):
                    evidences = []

                # Witnesses - AI decides to reuse or create
                for item in witnesses:
                    try:
                        if not isinstance(item, dict):
                            continue
                        
                        strength = item.get("support_strength")
                        reuse_temp_id = item.get("temp_id")
                        node_props = item.get("node")
                        
                        # Determine if reusing or creating
                        if isinstance(reuse_temp_id, str) and reuse_temp_id:
                            # AI chose to reuse existing witness
                            wid = reuse_temp_id
                            logger.debug(f"Phase 10: AI reusing existing Witness ({wid})")
                        elif isinstance(node_props, dict):
                            # AI creating new witness
                            try:
                                if witness_model is not None:
                                    inst = witness_model(**node_props)
                                    clean_props = inst.model_dump(exclude_none=True)
                                else:
                                    clean_props = node_props
                            except Exception:
                                clean_props = {k: v for k, v in node_props.items() if isinstance(k, str)}
                            
                            wid = f"n{next_idx}"
                            next_idx += 1
                            wnode = {"temp_id": wid, "label": "Witness", "properties": clean_props}
                            self.state.nodes_accumulated.append(wnode)
                            witnesses_created += 1
                            
                            # Add to catalog for future iterations (minimal info)
                            witnesses_catalog.append({
                                "temp_id": wid,
                                "name": clean_props.get("name"),
                                "type": clean_props.get("type")
                            })
                        else:
                            logger.warning(f"Phase 10: Witness item has neither temp_id nor node: {item}")
                            continue
                        
                        # Create edge to this fact (get relationship label from schema)
                        try:
                            s_val = float(strength) if isinstance(strength, (int, float)) or (isinstance(strength, str) and strength.strip()) else None
                        except Exception:
                            s_val = None
                        eprops = {"support_strength": s_val if s_val is not None else 0.0}
                        # Get the correct relationship label from schema
                        rel_label = get_relationship_label_for_edge("Fact", "Witness", self.state.rels_by_label or {})
                        if rel_label:
                            self.state.edges_accumulated.append({"from": fact.get("temp_id"), "to": wid, "label": rel_label, "properties": eprops})
                            edges_created += 1
                        else:
                            logger.warning("Phase 3: No relationship found in schema for Fact -> Witness")
                    except Exception as e:
                        logger.warning(f"Phase 10: Failed to process witness: {e}")
                        continue

                # Evidence - AI decides to reuse or create
                for item in evidences:
                    try:
                        if not isinstance(item, dict):
                            continue
                        
                        strength = item.get("support_strength")
                        reuse_temp_id = item.get("temp_id")
                        node_props = item.get("node")
                        
                        # Determine if reusing or creating
                        if isinstance(reuse_temp_id, str) and reuse_temp_id:
                            # AI chose to reuse existing evidence
                            eid = reuse_temp_id
                            logger.debug(f"Phase 10: AI reusing existing Evidence ({eid})")
                        elif isinstance(node_props, dict):
                            # AI creating new evidence
                            try:
                                if evidence_model is not None:
                                    inst = evidence_model(**node_props)
                                    clean_props = inst.model_dump(exclude_none=True)
                                else:
                                    clean_props = node_props
                            except Exception:
                                clean_props = {k: v for k, v in node_props.items() if isinstance(k, str)}
                            
                            eid = f"n{next_idx}"
                            next_idx += 1
                            enode = {"temp_id": eid, "label": "Evidence", "properties": clean_props}
                            self.state.nodes_accumulated.append(enode)
                            evidence_created += 1
                            
                            # Add to catalog for future iterations (minimal info: type and first 100 chars of description)
                            desc = clean_props.get("description", "")
                            desc_short = desc[:100] if isinstance(desc, str) else ""
                            evidence_catalog.append({
                                "temp_id": eid,
                                "type": clean_props.get("type"),
                                "description": desc_short
                            })
                        else:
                            logger.warning(f"Phase 10: Evidence item has neither temp_id nor node: {item}")
                            continue
                        
                        # Create edge to this fact (get relationship label from schema)
                        try:
                            s_val = float(strength) if isinstance(strength, (int, float)) or (isinstance(strength, str) and strength.strip()) else None
                        except Exception:
                            s_val = None
                        eprops = {"support_strength": s_val if s_val is not None else 0.0}
                        # Get the correct relationship label from schema
                        rel_label = get_relationship_label_for_edge("Fact", "Evidence", self.state.rels_by_label or {})
                        if rel_label:
                            self.state.edges_accumulated.append({"from": fact.get("temp_id"), "to": eid, "label": rel_label, "properties": eprops})
                            edges_created += 1
                        else:
                            logger.warning("Phase 3: No relationship found in schema for Fact -> Evidence")
                    except Exception as e:
                        logger.warning(f"Phase 10: Failed to process evidence: {e}")
                        continue
            except Exception as e:
                logger.warning(f"Phase 10: supports generation for a Fact failed: {e}")
                continue

        try:
            unique_witnesses = len(witnesses_catalog)
            unique_evidence = len(evidence_catalog)
            logger.info(f"Phase 3: completed (witnesses_created={witnesses_created}, evidence_created={evidence_created}, edges_added={edges_created})")
            logger.info(f"Phase 3: total unique items - {unique_witnesses} witnesses, {unique_evidence} evidence (AI-driven deduplication)")
        except Exception:
            logger.info("Phase 10: supports generation completed")
        
        # Publish progress
        if self.state.progress_callback:
            try:
                self.state.progress_callback("Phase 10 complete: Generated witnesses and evidence", "phase10", 95)
            except Exception as e:
                logger.warning(f"Failed to publish progress: {e}")
        
        return {"status": "supports_phase10_done"}

    @listen(phase10_extract_supports)
    def phase11_validate_and_repair(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Quick validation mode: just return the data without deep validation
        # The flow phases already enforce schema rules, so validation is mainly for catching edge cases
        import os
        skip_validation = os.getenv("SKIP_CASE_VALIDATION", "false").lower() in ("true", "1", "yes")
        
        if skip_validation:
            logger.info("Phase 11 (Validation): skipped (SKIP_CASE_VALIDATION=true)")
            return {
                "case_name": self.state.filename,
                "nodes": self.state.nodes_accumulated or [],
                "edges": self.state.edges_accumulated or []
            }
        
        # Pull validators from state prepared in prepare_schema
        models_by_label = self.state.models_by_label
        rels_by_label = self.state.rels_by_label
        props_meta_by_label = self.state.props_meta_by_label
        label_flags_by_label = self.state.label_flags_by_label

        # Fallback if state doesn't expose mapping (Flow state is BaseModel; use previous ctx return pattern)
        if not models_by_label or not rels_by_label or not props_meta_by_label:
            return {"case_name": self.state.filename, "nodes": self.state.nodes_accumulated or [], "edges": self.state.edges_accumulated or []}

        logger.info("Phase 11 (Validation): starting")
        
        # Unwrap 'raw' field if present (CrewAI sometimes wraps structured output)
        nodes = self.state.nodes_accumulated or []
        unwrapped_nodes = []
        unwrap_count = 0
        for node in nodes:
            if isinstance(node, dict):
                props = node.get("properties") or {}
                # Check if properties are wrapped in 'raw' field with JSON string
                if isinstance(props, dict) and len(props) == 1 and "raw" in props:
                    try:
                        raw_val = props.get("raw")
                        if isinstance(raw_val, str):
                            unwrapped_props = json.loads(raw_val)
                            # Create new node dict with unwrapped properties
                            node = dict(node)  # shallow copy to preserve other fields
                            node["properties"] = unwrapped_props
                            unwrap_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to unwrap 'raw' field for {node.get('temp_id')}: {e}")
                unwrapped_nodes.append(node)
        
        if unwrap_count > 0:
            logger.info(f"Unwrapped 'raw' field from {unwrap_count} nodes")
        
        edges = self.state.edges_accumulated or []
        logger.info(f"Validation: input has {len(unwrapped_nodes)} nodes, {len(edges)} edges")
        
        payload = {
            "case_name": self.state.filename,
            "nodes": unwrapped_nodes,
            "edges": edges,
        }
        cleaned, errors = validate_case_graph(
            payload,
            models_by_label,
            rels_by_label,
            props_meta_by_label,
            label_flags_by_label=label_flags_by_label,
            existing_catalog_by_label=self.state.existing_catalog_by_label if isinstance(self.state.existing_catalog_by_label, dict) else None,
        )
        
        # Log validation results
        if errors:
            logger.warning(f"Phase 11 (Validation): found {len(errors)} errors")
            logger.warning(f"Phase 11 (Validation): first 5 errors: {errors[:5]}")
            logger.info(f"Validation: cleaned output has {len(cleaned.get('nodes', []))} nodes, {len(cleaned.get('edges', []))} edges")
        
        if not errors:
            try:
                logger.info(f"Validation: passed (nodes={len(cleaned.get('nodes', []))}, edges={len(cleaned.get('edges', []))})")
            except Exception:
                logger.info("Phase 11 (Validation): passed with no errors")
            return cleaned

        # Return cleaned output with validation errors logged
        # Note: LLM repair was removed because it was slow (~5min) and removed all edges
        logger.warning(f"Phase 11 (Validation): returning cleaned output with {len(errors)} errors, {len(cleaned.get('edges', []))} edges retained")
        return cleaned


