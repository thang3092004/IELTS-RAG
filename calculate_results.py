import json
import numpy as np
import os

def calculate_scores(file_path):
    if not os.path.exists(file_path):
        print(f"Lỗi: Không tìm thấy file {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        judgments = json.load(f)

    metrics = ['Comprehensiveness', 'Empowerment', 'Trustworthiness', 'Depth', 'Density', 'Overall Score']
    # Tự động nhận diện các model có trong file (ieltsrag, videorag, etc.)
    models = set()
    for key in judgments.keys():
        model_name = key.split("++")[-1].replace("answers-", "")
        models.add(model_name)

    summaries = {m: {model: [] for model in models} for m in metrics}

    for task_id, res in judgments.items():
        model_key = task_id.split("++")[-1].replace("answers-", "")
        for m in metrics:
            val = res.get(m, {}).get("Score")
            if val is not None:
                summaries[m][model_key].append(float(val))

    print("\n" + "="*70)
    print(f"KẾT QUẢ ĐÁNH GIÁ (Tổng cộng {len(judgments)} cặp)")
    print("="*70)
    
    # In tiêu đề cột
    header = "Metric".ljust(22)
    for model in sorted(models):
        header += f" | {model.upper().center(15)}"
    print(header)
    print("-" * len(header))

    # In điểm từng tiêu chí
    for m in metrics:
        line = f"{m.ljust(22)}"
        for model in sorted(models):
            scores = summaries[m][model]
            avg = np.mean(scores) if scores else 0
            line += f" | {avg:8.3f} (n={len(scores)})"
        print(line)
    
    print("-" * len(header))

if __name__ == "__main__":
    calculate_scores("custom_eval_results_17/judge_output.json")
