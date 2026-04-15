import os
import glob
import time
from videorag import VideoRAG

def ingest_all():
    # Initialize VideoRAG with the same working directory as your project
    vrag = VideoRAG(working_dir="./reproduce/ablation/test_cache")
    
    video_extensions = ['*.mp4', '*.mkv', '*.webm', '*.avi']
    processed_videos = set()
    
    print("Ingestion daemon started. Watching for completed downloads in longervideos/...")
    
    try:
        while True:
            found_any = False
            base_path = "longervideos"
            
            # Walk through the directory to find completed videos
            video_paths = []
            for course_dir in os.listdir(base_path):
                course_path = os.path.join(base_path, course_dir)
                if not os.path.isdir(course_path):
                    continue
                    
                video_dir = os.path.join(course_path, "videos")
                if not os.path.exists(video_dir):
                    continue
                    
                for ext in video_extensions:
                    for f in glob.glob(os.path.join(video_dir, ext)):
                        # Only pick up files that are NOT .part and have not been processed in this session
                        if f not in processed_videos:
                            video_paths.append(f)
            
            if video_paths:
                print(f"Found {len(video_paths)} new videos. Starting ingestion...")
                for path in video_paths:
                    print(f"Ingesting: {path}")
                    try:
                        vrag.insert_video([path])
                        processed_videos.add(path)
                    except Exception as e:
                        print(f"Error ingesting {path}: {e}")
                found_any = True
            
            if not found_any:
                # Check if the download script is still running
                # (You might want to implement a check here, or just let it loop)
                time.sleep(10) 
                
    except KeyboardInterrupt:
        print("Ingestion daemon stopped.")

if __name__ == "__main__":
    ingest_all()
