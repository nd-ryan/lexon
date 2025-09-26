from crewai.flow.flow import Flow, listen, start
from crewai import Crew, Process
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
        tools = [read_document_tool]
        allowed_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and ld.get("case_unique") is True and not ld.get("ai_ignore")]
        replacements = {
            "ALLOWED_LABELS": ", ".join(allowed_labels),
            "SCHEMA_SPEC_TEXT": self.state.schema_spec_text or "",
        }
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements=replacements,
        )
        logger.info(f"Phase 1: extracting case_unique nodes for file: {self.state.filename}")
        # Execute only the phase 1 task
        task = crew.extract_task_phase1()
        single_crew = Crew(
            agents=[crew.extract_agent_phase1()],
            tasks=[task],
            process=Process.sequential,
        )
        raw_result = single_crew.kickoff()
        logger.info("Phase 1 completed")
        # Debug: log the raw_result shape
        try:
            has_p = hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None
            has_r = hasattr(raw_result, 'raw') and getattr(raw_result, 'raw') is not None
            has_td = hasattr(raw_result, 'to_dict')
            logger.info(f"CrewOutput debug: type={type(raw_result)}, has_pydantic={has_p}, has_raw={has_r}, has_to_dict={has_td}")
        except Exception:
            pass

        # Normalize and accumulate payload
        try:
            payload = None
            # Prefer CrewAI structured output when available
            if hasattr(raw_result, 'pydantic') and getattr(raw_result, 'pydantic') is not None:
                p = getattr(raw_result, 'pydantic')
                if isinstance(p, CaseGraph):
                    payload = p.model_dump(by_alias=True)
                elif hasattr(p, 'model_dump'):
                    payload = p.model_dump()  # type: ignore[attr-defined]
                elif isinstance(p, dict):
                    payload = p
            if payload is None:
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
            nodes = (payload or {}).get("nodes") or []
            if isinstance(nodes, list):
                filtered = [n for n in nodes if isinstance(n, dict) and n.get("label") in allowed_labels]
                has_case = any(isinstance(n, dict) and n.get("label") == "Case" for n in filtered)
                if not has_case:
                    next_idx = 1 + len(self.state.nodes_accumulated or [])
                    filtered.append({
                        "temp_id": f"n{next_idx}",
                        "label": "Case",
                        "properties": {"name": ((payload or {}).get("case_name") or self.state.filename or "")}
                    })
                self.state.nodes_accumulated.extend(filtered)  # type: ignore[arg-type]
            return {"status": "phase1_done"}
        except Exception as e:
            logger.error(f"Phase 1 normalization failed: {e}")
            raise

        # Return payload as-is; UI is now derived from schema.json on the client
        return {"status": "phase1_done"}

    @listen(extract_case_unique)
    def extract_non_unique_creatable(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2: extract labels where case_unique is false and can_create_new is true
        tools = [read_document_tool]
        allowed_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and not ld.get("case_unique") and ld.get("can_create_new") and not ld.get("ai_ignore")]
        replacements = {
            "ALLOWED_LABELS": ", ".join(allowed_labels),
            "SCHEMA_SPEC_TEXT": self.state.schema_spec_text or "",
        }
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements=replacements,
        )
        logger.info("Phase 2: extracting non-unique creatable nodes")
        # Execute only the phase 2 task
        task = crew.extract_task_phase2()
        single_crew = Crew(
            agents=[crew.extract_agent_phase2()],
            tasks=[task],
            process=Process.sequential,
        )
        raw_result = single_crew.kickoff()
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
                filtered = [n for n in nodes if isinstance(n, dict) and n.get("label") in allowed_labels]
                self.state.nodes_accumulated.extend(filtered)  # type: ignore[arg-type]
            return {"status": "phase2_done"}
        except Exception as e:
            logger.error(f"Phase 2 normalization failed: {e}")
            raise

    @listen(extract_non_unique_creatable)
    def dedup_with_llm(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2b: LLM-assisted dedup via dedicated agent/task
        logger.info("Phase 2b: starting LLM-based dedup via agent")
        from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
        labels_for_dedup = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and not ld.get("case_unique") and ld.get("can_create_new") and not ld.get("ai_ignore")]
        candidates = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") in labels_for_dedup]
        others = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") not in labels_for_dedup]
        catalogs: Dict[str, List[str]] = {}
        for lbl in labels_for_dedup:
            rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
            names: List[str] = []
            for r in rows:
                if isinstance(r, dict) and r.get("name") is not None:
                    names.append(str(r.get("name")))
            catalogs[lbl] = names
        # Build one-off crew instance with no tools, use task text to pass inputs
        crew = _CaseCrew(
            self.state.file_path,
            self.state.filename,
            self.state.case_id,
            tools=[],
            replacements={
                "CANDIDATE_NODES_JSON": json.dumps({"nodes": candidates}, ensure_ascii=False),
                "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
            },
        )
        task = crew.dedup_task_phase2b()
        single_crew = Crew(
            agents=[crew.dedup_agent_phase2b()],
            tasks=[task],
            process=Process.sequential,
        )
        result = single_crew.kickoff()
        try:
            text = str(result)
            data = json.loads(text) if isinstance(result, str) else (result if isinstance(result, dict) else json.loads(str(result)))
            deduped = data.get("nodes") if isinstance(data, dict) else None
            if not isinstance(deduped, list):
                deduped = candidates
        except Exception:
            deduped = candidates
        self.state.nodes_accumulated = others + (deduped or [])
        logger.info("Phase 2b: dedup completed")
        return {"status": "dedup_done"}

    @listen(dedup_with_llm)
    def assign_existing_only(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: choose existing nodes for labels with can_create_new=false via dedicated agent/task
        logger.info("Phase 3: assigning existing-only nodes from catalogs via agent")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            restricted_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and ld.get("can_create_new") is False and not ld.get("ai_ignore")]
            catalogs: Dict[str, List[str]] = {}
            for lbl in restricted_labels:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                names: List[str] = []
                for r in rows:
                    if isinstance(r, dict) and r.get("name") is not None:
                        names.append(str(r.get("name")))
                catalogs[lbl] = names
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
            task = crew.select_existing_task_phase3()
            single_crew = Crew(
                agents=[crew.select_existing_agent_phase3()],
                tasks=[task],
                process=Process.sequential,
            )
            result = single_crew.kickoff()
            selected: Dict[str, List[str]] = {}
            try:
                text = str(result)
                data = json.loads(text) if isinstance(result, str) else (result if isinstance(result, dict) else json.loads(str(result)))
                sel = data.get("selected") if isinstance(data, dict) else None
                if isinstance(sel, dict):
                    for k, v in sel.items():
                        if isinstance(k, str) and isinstance(v, list):
                            selected[k] = [str(x) for x in v]
            except Exception:
                selected = {}

            # Convert selections into nodes with new temp_ids
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl, names in selected.items():
                for nm in names:
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": {"name": nm}}
                    next_idx += 1
                    (self.state.nodes_accumulated or []).append(node)
            logger.info("Phase 3: existing-only assignment completed")
            return {"status": "existing_assigned"}
        except Exception:
            logger.warning("Phase 3: existing-only assignment skipped due to error; continuing")
            return {"status": "existing_assign_skipped"}

    @listen(assign_existing_only)
    def assign_relationships(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: assign relationships via crew task with schema-driven instructions
        logger.info("Phase 4: assigning relationships via relationships_task_phase4 agent")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            nodes = self.state.nodes_accumulated or []
            spec_text = self.state.schema_spec_text or ""
            crew = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "SCHEMA_SPEC_TEXT": spec_text,
                    "NODES_JSON": json.dumps({"nodes": nodes}, ensure_ascii=False),
                },
            )
            task = crew.relationships_task_phase4()
            single_crew = Crew(
                agents=[crew.relationships_agent_phase4()],
                tasks=[task],
                process=Process.sequential,
            )
            result = single_crew.kickoff()
            # Parse edges JSON
            edges: List[Dict[str, Any]] = []
            try:
                text = str(result)
                data = json.loads(text) if isinstance(result, str) else (result if isinstance(result, dict) else json.loads(str(result)))
                eg = data.get("edges") if isinstance(data, dict) else None
                if isinstance(eg, list):
                    for e in eg:
                        if not isinstance(e, dict):
                            continue
                        if not isinstance(e.get("from"), str) or not isinstance(e.get("to"), str) or not isinstance(e.get("label"), str):
                            continue
                        if e.get("properties") is not None and not isinstance(e.get("properties"), dict):
                            continue
                        edges.append({
                            "from": e.get("from"),
                            "to": e.get("to"),
                            "label": e.get("label"),
                            "properties": e.get("properties") or {},
                        })
            except Exception:
                edges = []
            # Validate references; drop edges that reference missing temp_ids
            temp_ids = {n.get("temp_id") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
            edges = [e for e in edges if e.get("from") in temp_ids and e.get("to") in temp_ids]
            self.state.edges_accumulated = edges
            logger.info(f"Phase 4: agent produced {len(edges)} edges")
            return {"status": "edges_assigned"}
        except Exception as e:
            self.state.edges_accumulated = []
            logger.warning(f"Phase 4: relationships assignment failed; continuing without edges: {e}")
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

        logger.info("Validation: starting")
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
            logger.info("Validation: passed with no errors")
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
                    logger.info("Validation: repair succeeded")
                    return repaired_clean
        except Exception:
            pass

        logger.warning("Validation: returning cleaned output with errors present")
        return cleaned


