import os
import uuid
import time
import shutil
import logging
import tempfile
import yt_dlp
import requests
import subprocess
import json
from datetime import datetime, timezone
from scenedetect import ContentDetector, AdaptiveDetector, SceneManager, open_video
from config import Config
from utils.helpers import (
    thread_safe_status_update, 
    detect_platform, 
    update_progress,
    ensure_project_dirs,
    retry_on_failure
)
from utils.storage import update_projects

logger = logging.getLogger(__name__)

@retry_on_failure(max_retries=3, delay=2, exceptions=(yt_dlp.utils.DownloadError, Exception))
def download_video(url, output_path, status_key, resolution='720'):
    """Download video using yt-dlp or requests for direct URLs"""
    try:
        thread_safe_status_update(status_key, {'status': 'downloading', 'progress': 0})
        platform = detect_platform(url)
        logger.info(f"Downloading from {platform}: {url} (Res: {resolution})")
        
        if platform == 'direct' and url.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv')):
            base_path = output_path.replace('.%(ext)s', '').replace('%(ext)s', '')
            return download_direct_video(url, base_path, status_key)
        
        # Build format string based on resolution
        if resolution == 'max':
            fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        else:
            res_val = int(resolution)
            fmt = f'bestvideo[height<={res_val}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res_val}][ext=mp4]/best'

        ydl_opts = {
            'format': fmt,
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [lambda d: update_progress(d, status_key)],
            'noplaylist': True,
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'merge_output_format': 'mp4'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        thread_safe_status_update(status_key, {'status': 'downloaded', 'progress': 50})
        return True
    except Exception as e:
        logger.error(f"Download failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise

@retry_on_failure(max_retries=3, delay=2, exceptions=(requests.RequestException, Exception))
def download_direct_video(url, output_path, status_key):
    """Download direct video URL using requests with retry"""
    try:
        logger.info(f"Downloading direct video: {url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, stream=True, timeout=Config.DOWNLOAD_TIMEOUT, headers=headers)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        ext = '.mp4'
        if url.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')):
            ext = os.path.splitext(url)[1]
        
        file_path = output_path + ext if not output_path.endswith(ext) else output_path
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192*4):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = min((downloaded / total_size) * 50, 50)
                        thread_safe_status_update(status_key, {'progress': progress})
        
        thread_safe_status_update(status_key, {'status': 'downloaded', 'progress': 50})
        return file_path
    except Exception as e:
        logger.error(f"Direct download error: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise

@retry_on_failure(max_retries=2, delay=3, exceptions=(subprocess.CalledProcessError, Exception))
def convert_to_tiktok_aspect(input_path, output_path, status_key):
    """Convert video to TikTok aspect ratio (9:16) with fast optimization"""
    try:
        thread_safe_status_update(status_key, {'status': 'processing', 'progress': 60})
        
        probe_cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', '-select_streams', 'v:0', input_path]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30, check=True)
        video_info = json.loads(result.stdout)
        video_stream = next((s for s in video_info.get('streams', []) if s.get('codec_type') == 'video'), None)
        
        width = int(video_stream.get('width', 0))
        height = int(video_stream.get('height', 0))
        target_width, target_height = 720, 1280
        input_aspect, target_aspect = width / height, 9 / 16
        
        if abs(input_aspect - target_aspect) < 0.01:
            filter_complex = f"scale={target_width}:{target_height}:flags=lanczos"
        elif input_aspect > target_aspect:
            new_width = int(height * target_aspect)
            x_offset = (width - new_width) // 2
            filter_complex = f"crop={new_width}:{height}:{x_offset}:0,scale={target_width}:{target_height}:flags=lanczos"
        else:
            new_height = int(width / target_aspect)
            y_offset = (new_height - height) // 2
            filter_complex = f"scale={target_width}:{new_height}:flags=lanczos,pad={target_width}:{target_height}:0:{y_offset}:black"
        
        ffmpeg_cmd = [
            'ffmpeg', '-i', input_path, '-vf', filter_complex,
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-y', output_path
        ]
        subprocess.run(ffmpeg_cmd, check=True, timeout=Config.PROCESS_TIMEOUT)
        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return True
    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise

@retry_on_failure(max_retries=2, delay=2)
def split_scenes(input_path, output_dir, status_key, min_scene_len=2.0, threshold=3.0):
    """Split video based on scene detection."""
    try:
        thread_safe_status_update(status_key, {'status': 'splitting', 'progress': 10})
        video = open_video(input_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len * video.frame_rate)))
        
        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()
        
        if not scene_list:
            thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100, 'message': 'No scenes detected'})
            return []

        base_name = os.path.splitext(os.path.basename(input_path))[0]
        clips = []
        for i, (start, end) in enumerate(scene_list):
            out_name = f"{base_name}_clip_{i+1}.mp4"
            out_path = os.path.join(output_dir, out_name)
            
            start_ts = start.get_seconds()
            duration = end.get_seconds() - start_ts
            
            cmd = [
                'ffmpeg', '-ss', str(start_ts), '-t', str(duration), '-i', input_path,
                '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
                '-c:a', 'aac', '-b:a', '192k', '-y', out_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            clips.append({'title': f"Clip {i+1}", 'filename': out_name})
            
            progress = 10 + (i + 1) / len(scene_list) * 90
            thread_safe_status_update(status_key, {'progress': progress})
            
        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return clips
    except Exception as e:
        logger.error(f"Scene split failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise

@retry_on_failure(max_retries=2, delay=2)
def split_fixed(input_path, output_dir, status_key, interval=30):
    """Split video into fixed intervals."""
    try:
        thread_safe_status_update(status_key, {'status': 'splitting', 'progress': 10})
        
        # Get duration
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path], capture_output=True, text=True)
        total_duration = float(probe.stdout.strip())
        
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        clips = []
        num_clips = int(total_duration // interval) + (1 if total_duration % interval > 0 else 0)
        
        for i in range(num_clips):
            start = i * interval
            out_name = f"{base_name}_part_{i+1}.mp4"
            out_path = os.path.join(output_dir, out_name)
            
            cmd = [
                'ffmpeg', '-ss', str(start), '-t', str(interval), '-i', input_path,
                '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
                '-c:a', 'aac', '-b:a', '192k', '-y', out_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            clips.append({'title': f"Part {i+1}", 'filename': out_name})
            
            progress = 10 + (i + 1) / num_clips * 90
            thread_safe_status_update(status_key, {'progress': progress})
            
        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return clips
    except Exception as e:
        logger.error(f"Fixed split failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise

@retry_on_failure(max_retries=2, delay=2)
def trim_video(input_path, output_path, start_time, end_time, status_key):
    """Trim a specific segment of the video."""
    try:
        thread_safe_status_update(status_key, {'status': 'trimming', 'progress': 30})
        duration = float(end_time) - float(start_time)
        
        cmd = [
            'ffmpeg', '-ss', str(start_time), '-t', str(duration), '-i', input_path,
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-c:a', 'aac', '-b:a', '192k', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return True
    except Exception as e:
        logger.error(f"Trim failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise
