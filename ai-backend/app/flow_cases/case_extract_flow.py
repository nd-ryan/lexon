from crewai.flow.flow import Flow, listen, start
from crewai import Crew, Process
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from .crews.case_crew.case_crew import CaseCrew
from .tools.io_tools import read_document_tool, fetch_neo4j_schema
from app.lib.schema_runtime import prune_ui_schema_for_llm, build_property_models, validate_case_graph, render_spec_text, build_relationship_property_models
from app.models.case_graph import CaseGraph
from app.lib.logging_config import setup_logger
from app.lib.neo4j_client import neo4j_client
import json
from datetime import datetime


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
        logger.info("prepare_schema: completed")
        print("[prepare_schema] completed")
        return ctx

    @listen(phase0_prepare_schema)
    def phase1_extract_case_unique(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 1: extract only labels where case_unique is true, one LLM call per label
        logger.info(f"Phase 1 (per-node): starting for file {self.state.filename}")
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
                    "Read the document text (provided below) and extract ONLY the properties for the label '" + label + "'.\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
                    "Guidance:\n"
                    "- Return ONLY JSON matching the schema properties for this label.\n"
                    "- Include all required properties; optional when supported by the text.\n"
                    "- Enforce types, enums, and date formats exactly as specified.\n"
                    "- Prefer facts present in the text; avoid invention.\n"
                    "- Do not output temp_id, label, or relationships here. Properties only.\n\n"
                    "INSTRUCTIONS (from flow map):\n" + instructions + "\n\n"
                    "EXAMPLES (illustrative, may be partial):\n" + examples_json + "\n\n"
                    "SCHEMA PROPERTIES for '" + label + "':\n" + props_spec_text + "\n\n"
                )

                # Create and run the task
                dyn_task = crew.phase1_extract_single_node_task(task_desc, props_model)  # type: ignore[arg-type]
                single_crew = Crew(
                    agents=[crew.phase1_extract_agent()],
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

    @listen(phase1_extract_case_unique)
    def phase2_extract_facts(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # New Phase 2: generate Fact nodes per Argument; many facts may support each argument
        logger.info("Phase 2: generating Facts per Argument")
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
                    "Read the document text (provided below) and extract Facts that support the following Argument.\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
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

                # Create a Fact node and RELIES_ON edge for each extracted fact
                for fprops in facts_list:
                    if not isinstance(fprops, dict):
                        continue
                    try:
                        if fact_model is not None:
                            inst = fact_model(**fprops)
                            clean_props = inst.model_dump(exclude_none=True)
                        else:
                            clean_props = fprops
                    except Exception:
                        clean_props = {k: v for k, v in fprops.items() if isinstance(k, str)}
                fact_temp_id = f"n{next_idx}"
                next_idx += 1
                node = {"temp_id": fact_temp_id, "label": "Fact", "properties": clean_props}
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

    @listen(phase2_extract_facts)
    def phase3_extract_supports(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 3: generate Witnesses and Evidence for each Fact, and link via SUPPORTED_BY
        logger.info("Phase 3: generating Witnesses and Evidence per Fact and linking edges")
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
                    "Read the document text (provided below) and generate Witnesses and Evidence that support the following Fact.\n\n"
                    "CASE_TEXT:\n" + (self.state.document_text or "") + "\n\n"
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

    @listen(phase3_extract_supports)
    def phase4_assign_case_unique_relationships(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 4: add remaining relationships among case-unique labels (excluding RELIES_ON and SUPPORTED_BY)
        logger.info("Phase 4: assigning remaining relationships among case-unique nodes")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            all_nodes = self.state.nodes_accumulated or []
            # Build pruned schema spec: only case_unique labels and rels to case_unique targets
            # Prefer full schema to preserve relationship property schemas
            labels_src = self.state.schema_full if isinstance(self.state.schema_full, list) else ((self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else [])
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

            # Limit to labels present in current nodes
            present_labels: set[str] = set()
            for n in all_nodes:
                if isinstance(n, dict) and isinstance(n.get("label"), str) and n.get("label") in case_unique_set:
                    present_labels.add(n.get("label"))
            # Filter nodes to only case-unique present labels
            nodes = [n for n in all_nodes if isinstance(n, dict) and n.get("label") in present_labels]

            keep_labels: List[Dict[str, Any]] = []
            for ldef in labels_src:
                if not isinstance(ldef, dict):
                    continue
                lbl = ldef.get("label")
                if not isinstance(lbl, str) or lbl not in present_labels:
                    continue
                pruned_rels: Dict[str, Any] = {}
                for rk, rv in (ldef.get("relationships") or {}).items():
                    if not isinstance(rk, str):
                        continue
                    if rk in {"RELIES_ON", "SUPPORTED_BY"}:  # already assigned earlier
                        continue
                    # rv can be a string target label or an object { target, properties }
                    if isinstance(rv, dict):
                        tgt = rv.get("target")
                        if isinstance(tgt, str) and tgt in present_labels:
                            pruned_rels[rk] = rv  # preserve properties schema
                    elif isinstance(rv, str) and rv in present_labels:
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
            task = crew.phase3_relationships_task()
            single_crew = Crew(
                agents=[crew.phase3_relationships_agent()],
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
                        # Coerce relationship properties via Pydantic when available
                        props = e.get("properties") or {}
                        try:
                            temp_id_to_label = {n.get("temp_id"): n.get("label") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
                            src_label = temp_id_to_label.get(e.get("from"))
                            rel_label = e.get("label")
                            key = (str(src_label), str(rel_label))
                            rel_models = self.state.rel_prop_models_by_key or {}
                            model = rel_models.get(key)  # type: ignore[index]
                            if model is not None and isinstance(props, dict):
                                inst = model(**props)
                                props = inst.model_dump(exclude_none=True)
                        except Exception:
                            pass
                        edges_new.append({
                            "from": e.get("from"),
                            "to": e.get("to"),
                            "label": e.get("label"),
                            "properties": props or {},
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

    @listen(phase4_assign_case_unique_relationships)
    def phase5_select_and_link(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 5: select ReliefType based on Ruling, Forum based on case text, then programmatically add Jurisdiction and edges
        logger.info("Phase 5: selecting ReliefType and Forum; computing Jurisdiction; creating edges")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Prefer full schema to preserve relationship property schemas
            labels_src = self.state.schema_full if isinstance(self.state.schema_full, list) else ((self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else [])
            # Build catalogs for ReliefType and Forum using schema-defined properties
            catalogs: Dict[str, List[Dict[str, Any]]] = {}
            for lbl in ["ReliefType", "Forum"]:
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
                    if entry:
                        entries.append(entry)
                catalogs[lbl] = entries

            # Extract the generated Ruling node properties
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

            # Create selected nodes with appropriate identifying key
            next_idx = 1 + len(self.state.nodes_accumulated or [])
            for lbl in ["ReliefType", "Forum"]:
                names = selected.get(lbl) or []
                for nm in names:
                    key = "name"
                    try:
                        props_meta = (self.state.props_meta_by_label or {}).get(lbl, {})
                        if "name" in props_meta:
                            key = "name"
                        elif lbl == "ReliefType" and "type" in props_meta:
                            key = "type"
                        elif "description" in props_meta:
                            key = "description"
                        elif "text" in props_meta:
                            key = "text"
                    except Exception:
                        key = "name"
                    node = {"temp_id": f"n{next_idx}", "label": lbl, "properties": {key: nm}}
                    next_idx += 1
                    (self.state.nodes_accumulated or []).append(node)

            # Ensure edges for Phase 5 relationships
            try:
                temp_id_to_label: Dict[str, str] = {}
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and isinstance(n.get("temp_id"), str) and isinstance(n.get("label"), str):
                        temp_id_to_label[n.get("temp_id")] = n.get("label")

                def find_first_temp_id(label: str) -> Optional[str]:
                    for n in (self.state.nodes_accumulated or []):
                        if isinstance(n, dict) and n.get("label") == label and isinstance(n.get("temp_id"), str):
                            return n.get("temp_id")
                    return None

                def edge_exists(src_label: str, rel_label: str, tgt_label: str) -> bool:
                    for e in (self.state.edges_accumulated or []):
                        if not isinstance(e, dict):
                            continue
                        fr = e.get("from")
                        to = e.get("to")
                        if not (isinstance(fr, str) and isinstance(to, str)):
                            continue
                        if temp_id_to_label.get(fr) == src_label and temp_id_to_label.get(to) == tgt_label and e.get("label") == rel_label:
                            return True
                    return False

                r_id = find_first_temp_id("Ruling")
                rt_id = find_first_temp_id("ReliefType")
                p_id = find_first_temp_id("Proceeding")
                f_id = find_first_temp_id("Forum")

                # Use relationships agent to generate RESULTS_IN and HEARD_IN edges with properties per schema
                try:
                    labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
                    # Keep only mappings involving Ruling->RESULTS_IN->ReliefType and Proceeding->HEARD_IN->Forum
                    pruned_defs: List[Dict[str, Any]] = []
                    for ldef in labels_src:
                        if not isinstance(ldef, dict):
                            continue
                        lbl = ldef.get("label")
                        if lbl not in {"Ruling", "Proceeding", "ReliefType", "Forum"}:
                            continue
                        rels_obj: Dict[str, Any] = {}
                        for rk, rv in (ldef.get("relationships") or {}).items():
                            if lbl == "Ruling" and rk == "RESULTS_IN":
                                rels_obj[rk] = rv
                            if lbl == "Proceeding" and rk == "HEARD_IN":
                                rels_obj[rk] = rv
                        new_def = dict(ldef)
                        new_def["relationships"] = rels_obj
                        pruned_defs.append(new_def)
                    spec_text_rel = render_spec_text({"labels": pruned_defs})

                    # Embed context so the agent can set required edge property values
                    context_block = json.dumps({
                        "RULING_JSON": ruling_props,
                        "CASE_TEXT": self.state.document_text or ""
                    }, ensure_ascii=False)

                    crew_rel = _CaseCrew(
                        self.state.file_path,
                        self.state.filename,
                        self.state.case_id,
                        tools=[],
                        replacements={
                            "SCHEMA_SPEC_TEXT": spec_text_rel + "\n\nCONTEXT:\n" + context_block,
                            "NODES_JSON": json.dumps({"nodes": [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") in {"Ruling", "ReliefType", "Proceeding", "Forum"}]}, ensure_ascii=False),
                        },
                    )
                    task_rel = crew_rel.phase3_relationships_task()
                    single_crew_rel = Crew(
                        agents=[crew_rel.phase3_relationships_agent()],
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
                                # Coerce relationship properties via Pydantic when available
                                props = e.get("properties") or {}
                                try:
                                    temp_id_to_label = {n.get("temp_id"): n.get("label") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
                                    src_label = temp_id_to_label.get(e.get("from"))
                                    rel_label = e.get("label")
                                    key = (str(src_label), str(rel_label))
                                    rel_models = self.state.rel_prop_models_by_key or {}
                                    model = rel_models.get(key)  # type: ignore[index]
                                    if model is not None and isinstance(props, dict):
                                        inst = model(**props)
                                        props = inst.model_dump(exclude_none=True)
                                except Exception:
                                    pass
                                edges_new.append({
                                    "from": e.get("from"),
                                    "to": e.get("to"),
                                    "label": e.get("label"),
                                    "properties": props or {},
                                })
                    except Exception:
                        edges_new = []
                    temp_ids = {n.get("temp_id") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict)}
                    edges_new = [e for e in edges_new if e.get("from") in temp_ids and e.get("to") in temp_ids]
                    existing = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
                    for e in edges_new:
                        key = (e.get("from"), e.get("to"), e.get("label"))
                        if key not in existing:
                            (self.state.edges_accumulated or []).append(e)
                            existing.add(key)
                except Exception:
                    pass

                # Programmatically fetch Jurisdiction for selected Forum
                try:
                    if f_id:
                        forum_nodes = [n for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("temp_id") == f_id]
                        forum_name = None
                        if forum_nodes:
                            props = forum_nodes[0].get("properties") or {}
                            forum_name = props.get("name") or props.get("text") or props.get("description")
                        if isinstance(forum_name, str) and forum_name.strip():
                            query = "MATCH (f:Forum {name: $name})-[:PART_OF]->(j:Jurisdiction) RETURN properties(j) AS props LIMIT 1"
                            rows = neo4j_client.execute_query(query, params={"name": forum_name})
                            if rows:
                                j_props = rows[0].get("props") if isinstance(rows[0], dict) else None
                                if isinstance(j_props, dict):
                                    j_node_id = find_first_temp_id("Jurisdiction")
                                    if not j_node_id:
                                        j_node_id = f"n{next_idx}"
                                        next_idx += 1
                                        (self.state.nodes_accumulated or []).append({"temp_id": j_node_id, "label": "Jurisdiction", "properties": j_props})
                                    # Forum -> PART_OF -> Jurisdiction
                                    if not edge_exists("Forum", "PART_OF", "Jurisdiction"):
                                        (self.state.edges_accumulated or []).append({"from": f_id, "to": j_node_id, "label": "PART_OF", "properties": {}})
                                    # Case -> IN -> Jurisdiction
                                    c_id = find_first_temp_id("Case")
                                    if c_id and not edge_exists("Case", "IN", "Jurisdiction"):
                                        (self.state.edges_accumulated or []).append({"from": c_id, "to": j_node_id, "label": "IN", "properties": {}})
                except Exception:
                    pass
            except Exception:
                pass

            logger.info("Phase 5: selection and relationships completed")
            return {"status": "phase5_done"}
        except Exception as e:
            logger.warning(f"Phase 5: selection/relationship assignment failed: {e}")
            return {"status": "phase5_skipped"}

    @listen(phase5_select_and_link)
    def phase6_assign_laws(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 6: for each Argument, select or create Law(s) with dedup and add Argument->Law edges
        logger.info("Phase 6: assigning Laws to Arguments with catalog dedup")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            # Collect Arguments
            arguments = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Argument" and isinstance(n.get("temp_id"), str)
            ]
            if not arguments:
                logger.info("Phase 6: no Argument nodes present; skipping law assignment")
                return {"status": "phase6_skipped"}

            # Build Law catalog using schema-defined properties (no hardcoding)
            catalogs: Dict[str, List[Dict[str, Any]]] = {"Law": []}
            try:
                rows = (self.state.existing_catalog_by_label or {}).get("Law") or []
                entries: List[Dict[str, Any]] = []
                # Derive allowed properties for Law from schema meta
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
                    if entry:
                        entries.append(entry)
                catalogs["Law"] = entries
            except Exception:
                catalogs = {"Law": []}

            # Law schema spec text for validation context
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            law_def = next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == "Law"), None)
            law_spec_text = render_spec_text({"labels": [law_def]}) if isinstance(law_def, dict) else ""

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
            # signature uses citation primarily, fallback to name
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
                # clean/validate
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
                    # skip creating duplicate node; find existing id if any
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
                # Create new Law node
                temp_id = f"n{next_idx}"
                next_idx += 1
                (self.state.nodes_accumulated or []).append({"temp_id": temp_id, "label": "Law", "properties": clean_props})
                created_ids_by_index[idx] = temp_id
                if sig:
                    existing_signatures.add(sig)

            # Create Argument -> Law edges (RELIES_ON)
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
                key = (a_id, l_id, "RELIES_ON")
                if key not in existing_edges:
                    (self.state.edges_accumulated or []).append({"from": a_id, "to": l_id, "label": "RELIES_ON", "properties": {}})
                    existing_edges.add(key)

            logger.info("Phase 6: law assignment completed")
            return {"status": "phase6_done"}
        except Exception as e:
            logger.warning(f"Phase 6: law assignment failed: {e}")
            return {"status": "phase6_skipped"}

    @listen(phase6_assign_laws)
    def phase7_assign_issue_related(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 7: per Issue, select/generate Doctrine, Policy, FactPattern with dedup and create edges
        logger.info("Phase 7: assigning Doctrine/Policy/FactPattern per Issue with catalog dedup")
        try:
            from .crews.case_crew.case_crew import CaseCrew as _CaseCrew
            issues = [
                {"temp_id": n.get("temp_id"), "properties": n.get("properties") or {}}
                for n in (self.state.nodes_accumulated or [])
                if isinstance(n, dict) and n.get("label") == "Issue" and isinstance(n.get("temp_id"), str)
            ]
            if not issues:
                logger.info("Phase 7: no Issue nodes present; skipping")
                return {"status": "phase7_skipped"}

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
                        if entry:
                            entries.append(entry)
                    catalogs[lbl] = entries
            except Exception:
                pass

            # Build schema spec snippets
            labels_src = (self.state.schema_spec or {}).get("labels", []) if isinstance(self.state.schema_spec, dict) else []
            def get_def(lbl: str) -> Dict[str, Any] | None:
                return next((ld for ld in labels_src if isinstance(ld, dict) and ld.get("label") == lbl), None)
            spec_text = render_spec_text({"labels": [d for d in [get_def("Doctrine"), get_def("Policy"), get_def("FactPattern")] if d]})

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
                    (self.state.nodes_accumulated or []).append({"temp_id": tid, "label": lbl, "properties": clean})
                    created_ids[lbl][idx] = tid
                    if sig:
                        existing_sig[lbl].add(sig)

            add_items("Doctrine", doctrines, doctrine_model)
            add_items("Policy", policies, policy_model)
            add_items("FactPattern", factpatterns, fp_model)

            # Create Issue relationships
            existing_edges = {(e.get("from"), e.get("to"), e.get("label")) for e in (self.state.edges_accumulated or []) if isinstance(e, dict)}
            for m in issue_map:
                if not isinstance(m, dict):
                    continue
                i_id = m.get("issue_temp_id")
                di = m.get("doctrine_index")
                pi = m.get("policy_index")
                fi = m.get("factpattern_index")
                if isinstance(i_id, str) and isinstance(di, int):
                    d_id = created_ids["Doctrine"].get(di)
                    if isinstance(d_id, str):
                        key = (i_id, d_id, "RELATES_TO")
                        if key not in existing_edges:
                            (self.state.edges_accumulated or []).append({"from": i_id, "to": d_id, "label": "RELATES_TO", "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(pi, int):
                    p_id = created_ids["Policy"].get(pi)
                    if isinstance(p_id, str):
                        key = (i_id, p_id, "RELATES_TO")
                        if key not in existing_edges:
                            (self.state.edges_accumulated or []).append({"from": i_id, "to": p_id, "label": "RELATES_TO", "properties": {}})
                            existing_edges.add(key)
                if isinstance(i_id, str) and isinstance(fi, int):
                    f_id = created_ids["FactPattern"].get(fi)
                    if isinstance(f_id, str):
                        key = (i_id, f_id, "RELATES_TO")
                        if key not in existing_edges:
                            (self.state.edges_accumulated or []).append({"from": i_id, "to": f_id, "label": "RELATES_TO", "properties": {}})
                            existing_edges.add(key)

            logger.info("Phase 7: issue-related assignment completed")
            return {"status": "phase7_done"}
        except Exception as e:
            logger.warning(f"Phase 7: issue-related assignment failed: {e}")
            return {"status": "phase7_skipped"}

    @listen(phase7_assign_issue_related)
    def phase8_assign_parties(self, _: Dict[str, Any]) -> Dict[str, Any]:
        # Phase 8: extract/dedupe Parties and create Case->Party INVOLVES edges with roles
        logger.info("Phase 8: extracting and deduplicating Parties; assigning roles")
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

            # Fuzzy standardization using Neo4j for each generated party name
            def _standardize_party_name(raw_name: str) -> str:
                try:
                    q = (raw_name or "").strip()
                    if not q:
                        return raw_name
                    query = (
                        "MATCH (p:Party) "
                        "WHERE p.name IS NOT NULL AND (toLower(p.name) CONTAINS toLower($q) OR toLower($q) CONTAINS toLower(p.name)) "
                        "RETURN p.name AS name LIMIT 25"
                    )
                    rows = neo4j_client.execute_query(query, {"q": q})
                    names: List[str] = []
                    for r in rows:
                        val = r.get("name")
                        if isinstance(val, str) and val.strip():
                            names.append(val.strip())
                    if not names:
                        return raw_name
                    # Prefer case-insensitive exact
                    for n in names:
                        if n.lower() == q.lower():
                            return n
                    # Heuristic: choose the closest by containment and length similarity
                    def score(candidate: str) -> float:
                        c = candidate.lower()
                        qq = q.lower()
                        contain = (1.0 if (c in qq or qq in c) else 0.0)
                        len_ratio = min(len(c), len(qq)) / max(len(c), len(qq)) if max(len(c), len(qq)) > 0 else 0.0
                        return contain * 0.7 + len_ratio * 0.3
                    best = max(names, key=score)
                    if score(best) >= 0.75:
                        return best
                    return raw_name
                except Exception:
                    return raw_name

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
                    standardized = _standardize_party_name(nm)
                    if standardized and standardized != nm:
                        clean["name"] = standardized
                        nm = standardized
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

            # Create Case -> Party INVOLVES edges with role property
            try:
                c_id = None
                for n in (self.state.nodes_accumulated or []):
                    if isinstance(n, dict) and n.get("label") == "Case" and isinstance(n.get("temp_id"), str):
                        c_id = n.get("temp_id")
                        break
                if isinstance(c_id, str):
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
                        key = (c_id, p_id, "INVOLVES")
                        if key not in existing_edges:
                            props = {"role": role}
                            (self.state.edges_accumulated or []).append({"from": c_id, "to": p_id, "label": "INVOLVES", "properties": props})
                            existing_edges.add(key)

                    # Also create Proceeding -> Party INVOLVES edges (no properties defined in schema)
                    proceeding_ids = [n.get("temp_id") for n in (self.state.nodes_accumulated or []) if isinstance(n, dict) and n.get("label") == "Proceeding" and isinstance(n.get("temp_id"), str)]
                    party_ids = {pid for pid in created_ids_by_index.values() if isinstance(pid, str)}
                    for pr_id in proceeding_ids:
                        for p_id in party_ids:
                            key = (pr_id, p_id, "INVOLVES")
                            if key not in existing_edges:
                                (self.state.edges_accumulated or []).append({"from": pr_id, "to": p_id, "label": "INVOLVES", "properties": {}})
                                existing_edges.add(key)
            except Exception:
                pass

            logger.info("Phase 8: party extraction/dedup and relationships completed")
            return {"status": "phase8_done"}
        except Exception as e:
            logger.warning(f"Phase 8: party extraction failed: {e}")
            return {"status": "phase8_skipped"}

    @listen(phase8_assign_parties)
    def phase9_validate_and_repair(self, _: Dict[str, Any]) -> Dict[str, Any]:
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


