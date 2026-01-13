import os
import time
import subprocess
import logging
import threading
import yt_dlp
from urllib.parse import urlparse
from functools import wraps
from typing import List, Optional, Dict, Any
from config import Config

logger = logging.getLogger(__name__)

def retry_on_failure(max_retries=3, delay=2, exceptions=(Exception,)):
    """Decorator for retry logic"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay * (attempt + 1))  # Exponential backoff
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}: {str(e)}")
            raise last_exception
        return wrapper
    return decorator

def is_valid_url(url):
    """Check if URL is valid"""
    try:
        if not url or not isinstance(url, str):
            return False
        result = urlparse(url.strip())
        return all([result.scheme in ['http', 'https'], result.netloc])
    except Exception as e:
        logger.error(f"URL validation error: {str(e)}")
        return False

def detect_platform(url):
    """Detect the platform from URL"""
    try:
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'instagram.com' in url_lower or 'instagr.am' in url_lower:
            return 'instagram'
        else:
            return 'direct'
    except Exception as e:
        logger.error(f"Platform detection error: {str(e)}")
        return 'direct'

def check_ffmpeg_available():
    """Check if FFmpeg is available"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.error(f"FFmpeg check failed: {str(e)}")
        return False

def sanitize_filename(name: str) -> str:
    """Create a safe filename from arbitrary text."""
    safe = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    safe = safe.replace(' ', '_')
    return safe or f"video_{int(time.time())}"

def extract_title(url: str) -> str:
    """Try to extract a human-friendly title from the URL/platform."""
    try:
        platform = detect_platform(url)
        if platform == 'direct':
            parsed = urlparse(url)
            basename = os.path.basename(parsed.path)
            if basename:
                return os.path.splitext(basename)[0]
            return parsed.netloc
        # Use yt-dlp metadata without downloading
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title') or info.get('id') or 'video'
    except Exception as e:
        logger.warning(f"Failed to extract title: {str(e)}")
        return "video"

def ensure_project_dirs(project_id: str):
    """Ensure project directories exist (Simplified to use main folders)."""
    # We no longer separate by project_id in folders, but we keep this for legacy calls
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.PROCESSED_FOLDER, exist_ok=True)
    os.makedirs(Config.CAPTIONS_FOLDER, exist_ok=True)
    return Config.UPLOAD_FOLDER, Config.PROCESSED_FOLDER, Config.CAPTIONS_FOLDER

# State for progress rate limiting
_progress_locks = threading.Lock()
_last_progress_time = {}

def thread_safe_status_update(status_key, update_dict):
    """Legacy helper for backward compatibility - updates job status in DB."""
    from database.models import Job
    # We assume status_key is the job_id. Only update if it's a real job.
    # To reduce DB calls, we don't call get_by_id here every time.
    # The update_status method will handle if the ID doesn't exist.
    progress = update_dict.get('progress')
    status = update_dict.get('status')
    error = update_dict.get('error')
    
    if not status and progress is None and not error:
        return

    # Map old statuses to new job statuses if needed
    mapped_status = None
    if status == 'completed': mapped_status = Job.STATUS_COMPLETED
    elif status == 'error': mapped_status = Job.STATUS_FAILED
    elif status: mapped_status = Job.STATUS_RUNNING
    
    try:
        Job.update_status(status_key, mapped_status, progress=progress, error_message=error)
    except Exception as e:
        logger.error(f"Failed to update status for {status_key}: {str(e)}")

def thread_safe_status_get(status_key):
    """Legacy helper - gets job status from DB."""
    from database.models import Job
    return Job.get_by_id(status_key) or {}

def update_progress(d, status_key):
    """Update job progress during download/processing with rate limiting"""
    try:
        if d.get('status') == 'downloading':
            now = time.time()
            with _progress_locks:
                last_time = _last_progress_time.get(status_key, 0)
                # Rate limit: max once per second
                if now - last_time < 1.0:
                    return
                _last_progress_time[status_key] = now

            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                progress = int((d['downloaded_bytes'] / total) * 100)
                thread_safe_status_update(status_key, {'progress': progress})
    except Exception as e:
        # Silent failure for progress to avoid crashing the main task
        pass
