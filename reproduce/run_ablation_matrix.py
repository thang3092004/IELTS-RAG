import asyncio
import os
import sys
import json
import traceback
import argparse
from pathlib import Path

# Add project root to sys.path so 'videorag' can be found when running from 'reproduce/'
root_path = str(Path(__file__).resolve().parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

from tqdm import tqdm
from videorag.videorag import VideoRAG
from videorag.base import QueryParam
from videorag._utils import logger

# ==============================================================================
# ABLATION MATRIX DEFINITION
# ==============================================================================
ABLATION_MATRIX = {
    # 1. Test TM Graph
    "full_framework": {"use_tm_graph": True},
    "baseline_with_debate": {"use_tm_graph": False}, 
    
    # 2. Test Debate (all using TM Graph)
    "no_debate": {"use_tm_graph": True, "max_rounds": 0},
    "critique_with_evidence": {"use_tm_graph": True, "debate_critique_see_evidence": True},
    "defender_no_tools": {"use_tm_graph": True, "debate_defender_disable_tools": True},
}


async def run_scenario(vrag, query, scenario_name, scenario_params, query_id, output_dir):
    """Run a single question under a specific ablation scenario.

    Raises on ANY error — caller is responsible for stopping the run.
    Never writes empty or partial results to disk.
    """
    file_path = output_dir / scenario_name / f"answer_{query_id}.md"

    # Resume Logic: Skip if already exists
    if file_path.exists():
        return

    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Base params — scenario_params can override any of these
    base_params = {
        "mode": "EBR_RAG",
        "ebr_top_k": 8,
        "max_rounds": 3,
        "return_detailed": True,
    }
    # scenario_params override base (e.g. no_debate sets max_rounds=0)
    merged = {**base_params, **scenario_params}
    
    # Filter out internal control flags that are NOT part of QueryParam dataclass
    query_param_keys = ["mode", "ebr_top_k", "max_rounds", "return_detailed", 
                        "debate_critique_see_evidence", "debate_defender_disable_tools",
                        "debate_single_hypothesis", "wo_reference"]
    qp_dict = {k: v for k, v in merged.items() if k in query_param_keys}
    
    param = QueryParam(**qp_dict)

    # --- Execute pipeline ---
    response = await vrag.aquery(query, param=param)

    # --- Validate response type ---
    if not isinstance(response, dict):
        raise TypeError(
            f"[{scenario_name}] Q{query_id}: Expected dict from aquery, "
            f"got {type(response).__name__!r}. Value: {str(response)[:200]}"
        )

    answer = response.get("answer", "")

    # --- Guard: never write empty answers to disk ---
    if not answer or not answer.strip():
        raise ValueError(
            f"[{scenario_name}] Q{query_id}: answer is empty after pipeline completed. "
            f"This indicates a key mismatch or silent LLM failure. Aborting."
        )

    # --- Save output (plain answer only, matching VideoRAG baseline format) ---
    file_path.write_text(answer, encoding="utf-8")
    logger.info(f"[{scenario_name}] Q{query_id}: saved ({len(answer)} chars)")


async def main():
    parser = argparse.ArgumentParser(description="EBR-RAG Ablation Study Runner")
    parser.add_argument("--collections", type=str, nargs="+", default=["6", "11", "19"],
                        help="Collection IDs to run")
    parser.add_argument("--scenarios", type=str, nargs="+", default=None,
                        help="Scenarios to run (default all)")
    args = parser.parse_args()

    # Load Dataset
    dataset_path = Path(root_path) / "longervideos/dataset.json"
    if not dataset_path.exists():
        print(f"Error: Dataset not found at {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    scenarios_to_run = list(args.scenarios) if args.scenarios else list(ABLATION_MATRIX.keys())

    # Validate requested scenarios exist
    for s in scenarios_to_run:
        if s not in ABLATION_MATRIX:
            print(f"Error: Unknown scenario {s!r}. Valid: {list(ABLATION_MATRIX.keys())}")
            return

    # Calculate total tasks for progress bar
    total_tasks = 0
    for col_id in args.collections:
        if col_id in dataset:
            total_tasks += len(dataset[col_id][0]["questions"]) * len(scenarios_to_run)

    pbar = tqdm(total=total_tasks, desc="Ablation Progress")

    try:
        for col_id in args.collections:
            if col_id not in dataset:
                print(f"\nWarning: Collection {col_id} not in dataset.")
                continue

            col_meta = dataset[col_id][0]
            col_desc = col_meta["description"]
            sub_category = f"{col_id}-{col_desc}"
            questions = col_meta["questions"]

            # Initialize VideoRAG for this specific collection
            work_dir = Path(root_path) / "longervideos/videorag-workdir" / sub_category
            if not work_dir.exists():
                print(f"\nWarning: Workdir not found at {work_dir}. Skipping collection.")
                pbar.update(len(questions) * len(scenarios_to_run))
                continue

            # vrag_tm = VideoRAG(working_dir=str(work_dir), use_tm_graph=True)
            # vrag_base = VideoRAG(working_dir=str(work_dir), use_tm_graph=False)
            vrag = None
            current_tm_mode = None

            output_root = Path(root_path) / "reproduce/all_answers" / sub_category

            for scenario_name in scenarios_to_run:
                params = ABLATION_MATRIX[scenario_name]
                use_tm = params.get("use_tm_graph", False)

                # Re-initialize VideoRAG if TM mode changes
                if vrag is None or current_tm_mode != use_tm:
                    logger.info(f"Initializing VideoRAG (use_tm_graph={use_tm}) for {sub_category}")
                    vrag = VideoRAG(working_dir=str(work_dir), use_tm_graph=use_tm)
                    # For debate re-captioning, we need the caption model
                    vrag.load_caption_model()
                    current_tm_mode = use_tm

                for q in questions:
                    q_id = q["id"]
                    q_text = q["question"]

                    try:
                        await run_scenario(vrag, q_text, scenario_name, params, q_id, output_root)
                    except Exception as e:
                        pbar.close()
                        print(f"\n{'='*70}")
                        print(f"FATAL ERROR — Ablation halted immediately.")
                        print(f"  Collection : {sub_category}")
                        print(f"  Scenario   : {scenario_name}")
                        print(f"  Question ID: {q_id}")
                        print(f"  Error      : {type(e).__name__}: {e}")
                        print(f"{'='*70}")
                        print("\nFull traceback:")
                        traceback.print_exc()
                        print(f"\nFix the issue above, then resume by re-running the script.")
                        print(f"(Already-saved files will be skipped automatically.)")
                        sys.exit(1)  # Hard stop — no silent continuation

                    pbar.update(1)

    finally:
        pbar.close()

    print("\n✅ Ablation study batch complete!")


if __name__ == "__main__":
    asyncio.run(main())
