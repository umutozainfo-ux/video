import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max
    UPLOAD_FOLDER = 'downloads'
    PROCESSED_FOLDER = 'processed'
    CAPTIONS_FOLDER = 'captions'
    PROJECT_DATA_FILE = 'projects.json'  # Legacy, kept for migration
    
    # Database configuration
    DATABASE_PATH = 'video_platform.db'
    
    # Job queue configuration
    NUM_JOB_WORKERS = 4  # Number of concurrent job workers
    JOB_RETENTION_DAYS = 30  # Days to keep completed jobs
    
    # Video processing
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    DOWNLOAD_TIMEOUT = 300  # 5 minutes
    PROCESS_TIMEOUT = 600  # 10 minutes
    WHISPER_MODEL_DEFAULT = 'tiny'
    
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-secret-key-12345')
    SESSION_COOKIE_SAMESITE = 'Lax'



def init_app_dirs(config):
    """Create necessary directories."""
    for folder in [config.UPLOAD_FOLDER, config.PROCESSED_FOLDER, config.CAPTIONS_FOLDER]:
        os.makedirs(folder, exist_ok=True)
