import asyncio
import os
import json
import argparse
from pathlib import Path
from tqdm import tqdm
from videorag import VideoRAG, QueryParam
from videorag._utils import logger

async def run_baseline(vrag, query, query_id, output_dir):
    """Run a single question under Naive RAG baseline."""
    file_path = output_dir / "answers-naiverag" / f"answer_{query_id}.md"
    
    if file_path.exists():
        return
        
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Naive RAG uses mode="videorag"
    param = QueryParam(mode="videorag")
    param.wo_reference = True # Match evaluation standard
    
    try:
        response = await vrag.aquery(query, param=param)
        # For Naive RAG, response might be a string or a dict depending on implementation
        if isinstance(response, dict):
            answer = response.get("answer", "")
            rationale = response.get("rationale", "")
        else:
            answer = response
            rationale = "Generated via standard VideoRAG (Naive RAG) pipeline."
            
        content = f"# Answer\n\n{answer}\n\n# Rationale\n\n{rationale}"
        file_path.write_text(content, encoding="utf-8")
        
    except Exception as e:
        logger.error(f"Error in Baseline for Q{query_id}: {str(e)}")

async def main():
    parser = argparse.ArgumentParser(description="Naive RAG Baseline Generator")
    parser.add_argument("--collections", type=str, nargs="+", default=["6", "11", "19"], help="Collection IDs to run")
    args = parser.parse_args()

    dataset_path = Path("longervideos/dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    total_tasks = 0
    for col_id in args.collections:
        if col_id in dataset:
            total_tasks += len(dataset[col_id][0]["questions"])

    pbar = tqdm(total=total_tasks, desc="Naive Baseline Progress")

    for col_id in args.collections:
        if col_id not in dataset: continue
            
        col_meta = dataset[col_id][0]
        sub_category = f"{col_id}-{col_meta['description']}"
        work_dir = Path(f"./longervideos/videorag-workdir/{sub_category}")
        
        if not work_dir.exists():
            pbar.update(len(col_meta["questions"]))
            continue
            
        vrag = VideoRAG(working_dir=str(work_dir))
        output_root = Path("reproduce/all_answers") / sub_category
        
        for q in col_meta["questions"]:
            await run_baseline(vrag, q["question"], q["id"], output_root)
            pbar.update(1)

    pbar.close()
    print("\n✅ Naive RAG Baseline generation complete!")

if __name__ == "__main__":
    asyncio.run(main())
