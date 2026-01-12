from flask import Flask, render_template, request, jsonify, send_file, Response
import os
import subprocess
import yt_dlp
import tempfile
import shutil
from pathlib import Path
import json
import threading
from werkzeug.utils import secure_filename
import requests
from urllib.parse import urlparse
import time
import logging
from functools import wraps
from typing import Optional, Tuple, Dict, Any, List
import uuid
from datetime import datetime, timezone
from faster_whisper import WhisperModel
import time
import logging
from functools import wraps
from typing import Optional, Tuple, Dict, Any
import uuid
from datetime import datetime
from scenedetect import ContentDetector, AdaptiveDetector, SceneManager, open_video

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max
app.config['UPLOAD_FOLDER'] = 'downloads'
app.config['PROCESSED_FOLDER'] = 'processed'
app.config['CAPTIONS_FOLDER'] = 'captions'
app.config['PROJECT_DATA_FILE'] = 'projects.json'
app.config['MAX_RETRIES'] = 3
app.config['RETRY_DELAY'] = 2  # seconds
app.config['DOWNLOAD_TIMEOUT'] = 300  # 5 minutes
app.config['PROCESS_TIMEOUT'] = 600  # 10 minutes
app.config['WHISPER_MODEL_DEFAULT'] = 'tiny'

