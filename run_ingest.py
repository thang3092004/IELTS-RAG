import os
import json
import logging
import warnings
import multiprocessing
import sys
from dotenv import load_dotenv

# Nạp các biến môi trường từ file .env
load_dotenv()

warnings.filterwarnings("ignore")
logging.getLogger("httpx").setLevel(logging.WARNING)

from videorag._llm import *
from videorag.videorag import VideoRAG

# Tối ưu cấu hình LLM cho ingestion
longervideos_llm_config = LLMConfig(
    embedding_func_raw = openai_embedding,
    embedding_model_name = "text-embedding-3-small",
    embedding_dim = 1536,
    embedding_max_token_size  = 8192,
    embedding_batch_num = 32,
    embedding_func_max_async = 16,
    query_better_than_threshold = 0.2,

    best_model_func_raw = gpt_4o_mini_complete,
    best_model_name = "gpt-4o-mini", 
    best_model_max_token_size = 32768,
    best_model_max_async = 16,
        
    cheap_model_func_raw = gpt_4o_mini_complete,
    cheap_model_name = "gpt-4o-mini",
    cheap_model_max_token_size = 32768,
    cheap_model_max_async = 16
)

def ingest_collection(sub_category):
    print(f"\n{'='*50}\nBẮT ĐẦU INGESTION CHO: {sub_category}\n{'='*50}")
    video_base_path = f'./longervideos/{sub_category}/videos/'
    
    if not os.path.exists(video_base_path):
        print(f"LỖI: Không tìm thấy thư mục {video_base_path}. Bạn đã chạy prepare_data.py và tải video về chưa?")
        return
        
    video_files = sorted([f for f in os.listdir(video_base_path) if f.endswith(('.mp4', '.avi', '.mkv', '.webm'))])
    
    if not video_files:
        print(f"CẢNH BÁO: Không có file video nào trong {video_base_path}.")
        return
        
    video_paths = [os.path.join(video_base_path, f) for f in video_files]
    print(f"Tìm thấy {len(video_paths)} videos. Đang khởi tạo tiến trình Ingest...")
    
    # Khởi tạo VideoRAG với storage riêng cho từng collection
    videorag = VideoRAG(
        llm=longervideos_llm_config, 
        working_dir=f"./longervideos/videorag-workdir/{sub_category}"
    )    
    
    try:
        videorag.insert_video(video_path_list=video_paths)
        print(f"\n[THÀNH CÔNG] Đã hoàn tất Ingestion cho: {sub_category}\n")
    except Exception as e:
        print(f"\n[LỖI NGHIÊM TRỌNG] Ingestion thất bại cho {sub_category} do lỗi hệ thống (Fail-fast trigger).")
        print(f"Chi tiết lỗi: {str(e)}")
        print("Dừng toàn bộ script để bảo vệ tính toàn vẹn dữ liệu.")
        raise e

if __name__ == '__main__':
    multiprocessing.set_start_method('spawn', force=True)
    
    # Các collection tiêu biểu đại diện cho 3 categories (Documentary, Lecture, Entertainment) với kích thước ~3 videos
    target_collections = [
        "19-jeff-bezos",                  # Documentary (3 videos)
        "6-daubechies-wavelet-lecture",   # Lecture (4 videos)
        "11-primetime-emmy-awards"        # Entertainment (3 videos)
    ]
    
    for collection in target_collections:
        ingest_collection(collection)
        
    print(f"\n{'='*50}\nTẤT CẢ CÁC COLLECTIONS ĐÃ INGEST THÀNH CÔNG!\n{'='*50}")
