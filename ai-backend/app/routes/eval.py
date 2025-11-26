from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import time
from enum import Enum
from typing import Dict, Any, Optional, Literal
from app.flow_query import QueryFlow
from app.lib.security import get_api_key
from app.lib.logging_config import setup_logger

logger = setup_logger("eval-route")

router = APIRouter(prefix="/eval", tags=["Evaluation"])

class InterpretRequest(BaseModel):
    query: str

@router.post("/interpret")
async def interpret_query_step(req: InterpretRequest, _=Depends(get_api_key)):
    """
    Isolates the 'Interpret Query' step of the QueryFlow.
    Returns the generated Route Plan and execution time.
    """
    try:
        flow = QueryFlow()
        flow.state.query = req.query
        
        # Run just the interpret_query step manually.
        # Since interpret_query is an @start() method that ultimately calls an async planner,
        # we await it here and rely on the flow's internal metrics for detailed timings.
        start_t = time.time()
        # We now start from reason_query -> interpret_query
        await flow.reason_query()
        result_signal = await flow.interpret_query()
        duration = time.time() - start_t

        timings = {}
        try:
            # Use any timings captured inside the flow, but fall back gracefully.
            timings = dict(flow.state.timings or {})
        except Exception:
            timings = {}
        
        # Always include a top-level duration for backwards compatibility.
        timings.setdefault("endpoint_total_seconds", duration)
        
        return {
            "success": True,
            "plan": flow.state.route_plan.model_dump() if flow.state.route_plan else None,
            "duration_seconds": duration,
            "timings": timings,
            "signal": result_signal
        }

    except Exception as e:
        logger.error(f"Interpret query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class StepName(str, Enum):
    interpret = "interpret"
    reason = "reason"
    searches = "searches"
    traversal = "traversal"
    answer = "answer"


class StepMode(str, Enum):
    full_chain = "full_chain"
    isolated = "isolated"


class StepEvalRequest(BaseModel):
    query: str
    step: StepName
    mode: StepMode = StepMode.full_chain
    # Arbitrary seed payload; shape depends on step.
    seed: Optional[Dict[str, Any]] = None


@router.post("/step")
async def eval_query_step(req: StepEvalRequest, _=Depends(get_api_key)):
    """
    Flexible evaluator for individual QueryFlow steps.

    - `step`: which step to target ("interpret", "searches", "traversal", "answer")
    - `mode`:
        - "full_chain": run all preceding steps to generate realistic inputs
        - "isolated": run only the target step using provided or auto-generated seed inputs
    - `seed`: optional JSON payload used when mode = "isolated"
    """
    flow = QueryFlow()
    flow.state.query = req.query
    flow.state.timings = {}

    step = req.step.value
    mode = req.mode.value

    start_t = time.time()
    input_used: Dict[str, Any] = {}
    output: Dict[str, Any] = {}

    try:
        # Helper to snapshot common pieces of state for the response.
        def snapshot_state_for_step(target_step: str) -> Dict[str, Any]:
            import copy
            
            if target_step == "reason":
                return {
                    "reasoning": flow.state.reasoning
                }
            if target_step == "interpret":
                return {
                    "reasoning": flow.state.reasoning,
                    "route_plan": flow.state.route_plan.model_dump()
                    if flow.state.route_plan
                    else None
                }
            if target_step in ("searches", "traversal", "answer"):
                # CRITICAL: We must deepcopy mutable state like step_results so that 
                # historical snapshots in chain_history don't get updated by subsequent steps.
                current_step_results = copy.deepcopy(flow.state.step_results or {})
                
                # Build a reverse mapping: node_id -> list of step indices that found it
                node_to_steps: Dict[str, list] = {}
                for step_idx, node_ids in current_step_results.items():
                    for node_id in node_ids:
                        if node_id not in node_to_steps:
                            node_to_steps[node_id] = []
                        if step_idx not in node_to_steps[node_id]:
                            node_to_steps[node_id].append(step_idx)
                
                # Enhance found_nodes with step source information
                # found_nodes is already being copied by value via model_dump loop below
                found_nodes_dict = {}
                for k, v in (flow.state.found_nodes or {}).items():
                    node_dict = v.model_dump()
                    # Add which steps found this node
                    node_dict["found_by_steps"] = sorted(node_to_steps.get(k, []))
                    found_nodes_dict[k] = node_dict
                
                # Add summary statistics
                summary = {
                    "total_nodes": len(found_nodes_dict),
                    "nodes_by_label": {},
                    "nodes_by_step": {},
                    "step_results_summary": {}
                }
                
                # Count nodes by label
                for node_id, node_info in (flow.state.found_nodes or {}).items():
                    label = node_info.label
                    summary["nodes_by_label"][label] = summary["nodes_by_label"].get(label, 0) + 1
                
                # Count unique nodes per step
                for step_idx, node_ids in current_step_results.items():
                    unique_count = len(set(node_ids))
                    summary["nodes_by_step"][f"step_{step_idx}"] = {
                        "unique_nodes": unique_count,
                        "total_results": len(node_ids),
                        "duplicates": len(node_ids) - unique_count
                    }
                
                # Summarize step results with more detail
                for step_idx, node_ids in current_step_results.items():
                    step_info = flow.state.route_plan.steps[step_idx] if flow.state.route_plan and step_idx < len(flow.state.route_plan.steps) else None
                    unique_count = len(set(node_ids))
                    summary["step_results_summary"][f"step_{step_idx}"] = {
                        "unique_nodes": unique_count,
                        "total_results": len(node_ids),
                        "node_type": step_info.node_type if step_info else "Unknown",
                        "search_type": step_info.search_type if step_info else "Unknown"
                    }
                
                return {
                    "route_plan": flow.state.route_plan.model_dump()
                    if flow.state.route_plan
                    else None,
                    "summary": summary,
                    "step_results": current_step_results,
                    "found_nodes": found_nodes_dict,
                }
            return {}

        # --- FULL CHAIN EXECUTION ---
        if mode == "full_chain":
            # To capture outputs per step, we accumulate them in a list
            chain_history = []

            # Step 1: Reason
            signal_reason = await flow.reason_query()
            chain_history.append({
                "step": "reason",
                "input": {"query": req.query},
                "output": {
                    "signal": signal_reason,
                    "state": snapshot_state_for_step("reason")
                }
            })
            
            if step == "reason":
                # If only asked for reason, we are done
                output = chain_history[-1]["output"]
                input_used = chain_history[-1]["input"]
            else:
                # Step 2: Interpret
                signal_interpret = await flow.interpret_query()
                chain_history.append({
                    "step": "interpret",
                    "input": {"query": req.query, "reasoning": flow.state.reasoning},
                    "output": {
                        "signal": signal_interpret,
                        "reasoning": flow.state.reasoning,
                        "route_plan": flow.state.route_plan.model_dump() if flow.state.route_plan else None,
                    }
                })

                if step == "interpret":
                    output = chain_history[-1]["output"]
                    input_used = chain_history[-1]["input"]
                else:
                    # Step 3: Searches
                    signal_searches = await flow.execute_searches()
                    chain_history.append({
                        "step": "searches",
                        "input": snapshot_state_for_step("interpret"), # Uses plan from prev step
                        "output": {
                            "signal": signal_searches,
                            "state": snapshot_state_for_step("searches"),
                        }
                    })

                    if step == "searches":
                        output = chain_history[-1]["output"]
                        input_used = chain_history[-1]["input"]
                    else:
                        # Step 4: Traversal
                        signal_traversal = await flow.deterministic_traversal()
                        chain_history.append({
                            "step": "traversal",
                            "input": snapshot_state_for_step("searches"), # Uses nodes from prev step
                            "output": {
                                "signal": signal_traversal,
                                "state": snapshot_state_for_step("traversal"),
                            }
                        })

                        if step == "traversal":
                            output = chain_history[-1]["output"]
                            input_used = chain_history[-1]["input"]
                        else:
                            # Step 5: Answer
                            response = await flow.gather_enriched_data()
                            chain_history.append({
                                "step": "answer",
                                "input": snapshot_state_for_step("traversal"),
                                "output": {
                                    "signal": "answer_ready",
                                    "response": response,
                                    "state": snapshot_state_for_step("answer"),
                                }
                            })
                            
                            output = chain_history[-1]["output"]
                            input_used = chain_history[-1]["input"]

            # Include full history in the response for the frontend to render
            # We return it at the top level to avoid recursion issues with jsonable_encoder
            # because chain_history elements contain output, and output might be a reference
            # to one of those elements.
            
            # Create a safe copy of the output for the top-level return
            import copy
            safe_output = copy.deepcopy(output)
            
            final_chain_history = chain_history

        # --- ISOLATED EXECUTION ---
        else:
            safe_output = output
            final_chain_history = None
            seed = req.seed or {}

            # Step 1 is already isolated by design.
            if step == "reason":
                signal_reason = await flow.reason_query()
                output = {
                     "signal": signal_reason,
                     "state": snapshot_state_for_step("reason")
                }
                input_used = {"query": req.query}

            elif step == "interpret":
                # Can seed reasoning
                flow.state.reasoning = seed.get("reasoning", "Pre-seeded reasoning.")
                signal_interpret = await flow.interpret_query()
                output = {
                    "signal": signal_interpret,
                    "route_plan": flow.state.route_plan.model_dump()
                    if flow.state.route_plan
                    else None,
                }
                input_used = {"query": req.query, "reasoning": flow.state.reasoning}

            elif step == "searches":
                # Need a RoutePlan. If not provided, auto-derive by running interpret.
                route_plan_seed = seed.get("route_plan")
                if not route_plan_seed:
                    await flow.reason_query()
                    await flow.interpret_query()
                    route_plan_seed = (
                        flow.state.route_plan.model_dump()
                        if flow.state.route_plan
                        else None
                    )
                if route_plan_seed:
                    from app.flow_query.query_flow import RoutePlan

                    flow.state.route_plan = RoutePlan(**route_plan_seed)

                input_used = {"route_plan": route_plan_seed}
                signal_searches = await flow.execute_searches()
                output = {
                    "signal": signal_searches,
                    "state": snapshot_state_for_step("searches"),
                }

            elif step == "traversal":
                # Need found_nodes. If not provided, run interpret + searches.
                found_nodes_seed = seed.get("found_nodes")
                if not found_nodes_seed:
                    await flow.reason_query()
                    await flow.interpret_query()
                    await flow.execute_searches()
                    found_nodes_seed = {
                        k: v.model_dump() for k, v in (flow.state.found_nodes or {}).items()
                    }

                # Rehydrate NodeInfo objects from seed.
                from app.flow_query.query_flow import NodeInfo

                flow.state.found_nodes = {
                    k: NodeInfo(**v) for k, v in (found_nodes_seed or {}).items()
                }

                input_used = {"found_nodes": found_nodes_seed}
                signal_traversal = await flow.deterministic_traversal()
                output = {
                    "signal": signal_traversal,
                    "state": snapshot_state_for_step("traversal"),
                }

            elif step == "answer":
                # Need found_nodes. If not provided, run interpret + searches + traversal.
                found_nodes_seed = seed.get("found_nodes")
                if not found_nodes_seed:
                    await flow.reason_query()
                    await flow.interpret_query()
                    await flow.execute_searches()
                    await flow.deterministic_traversal()
                    found_nodes_seed = {
                        k: v.model_dump() for k, v in (flow.state.found_nodes or {}).items()
                    }

                from app.flow_query.query_flow import NodeInfo

                flow.state.found_nodes = {
                    k: NodeInfo(**v) for k, v in (found_nodes_seed or {}).items()
                }

                input_used = {"found_nodes": found_nodes_seed}
                response = await flow.construct_answer()
                output = {
                    "signal": "answer_ready",
                    "response": response,
                    "state": snapshot_state_for_step("answer"),
                }

        duration = time.time() - start_t

        timings = {}
        try:
            timings = dict(flow.state.timings or {})
        except Exception:
            timings = {}

        timings.setdefault("endpoint_total_seconds", duration)

        return {
            "success": True,
            "step": step,
            "mode": mode,
            "duration_seconds": duration,
            "timings": timings,
            "input_used": input_used,
            "output": safe_output,
            "chain_history": final_chain_history
        }

    except Exception as e:
        logger.error(f"Step evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

