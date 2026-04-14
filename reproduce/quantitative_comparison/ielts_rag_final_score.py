import json, numpy as np

def calculate():
    try:
        with open('batch_requests/ielts_rag_comparison/realtime_evaluation_results.json', 'r') as f:
            data = json.load(f)
    except:
        print("Không thấy file kết quả!")
        return

    metrics = ['Comprehensiveness', 'Empowerment', 'Trustworthiness', 'Depth', 'Density', 'Overall Score']
    scores = {m: [] for m in metrics}

    for item in data:
        if 'response' in item:
            content = json.loads(item['response']['body']['choices'][0]['message']['content'])
            for m in metrics:
                scores[m].append(int(content[m]['Score']))

    print("\n" + "="*50)
    print(f"{'TIÊU CHÍ':<20} | {'ĐIỂM TRUNG BÌNH (1-5)':<20}")
    print("-" * 50)
    for m in metrics:
        avg = np.mean(scores[m])
        print(f"{m:<20} | {avg:.2f} / 5.0")
    print("="*50)
    print(f"Tổng cộng chấm xong: {len(data)} yêu cầu.")

if __name__ == '__main__':
    calculate()
