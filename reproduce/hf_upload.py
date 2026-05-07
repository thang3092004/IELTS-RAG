from huggingface_hub import HfApi, login
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv


def main():
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")

    parser = argparse.ArgumentParser(description="Upload selected ablation results to Hugging Face")
    parser.add_argument(
        "--collections",
        nargs="+",
        default=["6", "11", "19"],
        help="Collection IDs to upload",
    )
    parser.add_argument(
        "--repo-id",
        default="thang3092004/ebr-rag-ablation-6-11-19",
        help="Hugging Face dataset repo id",
    )
    parser.add_argument(
        "--source-root",
        default="reproduce/all_answers",
        help="Root folder containing per-collection ablation outputs",
    )
    args = parser.parse_args()

    token = os.getenv("HF_TOKEN")
    if not token:
        raise EnvironmentError(
            f"Please set HF_TOKEN before running. Tried loading {repo_root / '.env'}"
        )

    login(token=token)
    api = HfApi()
    api.create_repo(repo_id=args.repo_id, repo_type="dataset", exist_ok=True)

    source_root = (repo_root / args.source_root).resolve()
    if not source_root.exists():
        raise FileNotFoundError(f"Source root not found: {source_root}")

    for col_id in args.collections:
        matches = sorted(source_root.glob(f"{col_id}-*"))
        if not matches:
            print(f"[SKIP] No folder found for collection {col_id} under {source_root}")
            continue

        for folder in matches:
            print(f"[UPLOAD] {folder}")
            api.upload_folder(
                folder_path=str(folder),
                repo_id=args.repo_id,
                repo_type="dataset",
                path_in_repo=folder.name,
            )

    print(f"\n✅ Uploaded ablation results for collections: {', '.join(args.collections)}")
    print(f"Repo: {args.repo_id}")


if __name__ == "__main__":
    main()
