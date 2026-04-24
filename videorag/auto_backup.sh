#!/bin/bash
set +e

echo "==================================================="
echo "Google Drive Auto-Backup Watcher (Continuous Sync)"
echo "==================================================="

# Thay thế đường dẫn Google Drive bằng thư mục backup nằm riêng biệt ngoài project
BACKUP_DIR="$(dirname "$0")/../../VideoRAG_Backup"
mkdir -p "$BACKUP_DIR"

# Chuyển về thư mục VideoRAG-algorithm gốc để lệnh zip hoạt động đúng
cd "$(dirname "$0")/.."

do_backup() {
    echo "$(date) - Zipping VDB Workdir..."
    zip -r "$BACKUP_DIR/EBR-RAG-workdir_backup.zip" longervideos/EBR-RAG-workdir/ > /dev/null 2>&1
    
    echo "$(date) - Zipping all_answers..."
    zip -r "$BACKUP_DIR/all_answers_backup.zip" reproduce/all_answers/ > /dev/null 2>&1
    
    echo "$(date) - Zipping evaluation requests..."
    zip -r "$BACKUP_DIR/eval_requests_backup.zip" reproduce/quantitative_comparison/ > /dev/null 2>&1
}

# Continuous backup loop every 10 minutes while pipeline runs
while pgrep -f "run_all_pipeline.sh" > /dev/null; do
    echo "---------------------------------------------------"
    echo "Running periodic backup to Google Drive..."
    do_backup
    echo "Backup synced. Sleeping for 10 minutes..."
    sleep 600
done

echo "---------------------------------------------------"
echo "Pipeline finished! Performing final backup..."
do_backup
echo "Backup to Google Drive completed successfully!"
echo "==================================================="
