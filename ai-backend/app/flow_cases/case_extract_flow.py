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

        # Build existing catalogs for:
        # - labels where can_create_new is False (phase 3)
        # - labels where case_unique is False and can_create_new is True (phase 2b)
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
                should_fetch = False
                try:
                    is_creatable = flags.get("can_create_new") is True
                    is_non_creatable = flags.get("can_create_new") is False
                    is_case_unique = flags.get("case_unique") is True
                    # Phase 3 needs catalogs for non-creatable labels
                    # Phase 2b needs catalogs for non-unique, creatable labels
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
        logger.info("prepare_schema: completed")
        print("[prepare_schema] completed")
        return ctx

    @listen(prepare_schema)
    def extract_case_unique(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 1: extract only labels where case_unique is true, one LLM call per label
        logger.info(f"Phase 1 (per-node): starting for file {self.state.filename}")
        tools = [read_document_tool]

        # Load flow_map to determine ordering and instructions/examples
        try:
            import os
            flow_map_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "flow_map.json"))
            with open(flow_map_path, "r") as f:
                flow_map = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load flow_map.json; falling back to schema order: {e}")
            flow_map = []

        # Build list of Phase 1 labels driven by flow_map order when possible
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        def_map = {ld.get("label"): ld for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str)}

        # Prefer flow_map phase markers
        fm_phase1 = [e for e in (flow_map or []) if isinstance(e, dict) and e.get("phase") == 1 and not e.get("ai_ignore")]
        schema_all = [ld.get("label") for ld in labels_src if isinstance(ld, dict) and isinstance(ld.get("label"), str) and not ld.get("ai_ignore")]

        ordered_labels: List[str] = []
        fm_labels = [e.get("label") for e in fm_phase1 if isinstance(e.get("label"), str)]
        for lbl in fm_labels:
            if lbl in schema_all and lbl not in ordered_labels:
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

        for label in ordered_labels:
            try:
                # Build single-label spec for properties rendering
                ldef = def_map.get(label)
                if not isinstance(ldef, dict):
                    continue
                single_spec = {"labels": [ldef]}
                props_spec_text = render_spec_text(single_spec)

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
                    "Read the document and extract ONLY the properties for the label '" + label + "'.\n\n"
                    "Guidance:\n"
                    "- Return ONLY JSON matching the schema properties for this label.\n"
                    "- Include all required properties; optional when supported by the text.\n"
                    "- Enforce types, enums, and date formats exactly as specified.\n"
                    "- Prefer facts present in the text; avoid invention.\n"
                    "- Do not output temp_id, label, or relationships here. Properties only.\n\n"
                    "INSTRUCTIONS (from flow map):\n" + instructions + "\n\n"
                    "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                    "SCHEMA PROPERTIES for '" + label + "':\n" + props_spec_text + "\n\n"
                    "Required tool: read_document_tool(file_path=\"" + self.state.file_path + "\", filename=\"" + self.state.filename + "\")."
                )

                # Create and run the task
                dyn_task = crew.extract_task_phase1_single_node(task_desc, props_model)  # type: ignore[arg-type]
        single_crew = Crew(
            agents=[crew.extract_agent_phase1()],
                    tasks=[dyn_task],
            process=Process.sequential,
        )
                result = single_crew.kickoff()

                # Parse pydantic output into properties dict
                if hasattr(result, 'model_dump'):
                    properties = result.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                elif isinstance(result, dict):
                    properties = result
                else:
                    properties = json.loads(str(result))

                node = {"temp_id": f"n{next_idx}", "label": label, "properties": properties}
                next_idx += 1
                (self.state.nodes_accumulated or []).append(node)
                produced_labels.append(label)
            except Exception as e:
                logger.warning(f"Phase 1 per-node task for {label} failed: {e}")
                continue

        # Ensure a Case node exists; if missing, add minimal fallback
        if "Case" in ordered_labels and ("Case" not in produced_labels):
            try:
                node = {"temp_id": f"n{next_idx}", "label": "Case", "properties": {"name": self.state.filename}}
                (self.state.nodes_accumulated or []).append(node)
            except Exception:
                pass

        logger.info("Phase 1 (per-node): completed")
        return {"status": "phase1_done"}

        # Return payload as-is; UI is now derived from schema.json on the client
        return {"status": "phase1_done"}

    @listen(extract_case_unique)
    def extract_facts_phase2(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # New Phase 2: generate Fact nodes per Argument; many facts may support each argument
        logger.info("Phase 2: generating Facts per Argument")
        tools = [read_document_tool]

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
        spec_text = render_spec_text({"labels": [fact_def]}) if isinstance(fact_def, dict) else ""

        # Collect existing Arguments from Phase 1 output
        arguments: List[Dict[str, Any]] = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Argument"]
        if not arguments:
            logger.info("Phase 2: no Argument nodes present; skipping Facts generation")
            return {"status": "facts_phase2_skipped"}

        # Prepare crew using Phase 2 agent config
        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements={},
        )

        next_idx = 1 + len(self.state.nodes_accumulated or [])

        for arg_node in arguments:
            try:
                arg_props = arg_node.get("properties") or {}
                arg_ctx_json = json.dumps(arg_props, ensure_ascii=False)
                # Compose task: generate multiple facts supporting this argument
                desc = (
                    "Read the document and extract Facts that support the following Argument.\n\n"
                    "Argument (properties JSON):\n" + arg_ctx_json + "\n\n"
                    "Guidance:\n"
                    "- Produce a JSON object: { facts: [ { ...Fact properties... }, ... ] }.\n"
                    "- Each fact MUST be relevant to this argument. There can be many facts per argument.\n"
                    "- Match the Fact schema properties exactly (include all required; optional when supported).\n"
                    "- Enforce types/enums/date formats; prefer text-grounded content; avoid invention.\n"
                    "- Do not include temp_id, label, or relationships in the output.\n\n"
                    "INSTRUCTIONS (from flow map):\n" + instructions + "\n\n"
                    "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                    "SCHEMA PROPERTIES for 'Fact':\n" + spec_text + "\n\n"
                    "Required tool: read_document_tool(file_path=\"" + self.state.file_path + "\", filename=\"" + self.state.filename + "\")."
                )
                task = crew.extract_task_phase2_facts(desc)
                single_crew = Crew(
                    agents=[crew.extract_agent_phase2()],
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

                for fprops in facts_list:
                    if not isinstance(fprops, dict):
                        continue
                    # Validate against Fact model if available
                    try:
                        if fact_model is not None:
                            inst = fact_model(**fprops)
                            clean_props = inst.model_dump(exclude_none=True)
                else:
                            clean_props = fprops
                    except Exception:
                        clean_props = {k: v for k, v in fprops.items() if isinstance(k, str)}

                    # Create Fact node
                    fact_temp_id = f"n{next_idx}"
                    node = {"temp_id": fact_temp_id, "label": "Fact", "properties": clean_props}
                    next_idx += 1
                    (self.state.nodes_accumulated or []).append(node)
                    # Create edge: Argument RELIES_ON Fact
                    try:
                        arg_temp_id = arg_node.get("temp_id")
                        if isinstance(arg_temp_id, str) and arg_temp_id:
                            edge = {"from": arg_temp_id, "to": fact_temp_id, "label": "RELIES_ON", "properties": {}}
                            (self.state.edges_accumulated or []).append(edge)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Phase 2: fact generation for an Argument failed: {e}")
                continue

        logger.info("Phase 2: Facts generation completed")
        return {"status": "facts_phase2_done"}

    @listen(extract_facts_phase2)
    def extract_supports_phase3(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: generate Witnesses and Evidence for each Fact, and link via SUPPORTED_BY
        logger.info("Phase 3: generating Witnesses and Evidence per Fact and linking edges")
        tools = [read_document_tool]

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
        witness_spec = render_spec_text({"labels": [def_map.get("Witness")]}) if def_map.get("Witness") else ""
        evidence_spec = render_spec_text({"labels": [def_map.get("Evidence")]}) if def_map.get("Evidence") else ""

        fm_w = get_fm_entry("Witness")
        fm_e = get_fm_entry("Evidence")
        instructions_w = fm_w.get("instructions") or ""
        instructions_e = fm_e.get("instructions") or ""
        examples_w = json.dumps(fm_w.get("examples") or [], ensure_ascii=False)
        examples_e = json.dumps(fm_e.get("examples") or [], ensure_ascii=False)

        facts = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Fact"]
        if not facts:
            logger.info("Phase 3: no Fact nodes present; skipping supports generation")
            return {"status": "supports_phase3_skipped"}

        crew = CaseCrew(
            file_path=self.state.file_path,
            filename=self.state.filename,
            case_id=self.state.case_id,
            tools=tools,
            replacements={},
        )

                    next_idx = 1 + len(self.state.nodes_accumulated or [])

        for fact in facts:
            try:
                fact_props = fact.get("properties") or {}
                fact_ctx_json = json.dumps(fact_props, ensure_ascii=False)
                desc = (
                    "Read the document and generate Witnesses and Evidence that support the following Fact.\n\n"
                    "Fact (properties JSON):\n" + fact_ctx_json + "\n\n"
                    "Guidance:\n"
                    "- Return JSON as { witnesses: [ { node: <Witness properties>, support_strength: number } ], evidence: [ { node: <Evidence properties>, support_strength: number } ] }.\n"
                    "- Each item MUST support this Fact.\n"
                    "- support_strength: 0 to 100 (percent).\n"
                    "- Match schema properties strictly; include required; enforce types/enums/dates; avoid invention.\n"
                    "- Do not include temp_id, label, or relationships inside node objects.\n\n"
                    "WITNESS INSTRUCTIONS:\n" + instructions_w + "\n\n"
                    "WITNESS EXAMPLES (partial):\n" + examples_w + "\n\n"
                    "SCHEMA PROPERTIES for 'Witness':\n" + witness_spec + "\n\n"
                    "EVIDENCE INSTRUCTIONS:\n" + instructions_e + "\n\n"
                    "EVIDENCE EXAMPLES (partial):\n" + examples_e + "\n\n"
                    "SCHEMA PROPERTIES for 'Evidence':\n" + evidence_spec + "\n\n"
                    "Required tool: read_document_tool(file_path=\"" + self.state.file_path + "\", filename=\"" + self.state.filename + "\")."
                )
                task = crew.extract_task_phase3_supports(desc)
                single_crew = Crew(
                    agents=[crew.extract_agent_phase2()],
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

                # Witnesses
                for item in witnesses:
                    try:
                        node_props = item.get("node") if isinstance(item, dict) else None
                        strength = item.get("support_strength") if isinstance(item, dict) else None
                        if not isinstance(node_props, dict):
                            continue
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
                        (self.state.nodes_accumulated or []).append(wnode)
                        try:
                            s_val = float(strength) if isinstance(strength, (int, float)) or (isinstance(strength, str) and strength.strip()) else None
                        except Exception:
                            s_val = None
                        eprops = {"support_strength": s_val if s_val is not None else 0.0}
                        self.state.edges_accumulated.append({"from": fact.get("temp_id"), "to": wid, "label": "SUPPORTED_BY", "properties": eprops})
                    except Exception:
                        continue

                # Evidence
                for item in evidences:
                    try:
                        node_props = item.get("node") if isinstance(item, dict) else None
                        strength = item.get("support_strength") if isinstance(item, dict) else None
                        if not isinstance(node_props, dict):
                            continue
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
                        (self.state.nodes_accumulated or []).append(enode)
                        try:
                            s_val = float(strength) if isinstance(strength, (int, float)) or (isinstance(strength, str) and strength.strip()) else None
                        except Exception:
                            s_val = None
                        eprops = {"support_strength": s_val if s_val is not None else 0.0}
                        self.state.edges_accumulated.append({"from": fact.get("temp_id"), "to": eid, "label": "SUPPORTED_BY", "properties": eprops})
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Phase 3: supports generation for a Fact failed: {e}")
                continue

        logger.info("Phase 3: supports generation completed")
        return {"status": "supports_phase3_done"}

    @listen(extract_supports_phase3)
    def assign_case_unique_relationships_phase4(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: add remaining relationships among case-unique labels (excluding RELIES_ON and SUPPORTED_BY)
        logger.info("Phase 4: assigning remaining relationships among case-unique nodes")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            nodes = self.state.nodes_accumulated or []
            # Build pruned schema spec: only case_unique labels and rels to case_unique targets
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            case_unique_set: set[str] = set()
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str):
                    continue
                flags = (self.state.label_flags_by_label or {}).get(lbl, {})
                if flags.get("ai_ignore"):
                    continue
                if flags.get("case_unique") is True:
                    case_unique_set.add(lbl)

            keep_labels: List[Dict[str, Any]] = []
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str) or lbl not in case_unique_set:
                    continue
                pruned_rels: Dict[str, str] = {}
                for rk, rv in (ldef.get("relationships") or {}).items():
                    if not (isinstance(rk, str) and isinstance(rv, str)):
                        continue
                    if rk in {"RELIES_ON", "SUPPORTED_BY"}:  # already assigned earlier
                        continue
                    if rv in case_unique_set:
                        pruned_rels[rk] = rv
                new_def = dict(ldef)
                new_def["relationships"] = pruned_rels
                keep_labels.append(new_def)

            spec_text = render_spec_text({"labels": keep_labels})
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
            task = crew.relationships_task_phase3()
            single_crew = Crew(
                agents=[crew.relationships_agent_phase3()],
                tasks=[task],
                process=Process.sequential,
            )
            result = single_crew.kickoff()
            # Parse edges JSON and merge
            edges_new: List[Dict[str, Any]] = []
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
                        if e.get("label") in {"RELIES_ON", "SUPPORTED_BY"}:
                            continue
                        edges_new.append({
                            "from": e.get("from"),
                            "to": e.get("to"),
                            "label": e.get("label"),
                            "properties": e.get("properties") or {},
                        })
            except Exception:
                edges_new = []

            # Deduplicate edges (by from,to,label)
            existing = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for e in edges_new:
                key = (e.get("from"), e.get("to"), e.get("label"))
                if key not in existing:
                    (self.state.edges_accumulated or []).append(e)
                    existing.add(key)

            logger.info(f"Phase 4: agent produced {len(edges_new)} new edges among case-unique nodes")
            return {"status": "edges_assigned_phase4"}
        except Exception as e:
            logger.warning(f"Phase 4: relationship assignment failed; continuing without new edges: {e}")
            return {"status": "edges_assign_skipped_phase4"}

    @listen(assign_case_unique_relationships_phase4)
    def extract_non_unique_creatable(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 2 (legacy): extract labels where case_unique is false and can_create_new is true
        # Phase 2: extract labels where case_unique is false and can_create_new is true
        tools = [read_document_tool]
        labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
        phase2_labels = [ld for ld in labels_src if isinstance(ld, dict) and not ld.get("case_unique") and ld.get("can_create_new") and not ld.get("ai_ignore")]
        phase2_spec = {"labels": phase2_labels}
        phase2_spec_text = render_spec_text(phase2_spec)
        allowed_labels = [ld.get("label") for ld in phase2_labels if isinstance(ld, dict)]

        # Build relationship requirements between already generated nodes and non-case-unique creatable labels
        generated_nodes = self.state.nodes_accumulated or []
        generated_labels: set[str] = set()
        for n in generated_nodes:
            if isinstance(n, dict) and isinstance(n.get("label"), str):
                generated_labels.add(str(n.get("label")))

        non_unique_creatable: set[str] = set([l for l in allowed_labels if isinstance(l, str)])
        requirements: List[Dict[str, str]] = []
        # forward relationships: generated -> non_unique_creatable
        for ldef in labels_src:
            if not isinstance(ldef, dict):
                continue
            src = ldef.get("label")
            if not isinstance(src, str):
                continue
            rels = ldef.get("relationships") or {}
            if not isinstance(rels, dict):
                continue
            for rel_label, target in rels.items():
                if not isinstance(rel_label, str):
                    continue
                # target may be string or object; normalize to string
                tgt = target.get("target") if isinstance(target, dict) else target
                if not isinstance(tgt, str):
                    continue
                if src in generated_labels and tgt in non_unique_creatable:
                    requirements.append({"from": src, "label": rel_label, "to": tgt})
        # reverse relationships: non_unique_creatable -> generated
        for ldef in labels_src:
            if not isinstance(ldef, dict):
                continue
            src = ldef.get("label")
            if not isinstance(src, str):
                continue
            rels = ldef.get("relationships") or {}
            if not isinstance(rels, dict):
                continue
            for rel_label, target in rels.items():
                if not isinstance(rel_label, str):
                    continue
                tgt = target.get("target") if isinstance(target, dict) else target
                if not isinstance(tgt, str):
                    continue
                if src in non_unique_creatable and tgt in generated_labels:
                    requirements.append({"from": src, "label": rel_label, "to": tgt})

        replacements = {
            "SCHEMA_SPEC_TEXT": phase2_spec_text,
            "GENERATED_NODES_JSON": json.dumps({"nodes": generated_nodes}, ensure_ascii=False),
            "REL_REQUIREMENTS_JSON": json.dumps({"requirements": requirements}, ensure_ascii=False),
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
        catalogs: Dict[str, List[Dict[str, Any]]] = {}
        for lbl in labels_for_dedup:
            rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
            entries: List[Dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                entry: Dict[str, Any] = {}
                if r.get("name") is not None:
                    entry["name"] = str(r.get("name"))
                if r.get("description") is not None:
                    entry["description"] = str(r.get("description"))
                if r.get("text") is not None:
                    entry["text"] = str(r.get("text"))
                if isinstance(lbl, str) and lbl.lower() == "law" and r.get("citation") is not None:
                    entry["citation"] = str(r.get("citation"))
                if entry:
                    entries.append(entry)
            catalogs[lbl] = entries
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
    def assign_internal_relationships(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: assign relationships among generated nodes only (exclude non-creatable labels)
        logger.info("Phase 3: assigning relationships among generated nodes (excluding non-creatable labels)")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            nodes = self.state.nodes_accumulated or []
            # Build pruned schema spec excluding non-creatable labels and any relationships to them
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            keep_set: set[str] = set()
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str):
                    continue
                flags = (self.state.label_flags_by_label or {}).get(lbl, {})
                if flags.get("ai_ignore"):
                    continue
                if flags.get("can_create_new") is False:
                    continue
                keep_set.add(lbl)
            keep_labels: List[Dict[str, Any]] = []
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str) or lbl not in keep_set:
                    continue
                rels = {}
                for rk, rv in (ldef.get("relationships") or {}).items():
                    if isinstance(rk, str) and isinstance(rv, str) and rv in keep_set:
                        rels[rk] = rv
                new_def = dict(ldef)
                new_def["relationships"] = rels
                keep_labels.append(new_def)
            spec_text = render_spec_text({"labels": keep_labels})
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
            task = crew.relationships_task_phase3()
            single_crew = Crew(
                agents=[crew.relationships_agent_phase3()],
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
            temp_ids = {n.get("temp_id") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
            edges = [e for e in edges if e.get("from") in temp_ids and e.get("to") in temp_ids]
            self.state.edges_accumulated = edges
            logger.info(f"Phase 3: agent produced {len(edges)} edges among generated nodes")
            return {"status": "edges_assigned_phase3"}
        except Exception as e:
            self.state.edges_accumulated = []
            logger.warning(f"Phase 3: relationship assignment failed; continuing without edges: {e}")
            return {"status": "edges_assign_skipped_phase3"}

    @listen(assign_internal_relationships)
    def select_existing_and_assign_relationships(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: select non-creatable catalog nodes and assign relationships involving them
        logger.info("Phase 4: selecting existing-only nodes and assigning relationships with catalogs")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # First, select existing-only nodes
            restricted_labels = [ld.get("label") for ld in (self.state.schema_spec or {}).get("labels", []) if isinstance(ld, dict) and ld.get("can_create_new") is False and not ld.get("ai_ignore")]
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in restricted_labels:
                rows = (self.state.existing_catalog_by_label or {}).get(lbl) or []
                entries: List[Dict[str, Any]] = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    entry: Dict[str, Any] = {}
                    if r.get("name") is not None:
                        entry["name"] = str(r.get("name"))
                    if r.get("description") is not None:
                        entry["description"] = str(r.get("description"))
                    if r.get("text") is not None:
                        entry["text"] = str(r.get("text"))
                    if isinstance(lbl, str) and lbl.lower() == "law" and r.get("citation") is not None:
                        entry["citation"] = str(r.get("citation"))
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Build relationship requirements for creatable <-> non-creatable pairs
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            generated_nodes = self.state.nodes_accumulated or []
            generated_labels: set[str] = set([str(n.get("label")) for n in generated_nodes if isinstance(n, dict) and isinstance(n.get("label"), str)])
            non_creatable: set[str] = set([l for l in restricted_labels if isinstance(l, str)])
            requirements_phase4: List[Dict[str, str]] = []
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                src = ldef.get("label")
                if not isinstance(src, str):
                    continue
                rels = ldef.get("relationships") or {}
                if not isinstance(rels, dict):
                    continue
                for rel_label, target in rels.items():
                    if not isinstance(rel_label, str):
                        continue
                    tgt = target.get("target") if isinstance(target, dict) else target
                    if not isinstance(tgt, str):
                        continue
                    if src in generated_labels and tgt in non_creatable:
                        requirements_phase4.append({"from": src, "label": rel_label, "to": tgt})
                    if src in non_creatable and tgt in generated_labels:
                        requirements_phase4.append({"from": src, "label": rel_label, "to": tgt})

            crew_sel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "CASE_TEXT": self.state.document_text or "",
                    "CATALOGS_JSON": json.dumps(catalogs, ensure_ascii=False),
                    "REL_REQUIREMENTS_JSON": json.dumps({"requirements": requirements_phase4}, ensure_ascii=False),
                },
            )
            task_sel = crew_sel.select_existing_task_phase4()
            single_crew_sel = Crew(
                agents=[crew_sel.select_existing_agent_phase4()],
                tasks=[task_sel],
                process=Process.sequential,
            )
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

            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl, names in selected.items():
                for nm in names:
                    key = "name"
                    try:
                        props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                        if "name" in props_meta:
                            key = "name"
                        elif "description" in props_meta:
                            key = "description"
                        elif "text" in props_meta:
                            key = "text"
                    except Exception:
                        key = "name"
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": {key: nm}}
                    next_idx += 1
                    (self.state.nodes_accumulated or []).append(node)

            # Now assign relationships restricted to those to/from non-creatable labels
            restricted_set: set[str] = set([l for l in restricted_labels if isinstance(l, str)])
            involved_labels: set[str] = set()
            label_defs: List[Dict[str, Any]] = []
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str):
                    continue
                rels_involving: Dict[str, str] = {}
                for rk, rv in (ldef.get("relationships") or {}).items():
                    if isinstance(rk, str) and isinstance(rv, str) and (lbl in restricted_set or rv in restricted_set):
                        rels_involving[rk] = rv
                        involved_labels.add(lbl)
                        involved_labels.add(rv)
                if rels_involving:
                    new_def = dict(ldef)
                    new_def["relationships"] = rels_involving
                    label_defs.append(new_def)
            pruned_defs: List[Dict[str, Any]] = []
            for d in label_defs:
                if d.get("label") in involved_labels:
                    pruned_defs.append(d)
            spec_text_phase4 = render_spec_text({"labels": pruned_defs})

            nodes = self.state.nodes_accumulated or []
            crew_rel = _CaseCrew(
                self.state.file_path,
                self.state.filename,
                self.state.case_id,
                tools=[],
                replacements={
                    "SCHEMA_SPEC_TEXT": spec_text_phase4,
                    "NODES_JSON": json.dumps({"nodes": nodes}, ensure_ascii=False),
                    "REL_REQUIREMENTS_JSON": json.dumps({"requirements": requirements_phase4}, ensure_ascii=False),
                },
            )
            task_rel = crew_rel.relationships_task_phase3()
            single_crew_rel = Crew(
                agents=[crew_rel.relationships_agent_phase3()],
                tasks=[task_rel],
                process=Process.sequential,
            )
            result_rel = single_crew_rel.kickoff()
            edges_new: List[Dict[str, Any]] = []
            try:
                text = str(result_rel)
                data = json.loads(text) if isinstance(result_rel, str) else (result_rel if isinstance(result_rel, dict) else json.loads(str(result_rel)))
                eg = data.get("edges") if isinstance(data, dict) else None
                if isinstance(eg, list):
                    for e in eg:
                        if not isinstance(e, dict):
                            continue
                        if not isinstance(e.get("from"), str) or not isinstance(e.get("to"), str) or not isinstance(e.get("label"), str):
                            continue
                        if e.get("properties") is not None and not isinstance(e.get("properties"), dict):
                            continue
                        edges_new.append({
                            "from": e.get("from"),
                            "to": e.get("to"),
                            "label": e.get("label"),
                            "properties": e.get("properties") or {},
                        })
            except Exception:
                edges_new = []
            temp_ids = {n.get("temp_id") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
            edges_new = [e for e in edges_new if e.get("from") in temp_ids and e.get("to") in temp_ids]
            self.state.edges_accumulated = (self.state.edges_accumulated or []) + edges_new
            logger.info(f"Phase 4: agent added {len(edges_new)} edges involving catalog nodes")
            return {"status": "existing_and_edges_assigned"}
        except Exception:
            logger.warning("Phase 4: existing-only selection/relationship assignment skipped due to error; continuing")
            return {"status": "existing_assign_skipped"}

    @listen(select_existing_and_assign_relationships)
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


