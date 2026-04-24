import os, time, sys
from openai import OpenAI

client = OpenAI()
print("--- Đang giám sát TOÀN BỘ phiên chấm điểm EBR-RAG... ---")

while True:
    batches = client.batches.list(limit=20)
    targets = [b for b in batches if 'ielts' in (b.metadata or {}).get('description', '')]
    targets = sorted(targets, key=lambda x: x.created_at, reverse=True)[:3] # Lấy 3 thằng mới nhất
    
    if not targets:
        print("\rKhông tìm thấy phiên nào. Đang quét...", end="")
        time.sleep(10)
        continue

    output = []
    all_done = True
    for b_summary in targets:
        b = client.batches.retrieve(b_summary.id)
        status = b.status
        progress = f"{b.request_counts.completed}/{b.request_counts.total}"
        output.append(f"[{b.id[:10]}...: {status:12} | Tiến độ: {progress}]")
        if status not in ["completed", "failed", "cancelled"]:
            all_done = False
            
    sys.stdout.write("\r" + " | ".join(output) + f" | Cập nhật: {time.strftime('%H:%M:%S')}")
    sys.stdout.flush()

    if all_done and len(targets) >= 3:
        print("\n\n🎉 TẤT CẢ ĐÃ XONG! Mày có thể tải kết quả được rồi.")
        break
        
    time.sleep(30)