# Create necessary directories
for folder in [app.config['UPLOAD_FOLDER'], app.config['PROCESSED_FOLDER'], app.config['CAPTIONS_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# Store processing status with thread locks
processing_status = {}
status_locks = {}
import threading as th
status_lock = th.Lock()
projects_lock = th.Lock()
whisper_models: Dict[str, WhisperModel] = {}


def load_projects() -> Dict[str, Any]:
    """Load projects from disk."""
    try:
        if not os.path.exists(app.config['PROJECT_DATA_FILE']):
            return {}
        with open(app.config['PROJECT_DATA_FILE'], 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load projects: {str(e)}")
        return {}


def save_projects(data: Dict[str, Any]) -> None:
    """Persist projects to disk."""
    try:
        with open(app.config['PROJECT_DATA_FILE'], 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save projects: {str(e)}")


def get_projects() -> Dict[str, Any]:
    with projects_lock:
        return load_projects()


def update_projects(mutator):
    """Thread-safe project mutation helper."""
    with projects_lock:
        data = load_projects()
        mutated = mutator(data) or data
        save_projects(mutated)
        return mutated

def thread_safe_status_update(status_key, update_dict):
    """Thread-safe status update"""
    with status_lock:
        if status_key not in processing_status:
            processing_status[status_key] = {}
        processing_status[status_key].update(update_dict)

def thread_safe_status_get(status_key):
    """Thread-safe status get"""
    with status_lock:
        return processing_status.get(status_key, {}).copy()

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

def update_progress(d, status_key):
    """Update download progress"""
    try:
        if d.get('status') == 'downloading':
            if 'total_bytes' in d:
                progress = min((d['downloaded_bytes'] / d['total_bytes']) * 50, 50)
                thread_safe_status_update(status_key, {'progress': progress})
            elif 'total_bytes_estimate' in d:
                progress = min((d['downloaded_bytes'] / d['total_bytes_estimate']) * 50, 50)
                thread_safe_status_update(status_key, {'progress': progress})
    except Exception as e:
        logger.error(f"Progress update error: {str(e)}")


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
    """Ensure project directories exist."""
    downloads_dir = os.path.join(app.config['UPLOAD_FOLDER'], project_id)
    processed_dir = os.path.join(app.config['PROCESSED_FOLDER'], project_id)
    captions_dir = os.path.join(app.config['CAPTIONS_FOLDER'], project_id)
    os.makedirs(downloads_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(captions_dir, exist_ok=True)
    return downloads_dir, processed_dir, captions_dir


def get_whisper_model(size: str) -> WhisperModel:
    """Load and cache faster-whisper model."""
    size = size or app.config['WHISPER_MODEL_DEFAULT']
    if size not in whisper_models:
        # Disable GPU if unavailable; fallback to CPU
        whisper_models[size] = WhisperModel(size, device="auto", compute_type="auto")
    return whisper_models[size]


def list_captions_for_video(base_name: str, captions_dir: str) -> List[str]:
    """List caption files for a given base name in captions dir."""
    if not os.path.exists(captions_dir):
        return []
    return [f for f in os.listdir(captions_dir) if f.startswith(base_name) and f.endswith('.srt')]


def find_video(project: Dict[str, Any], video_id: str) -> Optional[Dict[str, Any]]:
    for v in project.get('videos', []):
        if v.get('id') == video_id:
            return v
    return None


def write_srt(segments, path: str, word_level: bool):
    """Write segments/words to SRT file."""
    def format_ts(t):
        hrs = int(t // 3600)
        mins = int((t % 3600) // 60)
        secs = int(t % 60)
        millis = int((t - int(t)) * 1000)
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

    lines: List[str] = []
    idx = 1
    if word_level:
        for seg in segments:
            for w in seg.words:
                start, end, text = w.start, w.end, w.word.strip()
                if not text:
                    continue
                lines.append(str(idx))
                lines.append(f"{format_ts(start)} --> {format_ts(end)}")
                lines.append(text)
                lines.append("")
                idx += 1
    else:
        for seg in segments:
            start, end, text = seg.start, seg.end, seg.text.strip()
            if not text:
                continue
            lines.append(str(idx))
            lines.append(f"{format_ts(start)} --> {format_ts(end)}")
            lines.append(text)
            lines.append("")
            idx += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

@retry_on_failure(max_retries=3, delay=2, exceptions=(yt_dlp.utils.DownloadError, Exception))
def download_video(url, output_path, status_key):
    """Download video using yt-dlp or requests for direct URLs"""
    try:
        thread_safe_status_update(status_key, {'status': 'downloading', 'progress': 0})
        
        platform = detect_platform(url)
        logger.info(f"Downloading from {platform}: {url}")
        
        # For direct video URLs, use requests
        if platform == 'direct' and url.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv')):
            base_path = output_path.replace('.%(ext)s', '').replace('%(ext)s', '')
            return download_direct_video(url, base_path, status_key)
        
        # For platform URLs, use yt-dlp with optimized settings
        ydl_opts = {
            'format': 'best[height<=720][ext=mp4]/best[height<=720]/best[height<=480]/best',  # Prefer mp4, medium quality
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [lambda d: update_progress(d, status_key)],
            'noplaylist': True,  # Don't download playlists
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'ignoreerrors': False,
            'no_check_certificate': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        thread_safe_status_update(status_key, {'status': 'downloaded', 'progress': 50})
        logger.info(f"Download completed for {status_key}")
        return True
    except yt_dlp.utils.DownloadError as e:
        error_msg = f"Download failed: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise
    except Exception as e:
        error_msg = f"Unexpected download error: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise

@retry_on_failure(max_retries=3, delay=2, exceptions=(requests.RequestException, Exception))
def download_direct_video(url, output_path, status_key):
    """Download direct video URL using requests with retry"""
    try:
        logger.info(f"Downloading direct video: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, stream=True, timeout=app.config['DOWNLOAD_TIMEOUT'], headers=headers)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        # Determine file extension from URL or content-type
        ext = '.mp4'
        content_type = response.headers.get('content-type', '').lower()
        if 'webm' in content_type:
            ext = '.webm'
        elif 'quicktime' in content_type or 'mov' in content_type:
            ext = '.mov'
        elif 'x-matroska' in content_type or 'mkv' in content_type:
            ext = '.mkv'
        elif url.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')):
            ext = os.path.splitext(url)[1]
        
        file_path = output_path + ext if not output_path.endswith(ext) else output_path
        
        chunk_size = 8192 * 4  # Larger chunks for faster download
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = min((downloaded / total_size) * 50, 50)
                        thread_safe_status_update(status_key, {'progress': progress})
        
        # Verify file was downloaded
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise Exception("Downloaded file is empty or missing")
        
        thread_safe_status_update(status_key, {'status': 'downloaded', 'progress': 50})
        logger.info(f"Direct download completed: {file_path}")
        return file_path
    except requests.Timeout:
        error_msg = "Download timeout - file too large or connection too slow"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise
    except requests.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise
    except Exception as e:
        error_msg = f"Download error: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise

@retry_on_failure(max_retries=2, delay=3, exceptions=(subprocess.CalledProcessError, Exception))
def convert_to_tiktok_aspect(input_path, output_path, status_key):
    """Convert video to TikTok aspect ratio (9:16) with fast optimization"""
    try:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        if os.path.getsize(input_path) == 0:
            raise ValueError("Input file is empty")
        
        thread_safe_status_update(status_key, {'status': 'processing', 'progress': 60})
        logger.info(f"Processing video: {input_path}")
        
        # Get video dimensions with timeout
        probe_cmd = [
            'ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams',
            '-select_streams', 'v:0', input_path
        ]
        
        try:
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30, check=True)
            video_info = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            raise Exception("FFprobe timeout - video file may be corrupted")
        except json.JSONDecodeError:
            raise Exception("Failed to parse video information")
        
        video_stream = next((s for s in video_info.get('streams', []) if s.get('codec_type') == 'video'), None)
        if not video_stream:
            raise Exception("No video stream found in file")
        
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        
        if width == 0 or height == 0:
            raise Exception("Invalid video dimensions")
        
        target_width = 720
        target_height = 1280  # TikTok aspect ratio 9:16
        
        # Calculate crop/pad to maintain aspect ratio
        input_aspect = width / height
        target_aspect = 9 / 16
        
        if abs(input_aspect - target_aspect) < 0.01:
            # Already correct aspect ratio, just scale
            filter_complex = f"scale={target_width}:{target_height}"
        elif input_aspect > target_aspect:
            # Video is wider, need to crop sides
            new_width = int(height * target_aspect)
            x_offset = (width - new_width) // 2
            filter_complex = f"crop={new_width}:{height}:{x_offset}:0,scale={target_width}:{target_height}"
        else:
            # Video is taller, need to add letterboxing
            new_height = int(width / target_aspect)
            y_offset = (new_height - height) // 2
            filter_complex = f"scale={target_width}:{new_height},pad={target_width}:{target_height}:0:{y_offset}:black"
        
        # Check for hardware acceleration (NVIDIA, AMD, Intel)
        hw_accel = None
        try:
            # Try to detect NVIDIA GPU
            result = subprocess.run(['nvidia-smi'], capture_output=True, timeout=2)
            if result.returncode == 0:
                hw_accel = 'h264_nvenc'
                logger.info("Using NVIDIA hardware acceleration")
        except:
            pass
        
        if not hw_accel:
            try:
                # Try to detect Intel Quick Sync
                result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, timeout=2)
                if 'h264_qsv' in result.stdout.decode('utf-8', errors='ignore'):
                    hw_accel = 'h264_qsv'
                    logger.info("Using Intel Quick Sync hardware acceleration")
            except:
                pass
        
        # FFmpeg command for fast conversion with optimization
        ffmpeg_cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', filter_complex,
            '-c:v', hw_accel if hw_accel else 'libx264',  # Use hardware acceleration if available
            '-preset', 'fast' if hw_accel else 'veryfast',  # Faster encoding
            '-crf', '23',  # Medium quality
            '-c:a', 'aac',  # AAC audio codec
            '-b:a', '128k',  # Audio bitrate
            '-movflags', '+faststart',  # Enable web streaming
            '-threads', '0',  # Use all available CPU threads
            '-y',  # Overwrite output file
            output_path
        ]
        
        # Add hardware acceleration input if using NVIDIA
        if hw_accel == 'h264_nvenc':
            ffmpeg_cmd.insert(1, '-hwaccel')
            ffmpeg_cmd.insert(2, 'cuda')
            ffmpeg_cmd.insert(3, '-hwaccel_output_format')
            ffmpeg_cmd.insert(4, 'cuda')
        
        try:
            result = subprocess.run(
                ffmpeg_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=app.config['PROCESS_TIMEOUT'],
            )
        except subprocess.TimeoutExpired:
            raise Exception("Video processing timeout - file may be too large or complex")
        except subprocess.CalledProcessError as e:
            error_output = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"FFmpeg error: {error_output}")
            raise Exception(f"Video processing failed: {error_output[:200]}")
        
        # Verify output file
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Output file is empty or missing")
        
        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        logger.info(f"Processing completed: {output_path}")
        return True
    except FileNotFoundError as e:
        error_msg = f"File not found: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise
    except subprocess.TimeoutExpired:
        error_msg = "Processing timeout - video may be too large"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise
    except Exception as e:
        error_msg = f"Processing error: {str(e)}"
        logger.error(error_msg)
        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
        raise

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/projects', methods=['GET', 'POST'])
def projects():
    """List or create projects."""
    if request.method == 'GET':
        return jsonify(list(get_projects().values()))
    # POST create
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Project name is required'}), 400

    def mutator(data):
        project_id = str(uuid.uuid4())
        project = {
            'id': project_id,
            'name': name,
            'created_at': datetime.utcnow().isoformat(),
            'videos': []
        }
        data[project_id] = project
        ensure_project_dirs(project_id)
        return data

    updated = update_projects(mutator)
    return jsonify(updated[list(updated.keys())[-1]]), 201


@app.route('/api/projects/<project_id>', methods=['GET', 'DELETE'])
def project_detail(project_id):
    data = get_projects()
    project = data.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    if request.method == 'GET':
        return jsonify(project)

    # DELETE
    def mutator(d):
        d.pop(project_id, None)
        return d

    update_projects(mutator)
    # Optionally keep files; safer to keep. Could delete directories if needed.
    return jsonify({'status': 'deleted'})


@app.route('/api/projects/<project_id>/videos', methods=['GET'])
def project_videos(project_id):
    data = get_projects()
    project = data.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    # enrich with caption list
    _, _, captions_dir = ensure_project_dirs(project_id)
    videos = project.get('videos', [])
    for v in videos:
        base = os.path.splitext(v.get('filename', ''))[0]
        v['captions'] = list_captions_for_video(base, captions_dir)
    return jsonify(videos)


@app.route('/api/projects/<project_id>/videos/<video_id>', methods=['GET', 'DELETE'])
def project_video_detail(project_id, video_id):
    data = get_projects()
    project = data.get(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    video = find_video(project, video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    _, processed_dir, captions_dir = ensure_project_dirs(project_id)
    base = os.path.splitext(video.get('filename', ''))[0]
    captions = list_captions_for_video(base, captions_dir)

    if request.method == 'GET':
        result = dict(video)
        result['captions'] = captions
        return jsonify(result)

    # DELETE
    def mutator(d):
        proj = d.get(project_id)
        if proj is None:
            return d
        proj['videos'] = [v for v in proj.get('videos', []) if v.get('id') != video_id]
        return d

    update_projects(mutator)

    # Delete files
    video_path = os.path.join(processed_dir, video.get('filename', ''))
    if os.path.exists(video_path):
        try:
            os.remove(video_path)
        except Exception as e:
            logger.warning(f"Failed to delete video file: {str(e)}")
    for cap in captions:
        cap_path = os.path.join(captions_dir, cap)
        if os.path.exists(cap_path):
            try:
                os.remove(cap_path)
            except Exception as e:
                logger.warning(f"Failed to delete caption file: {str(e)}")
    return jsonify({'status': 'deleted'})


@app.route('/api/download', methods=['POST'])
def download():
    """Download and process video"""
    try:
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Empty request body'}), 400
        
        url = data.get('url', '').strip()
        project_id = (data.get('project_id') or '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        if not is_valid_url(url):
            return jsonify({'error': 'Invalid URL format'}), 400
        
        # Check FFmpeg availability
        if not check_ffmpeg_available():
            return jsonify({'error': 'FFmpeg is not installed or not in PATH. Please install FFmpeg first.'}), 500
        
        if not project_id:
            return jsonify({'error': 'project_id is required'}), 400

        projects_data = get_projects()
        project = projects_data.get(project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404

        # Generate unique filename and title from source
        file_id = str(uuid.uuid4())
        status_key = file_id
        raw_title = extract_title(url)
        safe_title = sanitize_filename(raw_title)
        
        # Prepare directories
        try:
            temp_dir = tempfile.mkdtemp(prefix='video_dl_')
            _, processed_dir, captions_dir = ensure_project_dirs(project_id)
        except Exception as e:
            logger.error(f"Failed to create temp directory: {str(e)}")
            return jsonify({'error': 'Failed to create temporary directory'}), 500

        input_path = os.path.join(temp_dir, f'input_{file_id}.%(ext)s')

        # Build output filename from source title, ensure uniqueness inside project
        base_name = safe_title or f"video_{file_id}"
        output_filename = f"{base_name}.mp4"
        output_path = os.path.join(processed_dir, output_filename)

        suffix = 1
        while os.path.exists(output_path):
            output_filename = f"{base_name}_{suffix}.mp4"
            output_path = os.path.join(processed_dir, output_filename)
            suffix += 1
        
        thread_safe_status_update(status_key, {'status': 'starting', 'progress': 0, 'project_id': project_id, 'title': safe_title})
        
        # Download video in background thread
        def process_video():
            temp_dir_cleanup = temp_dir
            try:
                # Download with retry
                result = download_video(url, input_path, status_key)
                if not result:
                    return
                
                # Handle direct download (returns file path) vs yt-dlp (returns True)
                if isinstance(result, str):
                    actual_input_path = result
                else:
                    # Find the actual downloaded file (yt-dlp adds extension)
                    try:
                        downloaded_files = [
                            f for f in os.listdir(temp_dir_cleanup) 
                            if os.path.isfile(os.path.join(temp_dir_cleanup, f)) 
                            and not f.endswith('.part')  # Exclude incomplete downloads
                        ]
                        if not downloaded_files:
                            raise FileNotFoundError('Downloaded file not found')
                        
                        # Get the most recently modified file (the downloaded one)
                        downloaded_files.sort(
                            key=lambda f: os.path.getmtime(os.path.join(temp_dir_cleanup, f)), 
                            reverse=True
                        )
                        actual_input_path = os.path.join(temp_dir_cleanup, downloaded_files[0])
                        
                        # Verify file exists and is not empty
                        if not os.path.exists(actual_input_path) or os.path.getsize(actual_input_path) == 0:
                            raise ValueError('Downloaded file is empty')
                    except Exception as e:
                        error_msg = f"Failed to locate downloaded file: {str(e)}"
                        logger.error(error_msg)
                        thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
                        return
                
                # Convert to TikTok aspect with retry
                if not convert_to_tiktok_aspect(actual_input_path, output_path, status_key):
                    return
                
                # Verify final output
                if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    raise Exception("Output file verification failed")

                # Update project metadata
                def mutator(d):
                    proj = d.get(project_id)
                    if proj is None:
                        return d
                    videos = proj.setdefault('videos', [])
                    videos.append({
                        'id': status_key,
                        'title': safe_title,
                        'source_url': url,
                        'filename': output_filename,
                        'project_id': project_id,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    })
                    return d

                update_projects(mutator)
                
                thread_safe_status_update(status_key, {
                    'file': output_filename,
                    'project_id': project_id,
                    'title': safe_title,
                    'status': 'completed',
                    'progress': 100
                })
                logger.info(f"Successfully processed video: {output_filename}")
            except Exception as e:
                error_msg = f"Processing failed: {str(e)}"
                logger.error(error_msg)
                thread_safe_status_update(status_key, {'status': 'error', 'error': error_msg})
            finally:
                # Cleanup temp files
                try:
                    shutil.rmtree(temp_dir_cleanup, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory: {str(e)}")
        
        thread = threading.Thread(target=process_video)
        thread.daemon = True
        thread.start()
        
        return jsonify({'id': file_id, 'status': 'processing'})
    
    except Exception as e:
        logger.error(f"Download endpoint error: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/status/<path:file_id>')
def get_status(file_id):
    """Get processing status"""
    try:
        if not file_id:
            return jsonify({'error': 'Invalid file ID'}), 400
        
        # Allow UUIDs, caption, split, and burn status keys
        if not (len(file_id) == 36 or any(file_id.startswith(p) for p in ['caption_', 'split_', 'burn_'])):
            return jsonify({'error': 'Invalid file ID format'}), 400
        
        status = thread_safe_status_get(file_id)
        if not status:
            return jsonify({'status': 'not_found'}), 404
        
        return jsonify(status)
    except Exception as e:
        logger.error(f"Status endpoint error: {str(e)}")
        return jsonify({'error': 'Failed to get status'}), 500

@app.route('/api/video/<project_id>/<filename>')
def get_video(project_id, filename):
    """Serve processed video"""
    try:
        if not filename or not project_id:
            return jsonify({'error': 'Filename and project_id required'}), 400
        
        filename = secure_filename(filename)
        file_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        if not os.path.isfile(file_path):
            return jsonify({'error': 'Invalid file'}), 400
        
        return send_file(file_path, mimetype='video/mp4', conditional=True)
    except Exception as e:
        logger.error(f"Video serve error: {str(e)}")
        return jsonify({'error': 'Failed to serve video'}), 500

@app.route('/api/stream/<project_id>/<filename>')
def stream_video(project_id, filename):
    """Stream video for better playback with range support"""
    try:
        if not filename or not project_id:
            return jsonify({'error': 'Filename and project_id required'}), 400
        
        filename = secure_filename(filename)
        file_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        range_header = request.headers.get('Range', None)
        if not range_header:
            return send_file(file_path, mimetype='video/mp4', conditional=True)
        
        import re
        size = os.path.getsize(file_path)
        byte1 = 0
        byte2 = size - 1
        
        m = re.search(r'(\d+)-(\d*)', range_header)
        if m:
            g = m.groups()
            if g[0]:
                byte1 = int(g[0])
            if g[1]:
                byte2 = int(g[1])
        
        length = byte2 - byte1 + 1
        
        with open(file_path, 'rb') as f:
            f.seek(byte1)
            data = f.read(length)
        
        rv = Response(data, 206, mimetype='video/mp4', direct_passthrough=True)
        rv.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{size}')
        rv.headers.add('Accept-Ranges', 'bytes')
        rv.headers.add('Content-Length', str(length))
        return rv
    except Exception as e:
        logger.error(f"Stream error: {str(e)}")
        return jsonify({'error': 'Failed to stream video'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/projects/<project_id>/videos/<filename>/caption', methods=['POST'])
def generate_caption(project_id, filename):
    """Generate captions (word or sentence level) for a video in a project."""
    try:
        project_id = secure_filename(project_id)
        filename = secure_filename(filename)
        data = request.get_json(force=True, silent=True) or {}
        level = (data.get('level') or 'word').lower()
        model_size = (data.get('model') or app.config['WHISPER_MODEL_DEFAULT']).lower()

        if level not in ('word', 'sentence'):
            return jsonify({'error': 'level must be word or sentence'}), 400

        # Locate video file
        video_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, filename)
        if not os.path.exists(video_path):
            return jsonify({'error': 'Video not found'}), 404

        # Ensure captions directory
        _, _, captions_dir = ensure_project_dirs(project_id)

        # Caption filename
        base_name = os.path.splitext(filename)[0]
        caption_filename = f"{base_name}_{level}.srt"
        caption_path = os.path.join(captions_dir, caption_filename)

        status_key = f"caption_{project_id}_{filename}"
        thread_safe_status_update(status_key, {'status': 'starting', 'progress': 0, 'project_id': project_id})

        def worker():
            try:
                thread_safe_status_update(status_key, {'status': 'loading_model', 'progress': 10})
                model = get_whisper_model(model_size)
                
                thread_safe_status_update(status_key, {'status': 'transcribing', 'progress': 30})
                # Use word timestamps for word level
                word_ts = level == 'word'
                # Disable vad_filter to ensure all words are captured
                segments_gen, info = model.transcribe(
                    video_path,
                    word_timestamps=word_ts,
                    vad_filter=False,
                    beam_size=5
                )
                
                duration = info.duration
                processed_segments = []
                
                for segment in segments_gen:
                    processed_segments.append(segment)
                    if duration > 0:
                        prog = 30 + (segment.end / duration) * 50
                        thread_safe_status_update(status_key, {'status': 'transcribing', 'progress': int(prog)})
                
                thread_safe_status_update(status_key, {'status': 'writing_captions', 'progress': 90})
                write_srt(processed_segments, caption_path, word_level=word_ts)

                thread_safe_status_update(status_key, {
                    'status': 'completed',
                    'progress': 100,
                    'caption_file': caption_filename,
                    'project_id': project_id,
                    'level': level,
                    'model': model_size
                })
                logger.info(f"Caption generation completed: {caption_filename}")
            except Exception as e:
                logger.error(f"Caption generation failed: {str(e)}", exc_info=True)
                thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return jsonify({'status': 'processing', 'id': status_key, 'caption_file': caption_filename})
    except Exception as e:
        logger.error(f"Caption endpoint error: {str(e)}")
        return jsonify({'error': 'Failed to start captioning'}), 500


@app.route('/api/projects/<project_id>/videos/<video_id>/burn', methods=['POST'])
def burn_caption(project_id, video_id):
    """Hardcode (burn) captions into the video."""
    try:
        project_id = secure_filename(project_id)
        data = request.get_json(force=True, silent=True) or {}
        caption_filename = data.get('caption_file')
        
        if not caption_filename:
            return jsonify({'error': 'caption_file is required'}), 400
        
        caption_filename = secure_filename(caption_filename)
        
        # Load project
        projects_data = get_projects()
        project = projects_data.get(project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        video = find_video(project, video_id)
        if not video:
            return jsonify({'error': 'Video not found'}), 404
            
        input_filename = video['filename']
        input_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, input_filename)
        caption_path = os.path.join(app.config['CAPTIONS_FOLDER'], project_id, caption_filename)
        
        if not os.path.exists(input_path):
            return jsonify({'error': 'Video file not found'}), 404
        if not os.path.exists(caption_path):
            return jsonify({'error': 'Caption file not found'}), 404
            
        base_name = os.path.splitext(input_filename)[0]
        output_filename = f"{base_name}_burned.mp4"
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, output_filename)
        
        status_key = f"burn_{project_id}_{video_id}"
        thread_safe_status_update(status_key, {'status': 'starting', 'progress': 0, 'project_id': project_id})
        
        def worker():
            try:
                thread_safe_status_update(status_key, {'status': 'burning', 'progress': 10})
                
                # Windows path escaping for FFmpeg subtitles filter
                abs_caption_path = os.path.abspath(caption_path).replace('\\', '/').replace(':', '\\:')
                
                ffmpeg_cmd = [
                    'ffmpeg', '-i', input_path,
                    '-vf', f"subtitles='{abs_caption_path}'",
                    '-c:a', 'copy',
                    '-y',
                    output_path
                ]
                
                logger.info(f"Running burn command: {' '.join(ffmpeg_cmd)}")
                
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg failed: {result.stderr}")
                
                def mutator(d):
                    p = d.get(project_id)
                    if not p: return d
                    v_list = p.setdefault('videos', [])
                    if not any(v['filename'] == output_filename for v in v_list):
                        v_list.append({
                            'id': str(uuid.uuid4()),
                            'title': f"{video.get('title', 'Video')} (Burned)",
                            'source_url': video.get('source_url'),
                            'filename': output_filename,
                            'project_id': project_id,
                            'created_at': datetime.now(timezone.utc).isoformat()
                        })
                    return d
                
                update_projects(mutator)
                
                thread_safe_status_update(status_key, {
                    'status': 'completed',
                    'progress': 100,
                    'file': output_filename,
                    'project_id': project_id
                })
            except Exception as e:
                logger.error(f"Burn failed: {str(e)}")
                thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        
        return jsonify({'status': 'processing', 'id': status_key})
    except Exception as e:
        logger.error(f"Burn caption error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/projects/<project_id>/videos/<video_id>/split-scenes', methods=['POST'])
def split_scenes(project_id, video_id):
    """Detect scenes and split video into multiple clips."""
    try:
        project_id = secure_filename(project_id)
        data = request.get_json(force=True, silent=True) or {}
        min_scene_len = float(data.get('min_scene_len', 2.0))
        threshold = float(data.get('threshold', 3.0)) # Default AdaptiveDetector threshold
        
        # Load project
        projects_data = get_projects()
        project = projects_data.get(project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        video_obj = find_video(project, video_id)
        if not video_obj:
            return jsonify({'error': 'Video not found'}), 404
            
        input_filename = video_obj['filename']
        input_path = os.path.join(app.config['PROCESSED_FOLDER'], project_id, input_filename)
        processed_dir = os.path.join(app.config['PROCESSED_FOLDER'], project_id)
        
        if not os.path.exists(input_path):
            return jsonify({'error': f"Video file not found at {input_path}"}), 404
            
        status_key = f"split_{project_id}_{video_id}"
        thread_safe_status_update(status_key, {
            'status': 'starting', 
            'progress': 0, 
            'project_id': project_id,
            'details': 'Initializing AI Scene Detector'
        })
        
        def worker():
            try:
                thread_safe_status_update(status_key, {'status': 'detecting_scenes', 'progress': 5, 'details': 'Analyzing video content...'})
                
                # Use scenedetect to find scenes with AdaptiveDetector
                video = open_video(input_path)
                scene_manager = SceneManager()
                scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
                
                def progress_callback(frame_img, frame_num):
                    try:
                        # Fallback to estimation if duration is weird
                        total_frames = 0
                        try:
                            total_frames = video.duration.get_frames()
                        except:
                            pass
                            
                        if total_frames > 0:
                            prog = 5 + (frame_num / total_frames) * 40
                            thread_safe_status_update(status_key, {'progress': int(prog)})
                    except:
                        pass

                scene_manager.detect_scenes(video, callback=progress_callback)
                detected_scenes = scene_manager.get_scene_list()
                
                # Filter scenes by minimum length
                scene_list = [s for s in detected_scenes if (s[1].get_seconds() - s[0].get_seconds()) >= min_scene_len]
                
                if not scene_list:
                    thread_safe_status_update(status_key, {
                        'status': 'error', 
                        'error': f'No scenes detected with length >= {min_scene_len}s. Try lowering sensitivity or length.'
                    })
                    return

                thread_safe_status_update(status_key, {
                    'status': 'splitting_clips', 
                    'progress': 50, 
                    'details': f'Extracting {len(scene_list)} clips...'
                })
                
                base_name = os.path.splitext(input_filename)[0]
                video_title = video_obj.get('title', 'Video')
                video_source = video_obj.get('source_url', '')
                
                total_scenes = len(scene_list)
                new_videos = []
                
                for i, scene in enumerate(scene_list):
                    start_time = scene[0].get_seconds()
                    end_time = scene[1].get_seconds()
                    duration = end_time - start_time
                    
                    clip_filename = f"{base_name}_clip_{i+1}.mp4"
                    clip_path = os.path.join(processed_dir, clip_filename)
                    
                    # Ensure unique filename
                    suffix = 1
                    while os.path.exists(clip_path):
                        clip_filename = f"{base_name}_clip_{i+1}_{suffix}.mp4"
                        clip_path = os.path.join(processed_dir, clip_filename)
                        suffix += 1

                    # FFmpeg to extract clip - optimized
                    ffmpeg_cmd = [
                        'ffmpeg', '-ss', f"{start_time:.3f}", '-t', f"{duration:.3f}",
                        '-i', input_path,
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
                        '-c:a', 'aac', '-b:a', '128k',
                        '-y', clip_path
                    ]
                    
                    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        logger.error(f"Clip {i+1} failed: {result.stderr}")
                        continue
                        
                    new_videos.append({
                        'id': str(uuid.uuid4()),
                        'title': f"{video_title} Clip {i+1}",
                        'source_url': video_source,
                        'filename': clip_filename,
                        'project_id': project_id,
                        'created_at': datetime.now(timezone.utc).isoformat()
                    })
                    
                    # Progress 50% to 100%
                    prog = 50 + ((i + 1) / total_scenes) * 50
                    thread_safe_status_update(status_key, {'progress': int(prog), 'details': f'Processed {i+1}/{total_scenes} clips'})

                # Update project metadata once
                if new_videos:
                    def mutator(d):
                        p = d.get(project_id)
                        if not p: return d
                        v_list = p.setdefault('videos', [])
                        v_list.extend(new_videos)
                        return d
                    update_projects(mutator)

                thread_safe_status_update(status_key, {
                    'status': 'completed',
                    'progress': 100,
                    'project_id': project_id,
                    'clips_count': len(new_videos)
                })
                logger.info(f"Split completed: {len(new_videos)} clips created")
            except Exception as e:
                logger.error(f"Split failed: {str(e)}", exc_info=True)
                thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        
        return jsonify({'status': 'processing', 'id': status_key})
    except Exception as e:
        logger.error(f"Split scenes error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/caption/<project_id>/<filename>')
def get_caption(project_id, filename):
    """Download caption file."""
    try:
        project_id = secure_filename(project_id)
        filename = secure_filename(filename)
        caption_path = os.path.join(app.config['CAPTIONS_FOLDER'], project_id, filename)
        if not os.path.exists(caption_path):
            return jsonify({'error': 'Caption not found'}), 404
        return send_file(caption_path, mimetype='text/plain', as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"Caption serve error: {str(e)}")
        return jsonify({'error': 'Failed to serve caption'}), 500

if __name__ == '__main__':
    # Check FFmpeg on startup
    if not check_ffmpeg_available():
        logger.warning("FFmpeg not found! Video processing will fail. Please install FFmpeg.")
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
