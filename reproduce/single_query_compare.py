import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path

from videorag.videorag import VideoRAG
from videorag.base import QueryParam


def _load_question(dataset_path: Path, dataset_id: int, question_id: int) -> tuple[str, str]:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    entry = data.get(str(dataset_id))
    if not entry:
        raise ValueError(f"dataset_id {dataset_id} not found in {dataset_path}")
    payload = entry[0]
    for item in payload.get("questions", []):
        if item.get("id") == question_id:
            return payload.get("description", ""), item.get("question", "")
    raise ValueError(f"question_id {question_id} not found for dataset {dataset_id}")


def _read_baseline(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _normalize_response(resp) -> str:
    if isinstance(resp, dict):
        for key in ("answer", "response", "content", "text"):
            if key in resp:
                return str(resp[key]).strip()
    return str(resp).strip()


def main():
    parser = argparse.ArgumentParser(description="Run a single query and compare with a baseline answer")
    parser.add_argument("--dataset-id", type=int, default=17, help="Dataset index in longervideos/dataset.json")
    parser.add_argument("--question-id", type=int, default=1, help="Question id inside the dataset entry")
    parser.add_argument("--baseline", type=Path, required=True, help="Path to baseline answer markdown/text")
    parser.add_argument("--working-dir", type=Path, required=True, help="Existing working_dir containing storages")
    parser.add_argument("--dataset-path", type=Path, default=Path("longervideos/dataset.json"), help="Path to dataset.json")
    parser.add_argument("--mode", type=str, default="ielts_rag", help="Query mode (ielts_rag | videorag | videorag_multiple_choice)")
    parser.add_argument("--top-k", type=int, default=20, help="top_k for retrieval")
    args = parser.parse_args()

    if not args.working_dir.exists():
        parser.error(f"working_dir {args.working_dir} not found. Point to an existing cache with inserted videos.")

    description, question = _load_question(args.dataset_path, args.dataset_id, args.question_id)
    baseline_answer = _read_baseline(args.baseline)

    vr = VideoRAG(working_dir=str(args.working_dir), always_create_working_dir=False)
    param = QueryParam()
    param.mode = args.mode
    param.top_k = args.top_k

    response = vr.query(question, param=param)
    model_answer = _normalize_response(response)
    similarity = SequenceMatcher(None, baseline_answer, model_answer).ratio()

    print("=== Query Info ===")
    print(f"Dataset: {args.dataset_id} ({description})")
    print(f"Question id: {args.question_id}")
    print(f"Question: {question}\n")

    print("=== Baseline (old model) ===")
    print(baseline_answer + "\n")

    print("=== Current model ===")
    print(model_answer + "\n")

    print("=== Similarity (SequenceMatcher ratio) ===")
    print(f"{similarity:.3f}")


if __name__ == "__main__":
    main()
