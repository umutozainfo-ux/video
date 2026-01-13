import os
import time
import logging
from config import Config

logger = logging.getLogger(__name__)

def run_storage_cleanup(max_age_hours=48):
    """Automatically delete old processed files and downloads to save space."""
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    
    folders_to_clean = [
        Config.UPLOAD_FOLDER,
        Config.PROCESSED_FOLDER,
        Config.CAPTIONS_FOLDER
    ]
    
    deleted_count = 0
    freed_space = 0
    
    for folder in folders_to_clean:
        if not os.path.exists(folder):
            continue
            
        for root, dirs, files in os.walk(folder):
            for f in files:
                file_path = os.path.join(root, f)
                try:
                    # Check if file is older than max_age
                    file_stat = os.stat(file_path)
                    if (now - file_stat.st_mtime) > max_age_seconds:
                        file_size = file_stat.st_size
                        os.remove(file_path)
                        deleted_count += 1
                        freed_space += file_size
                except Exception as e:
                    logger.error(f"Error cleaning file {file_path}: {e}")
                    
    if deleted_count > 0:
        logger.info(f"Storage Cleanup: Removed {deleted_count} old files, freed {freed_space / (1024*1024):.2f} MB")
