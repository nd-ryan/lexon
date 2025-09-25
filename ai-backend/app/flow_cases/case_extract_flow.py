from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from .crews.case_crew.case_crew import CaseCrew
from .tools.io_tools import read_document_tool, get_neo4j_schema_tool, fetch_neo4j_schema
from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models, validate_case_graph, render_spec_text
from app.models.case_graph import CaseGraph
from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
import json
from datetime import datetime, timezone


logger = setup_logger("case-extract-flow")


class CaseExtractState(BaseModel):
    file_path: str = ""
    filename: str = ""
    case_id: str = ""
    # Runtime additions shared across flow steps
    schema_spec: Dict[str, Any] | None = None
    schema_spec_text: str = ""
    models_by_label: Dict[str, Any] | None = None
    rels_by_label: Dict[str, Dict[str, str]] | None = None
    props_meta_by_label: Dict[str, Dict[str, Dict[str, Any]]] | None = None
    label_flags_by_label: Dict[str, Dict[str, bool]] | None = None
    existing_catalog_by_label: Dict[str, List[Dict[str, Any]]] | None = None
    # Working context
    document_text: str = ""
    nodes_accumulated: List[Dict[str, Any]] | None = None
    edges_accumulated: List[Dict[str, Any]] | None = None


class CaseExtractFlow(Flow[CaseExtractState]):
    @start()
    def kickoff(self) -> Dict[str, Any]:
        return {
            "file_path": self.state.file_path,
            "filename": self.state.filename,
            "case_id": self.state.case_id,
            "status": "initialized"
        }

    @listen(kickoff)
    def prepare_schema(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
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

        # Read document once and store text
        try:
            doc_res = read_document_tool(self.state.file_path, self.state.filename)
            if isinstance(doc_res, dict) and doc_res.get("ok"):
                self.state.document_text = str(doc_res.get("text") or "")
            else:
                self.state.document_text = ""
        except Exception:
            self.state.document_text = ""

        # Build existing catalogs for labels where can_create_new is False
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
                if flags.get("can_create_new") is False:
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
        logger.info("prepare_schema: completed")
        print("[prepare_schema] completed")
        return ctx

    @listen(prepare_schema)
    def extract_case_unique(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 1: extract only labels where case_unique is true
        tools = [read_document_tool, get_neo4j_schema_tool]
        allowed_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and ld.get("case_unique") is True and not ld.get("ai_ignore")]
        extra = (
            "PHASE: 1 (case_unique=true)\n"
            "Only output nodes whose labels are in this list: " + ", ".join(allowed_labels) + "\n"
            "Do not output any relationships in this phase.\n"
            "Do not include any ai_ignore labels or properties.\n"
        )
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            schema_spec_text=self.state.schema_spec_text or "",
            extra_instructions=extra,
        )
        logger.info(f"Phase 1: extracting case_unique nodes for file: {self.state.filename}")
        raw_result = crew.crew().kickoff()
        logger.info("Phase 1 completed")
        # Debug: log the raw_result shape
        try:
            has_p = hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None
            has_r = hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None
            has_td = hasattr(raw_result, 'to_dict')
            logger.info(f"CrewOutput debug: type={type(raw_result)}, has_pydantic={has_p}, has_raw={has_r}, has_to_dict={has_td}")
        except Exception:
            pass

        # Normalize and forward payload for validation
        try:
            # Prefer CrewAI structured output when available
            if hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None:
                p = getattr(raw_result, 'pydantic')
                # If Crew already returned a Pydantic model of our type
                if isinstance(p, CaseGraph):
                    return p.model_dump(by_alias=True)
                # If Crew returned some other BaseModel, coerce via dict
                if hasattr(p, 'model_dump'):
                    return p.model_dump()  # type: ignore[attr-defined]
                # If Crew returned a dict-like structure
                if isinstance(p, dict):
                    return p

            # Next try a dict conversion
            if hasattr(raw_result, 'to_dict'):
                payload = raw_result.to_dict()  # type: ignore[attr-defined]
            elif isinstance(raw_result, dict):
                payload = raw_result
            elif hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None:
                raw = getattr(raw_result, 'raw')
                if hasattr(raw, 'model_dump'):
                    payload = raw.model_dump()  # type: ignore[attr-defined]
                elif isinstance(raw, str):
                    payload = json.loads(raw)
                else:
                    payload = raw
            elif isinstance(raw_result, str):
                payload = json.loads(raw_result)
            else:
                # Last resort: dump to string then parse if possible
                payload = json.loads(str(raw_result))

            # Accumulate nodes; edges should be empty in this phase
            nodes = payload.get("nodes") or []
            if isinstance(nodes, list):
                self.state.nodes_accumulated.extend(nodes)  # type: ignore[arg-type]
            return {"status": "phase1_done"}
        except Exception as e:
            logger.error(f"Structured output validation failed: {e}")
            raise

        # Return payload as-is; UI is now derived from schema.json on the client
        return payload

    @listen(extract_case_unique)
    def extract_non_unique_creatable(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2: extract labels where case_unique is false and can_create_new is true
        tools = [read_document_tool, get_neo4j_schema_tool]
        allowed_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and not ld.get("case_unique") and ld.get("can_create_new") and not ld.get("ai_ignore")]
        extra = (
            "PHASE: 2 (case_unique=false && can_create_new=true)\n"
            "Only output nodes whose labels are in this list: " + ", ".join(allowed_labels) + "\n"
            "Do not output any relationships in this phase.\n"
            "Do not include any ai_ignore labels or properties.\n"
        )
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            schema_spec_text=self.state.schema_spec_text or "",
            extra_instructions=extra,
        )
        logger.info("Phase 2: extracting non-unique creatable nodes")
        raw_result = crew.crew().kickoff()
        logger.info("Phase 2 completed")
        try:
            if hasattr(raw_result, 'to_dict'):
                payload = raw_result.to_dict()  # type: ignore[attr-defined]
            elif isinstance(raw_result, dict):
                payload = raw_result
            elif hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None:
                raw = getattr(raw_result, 'raw')
                if hasattr(raw, 'model_dump'):
                    payload = raw.model_dump()  # type: ignore[attr-defined]
                elif isinstance(raw, str):
                    payload = json.loads(raw)
                else:
                    payload = raw
            elif isinstance(raw_result, str):
                payload = json.loads(raw_result)
            else:
                payload = json.loads(str(raw_result))

            nodes = payload.get("nodes") or []
            if isinstance(nodes, list):
                self.state.nodes_accumulated.extend(nodes)  # type: ignore[arg-type]
            return {"status": "phase2_done"}
        except Exception as e:
            logger.error(f"Phase 2 normalization failed: {e}")
            raise

    @listen(extract_non_unique_creatable)
    def dedup_with_llm(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2b: LLM-assisted dedup for case_unique=false & can_create_new=true labels
        try:
            from crewai import LLM
            llm = LLM(model="gpt-4.1", temperature=0)
            labels_for_dedup = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and not ld.get("case_unique") and ld.get("can_create_new") and not ld.get("ai_ignore")]
            # Prepare catalogs for these labels as matching context
            catalogs_text_parts: List[str] = []
            for lbl in labels_for_dedup:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                sample_names = []
                for r in rows[:200]:
                    if isinstance(r, dict):
                        if r.get("name") is not None:
                            sample_names.append(str(r.get("name")))
                if sample_names:
                    catalogs_text_parts.append(f"Existing {lbl} names: " + ", ".join(sample_names))

            candidates = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") in labels_for_dedup]
            others = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") not in labels_for_dedup]

            instr = (
                "You are deduplicating nodes against existing data.\n"
                "For each candidate node, if it likely matches an existing entity (by name or clear synonym), keep the existing name exactly; otherwise keep as-is.\n"
                "Return JSON with the same structure: {\"nodes\": [...]} with updated properties (e.g., standardized names).\n"
            )
            user_content = (
                ("\n\n".join(catalogs_text_parts) if catalogs_text_parts else "") +
                "\n\nCANDIDATE NODES JSON:\n" + json.dumps({"nodes": candidates}, ensure_ascii=False)
            )
            resp = llm.call([{ "role": "user", "content": instr + "\n\n" + user_content }])
            payload = None
            if resp:
                text = str(resp).strip()
                if text.startswith("```"):
                    lines = text.split('\n')
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                payload = json.loads(text)
            if not isinstance(payload, dict):
                payload = {"nodes": candidates}
            deduped = payload.get("nodes") or candidates
            self.state.nodes_accumulated = others + deduped
            return {"status": "dedup_done"}
        except Exception:
            # On failure, keep original candidates
            return {"status": "dedup_skipped"}

    @listen(dedup_with_llm)
    def assign_existing_only(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: choose existing nodes for labels with can_create_new=false
        try:
            from crewai import LLM
            llm = LLM(model="gpt-4.1", temperature=0)
            restricted_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and ld.get("can_create_new") is False and not ld.get("ai_ignore")]
            catalogs: Dict[str, List[str]] = {}
            for lbl in restricted_labels:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                names: List[str] = []
                for r in rows:
                    if isinstance(r, dict) and r.get("name") is not None:
                        names.append(str(r.get("name")))
                catalogs[lbl] = names

            instr = (
                "Select existing nodes for the case from provided catalogs.\n"
                "Use the case text to identify which existing entities apply.\n"
                "Return JSON as {\"selected\": { label: [names...] }}."
            )
            user_content = (
                "CASE TEXT:\n" + (self.state.document_text or "") +
                "\n\nCATALOGS:\n" + json.dumps(catalogs, ensure_ascii=False)
            )
            resp = llm.call([{ "role": "user", "content": instr + "\n\n" + user_content }])
            selected: Dict[str, List[str]] = {}
            if resp:
                text = str(resp).strip()
                if text.startswith("```"):
                    lines = text.split('\n')
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    sel = parsed.get("selected")
                    if isinstance(sel, dict):
                        for k, v in sel.items():
                            if isinstance(k, str) and isinstance(v, list):
                                selected[k] = [str(x) for x in v]

            # Convert selections into nodes with new temp_ids
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl, names in selected.items():
                for nm in names:
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": {"name": nm}}
                    next_idx += 1
                    (self.state.nodes_accumulated or []).append(node)
            return {"status": "existing_assigned"}
        except Exception:
            return {"status": "existing_assign_skipped"}

    @listen(assign_existing_only)
    def assign_relationships(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: use LLM to assign relationships based on schema and nodes list
        try:
            from crewai import LLM
            llm = LLM(model="gpt-4.1", temperature=0)
            nodes = self.state.nodes_accumulated or []
            instr = (
                "Assign relationships between nodes based on the schema rules.\n"
                "Return JSON as {\"edges\": [ {from, to, label, properties} ... ] }.\n"
                "Only use relationship types allowed for each source label and target label from the schema."
            )
            user_content = (
                "SCHEMA SPEC:\n" + (self.state.schema_spec_text or "") +
                "\n\nNODES JSON:\n" + json.dumps({"nodes": nodes}, ensure_ascii=False)
            )
            resp = llm.call([{ "role": "user", "content": instr + "\n\n" + user_content }])
            edges: List[Dict[str, Any]] = []
            if resp:
                text = str(resp).strip()
                if text.startswith("```"):
                    lines = text.split('\n')
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    eg = parsed.get("edges")
                    if isinstance(eg, list):
                        edges = [e for e in eg if isinstance(e, dict)]
            self.state.edges_accumulated = edges
            return {"status": "edges_assigned"}
        except Exception:
            self.state.edges_accumulated = []
            return {"status": "edges_assign_skipped"}

    @listen(assign_relationships)
    def validate_and_repair(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Pull validators from state prepared in prepare_schema
        models_by_label = self.state.models_by_label
        rels_by_label = self.state.rels_by_label
        props_meta_by_label = self.state.props_meta_by_label
        label_flags_by_label = self.state.label_flags_by_label

        # Fallback if state doesn't expose mapping (Flow state is BaseModel; use previous ctx return pattern)
        if not models_by_label or not rels_by_label or not props_meta_by_label:
            return {"case_name": self.state.filename, "nodes": self.state.nodes_accumulated or [], "edges": self.state.edges_accumulated or []}

        payload = {
            "case_name": self.state.filename,
            "nodes": self.state.nodes_accumulated or [],
            "edges": self.state.edges_accumulated or [],
        }
        cleaned, errors = validate_case_graph(
            payload,
            models_by_label,
            rels_by_label,
            props_meta_by_label,
            label_flags_by_label=label_flags_by_label,
            existing_catalog_by_label=self.state.existing_catalog_by_label if isinstance(self.state.existing_catalog_by_label, dict) else None,
        )
        if not errors:
            return cleaned

        # One repair round
        try:
            from crewai import LLM
            spec_text = self.state.schema_spec_text or ""
            llm = LLM(model="gpt-4.1", temperature=0)
            instruction = (
                "You produced a CaseGraph JSON that did not fully comply with the schema rules. "
                "Correct it so it passes validation. Return ONLY the corrected JSON.\n\n"
                "Rules recap:\n"
                "- Use only listed labels and properties. Include all required properties.\n"
                "- Enforce data types (str/int/bool/list[str]).\n"
                "- Enforce enum options if provided.\n"
                "- Enforce date format YYYY-MM-DD when specified.\n"
                "- If a label has can_create_new=false, you must match an existing node from the catalogs.\n"
                "- Do not create nodes or properties marked ai_ignore.\n"
                "- Edges: label allowed for the source label and targets the expected label; from/to refer to existing node temp_ids.\n"
            )
            user_content = (
                f"SCHEMA SPEC:\n{spec_text}\n\n"
                + "VALIDATION ERRORS:\n- " + "\n- ".join(errors) + "\n\n"
                + f"CURRENT JSON:\n{json.dumps(cleaned, ensure_ascii=False)}\n\n"
                + ("CATALOGS:\n" + json.dumps(self.state.existing_catalog_by_label or {}, ensure_ascii=False) + "\n\n")
                + "Return ONLY JSON."
            )
            resp = llm.call([{ "role": "user", "content": instruction + "\n\n" + user_content }])
            if resp:
                text = str(resp).strip()
                if text.startswith("```"):
                    lines = text.split('\n')
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                repaired = json.loads(text)
                repaired_clean, repaired_errors = validate_case_graph(
                    repaired,
                    models_by_label,
                    rels_by_label,
                    props_meta_by_label,
                    label_flags_by_label=label_flags_by_label,
                    existing_catalog_by_label=self.state.existing_catalog_by_label if isinstance(self.state.existing_catalog_by_label, dict) else None,
                )
                if not repaired_errors:
                    return repaired_clean
        except Exception:
            pass

        return cleaned


