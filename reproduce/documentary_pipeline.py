import os
import json
import subprocess
import time
import threading
from videorag import VideoRAG

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
WORKING_DIR = "./longervideos/videorag-workdir"
DOC_IDS = ["0", "1", "14", "18", "19"]
DATASET_JSON = "longervideos/dataset.json"
PROGRESS_FILE = "reproduce/ingest_progress.json"

# State tracking
downloaded_files = set()
processed_files = set()
stop_flag = False

def load_progress():
    """Load previously processed videos from disk."""
    global processed_files
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                data = json.load(f)
                processed_files = set(data.get("ingested_paths", []))
                print(f"[SYSTEM] Resuming from progress: {len(processed_files)} videos already processed.")
        except Exception as e:
            print(f"[SYSTEM] Error loading progress file: {e}. Starting fresh.")

def save_progress(path):
    """Save a newly processed video path to disk."""
    global processed_files
    processed_files.add(path)
    data = {"ingested_paths": list(processed_files), "last_update": time.ctime()}
    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[SYSTEM] Warning: Could not save progress to file: {e}")

def get_doc_collections():
    """Extract paths for the 5 documentary collections."""
    with open(DATASET_JSON, 'r') as f:
        data = json.load(f)
    
    docs = []
    for cid in DOC_IDS:
        if cid not in data: continue
        coll = data[cid][0]
        name = f"{cid}-{coll['description']}"
        docs.append(name)
    return docs

def download_worker(collections):
    """Thread to download videos iteratively for documentary folders."""
    global stop_flag
    print(f"\n[DOWNLOADER] Starting download thread for: {', '.join(collections)}")
    
    for coll in collections:
        if stop_flag: break
        video_dir = os.path.join("longervideos", coll, "videos")
        videos_txt = os.path.join("longervideos", coll, "videos.txt")
        
        print(f"[DOWNLOADER] Downloading collection: {coll}")
        # Run yt-dlp. yt-dlp handles skipping existing files automatically.
        cmd = [
            "yt-dlp",
            "-o", "%(id)s.%(ext)s",
            "-S", "res:480",
            "-a", videos_txt,
            "-P", video_dir,
            "--no-mtime" # Ensure we don't have issues with mod times
        ]
        
        try:
            # We run it synchronously per collection inside the thread
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[DOWNLOADER] Finished check/download for collection: {coll}")
        except Exception as e:
            print(f"[DOWNLOADER] Error in {coll}: {e}")

    print("[DOWNLOADER] All planned downloads triggered/finished.")

def ingest_worker():
    """Main thread/loop to watch for finished downloads and ingest them."""
    global stop_flag, processed_files
    
    print("[INGESTOR] Ingest worker starting...")
    collections = get_doc_collections()
    vrag_instances = {}

    while not stop_flag:
        new_targets = []
        
        # Scan folders for finished videos
        for coll in collections:
            v_dir = os.path.join("longervideos", coll, "videos")
            if not os.path.exists(v_dir): continue
            
            for f in os.listdir(v_dir):
                if f.endswith(('.mp4', '.mkv', '.webm')) and ".part" not in f:
                    path = os.path.abspath(os.path.join(v_dir, f))
                    if path not in processed_files:
                        new_targets.append((path, coll))
        
        if new_targets:
            print(f"\n{'='*60}")
            print(f"[INGESTOR] FOUND {len(new_targets)} NEW VIDEOS TO INGEST!")
            for target, coll_name in new_targets:
                v_name = os.path.basename(target)
                
                # Use collection-specific working directory to resume properly
                coll_workdir = os.path.join(WORKING_DIR, coll_name)
                if coll_name not in vrag_instances:
                    print(f"[INGESTOR] Initializing engine for {coll_name} at {coll_workdir}")
                    vrag_instances[coll_name] = VideoRAG(working_dir=coll_workdir)
                
                vrag = vrag_instances[coll_name]
                
                print(f"[INGESTOR] >>> PROCESSING START: {v_name} (Collection: {coll_name})")
                start_t = time.time()
                try:
                    # HEAVY OPERATION: Whisper + VLM + ImageBind + TVG build
                    # VideoRAG will automatically skip if already processed in this workdir
                    vrag.insert_video([target])
                    duration = time.time() - start_t
                    print(f"[INGESTOR] <<< DONE: {v_name} ({duration:.1f}s)")
                    
                    # NEW: Save progress immediately after success
                    save_progress(target)
                except Exception as e:
                    print(f"[INGESTOR] !!! ERROR processing {v_name}: {e}")
            print(f"{'='*60}\n")
        else:
            # Wait for more downloads to finish
            time.sleep(5)
            print(".", end="", flush=True)

if __name__ == "__main__":
    docs = get_doc_collections()
    
    # NEW: Load progress before starting
    load_progress()
    
    # Start downloader in a background thread
    dl_thread = threading.Thread(target=download_worker, args=(docs,), daemon=True)
    dl_thread.start()
    
    try:
        # Run ingestor in the main thread to allow clean Ctrl+C interrupt
        ingest_worker()
    except KeyboardInterrupt:
        print("\n[SYSTEM] Received Ctrl+C. Shutting down gracefully...")
        stop_flag = True
        dl_thread.join(timeout=1)
        print("[SYSTEM] Stopped.")
