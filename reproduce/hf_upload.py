from huggingface_hub import HfApi, login
import os

# ==========================================
# CẤU HÌNH CỦA BẠN
# ==========================================
TOKEN = os.getenv("HF_TOKEN") # Dán token của bạn vào biến môi trường HF_TOKEN
REPO_ID = "thang3092004/ebr-rag-6-11-19-ingested"  # Thay bằng username/tên-repo bạn muốn
# ==========================================

try:
    print(f"--- Đang đăng nhập Hugging Face ---")
    login(token=TOKEN)
    
    api = HfApi()
    
    print(f"--- Đang tạo Dataset Repo: {REPO_ID} ---")
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)
    
    print(f"--- Đang tải thư mục videorag-workdir lên ---")
    # Đường dẫn thư mục ingest là ./longervideos/videorag-workdir
    api.upload_folder(
        folder_path="longervideos/videorag-workdir",
        repo_id=REPO_ID,
        repo_type="dataset",
    )
    print("\n✅ THÀNH CÔNG! Dữ liệu của bạn đã được tải lên Hugging Face.")
    
except Exception as e:
    print(f"\n❌ LỖI: {str(e)}")
