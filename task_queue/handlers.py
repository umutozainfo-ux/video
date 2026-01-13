"""
Job handlers that integrate existing services with the job queue system.
Each handler processes a specific type of job.
"""

import os
import logging
import uuid
from typing import Dict, Any
from config import Config
from database.models import Video, Caption, Project
from task_queue.job_queue import update_job_progress
from services.video_service import (
    download_video,
    convert_to_tiktok_aspect,
    safe_import_video,
    split_scenes,
    split_fixed,
    trim_video
)
from services.caption_service import (
    get_whisper_model,
    write_srt,
    burn_captions
)

from utils.helpers import extract_title

logger = logging.getLogger(__name__)

def get_video_path(video: Dict[str, Any]) -> str:
    """Resolve the absolute path for a video, checking both upload and processed folders."""
    filename = video['filename']
    upload_path = os.path.join(Config.UPLOAD_FOLDER, filename)
    processed_path = os.path.join(Config.PROCESSED_FOLDER, filename)
    
    # Also check legacy clip subfolder
    clip_subfolder_path = os.path.join(Config.PROCESSED_FOLDER, f"clips_{video['parent_video_id']}", filename) if video.get('parent_video_id') else None
    
    if os.path.exists(processed_path):
        return processed_path
    if clip_subfolder_path and os.path.exists(clip_subfolder_path):
        return clip_subfolder_path
    return upload_path

def handle_download_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Handle video download and conversion job."""
    logger.info(f"Processing download job: {job['id']}")
    input_data = job.get('input_data', {})
    url = input_data.get('url')
    resolution = input_data.get('resolution', '720')
    project_id = job.get('project_id')
    
    # Ensure title is not None
    title = input_data.get('title') or extract_title(url)
    
    if not url or not project_id:
        raise ValueError("URL and project_id are required")
    
    # Generate unique filenames
    base_id = str(uuid.uuid4())
    raw_filename = f"raw_{base_id}.mp4"
    processed_filename = f"{base_id}.mp4"
    raw_path = os.path.join(Config.UPLOAD_FOLDER, raw_filename)
    processed_path = os.path.join(Config.UPLOAD_FOLDER, processed_filename)
    
    update_job_progress(job['id'], 10, f"Downloading {resolution}p format...")
    download_video(url, raw_path, job['id'], resolution=resolution)
    
    update_job_progress(job['id'], 60, "Converting to vertical format...")
    convert_to_tiktok_aspect(raw_path, processed_path, job['id'])
    
    # Clean up raw file 
    if os.path.exists(raw_path):
        os.remove(raw_path)

    update_job_progress(job['id'], 95, "Finalizing...")
    size_bytes = os.path.getsize(processed_path) if os.path.exists(processed_path) else None
    
    video = Video.create(
        project_id=project_id,
        title=title,
        filename=processed_filename,
        source_url=url,
        size_bytes=size_bytes
    )
    
    return {'video_id': video['id'], 'filename': processed_filename}

def handle_upload_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Handle upload and conversion job."""
    logger.info(f"Processing upload job: {job['id']}")
    input_data = job.get('input_data', {})
    temp_filename = input_data.get('filename')
    title = input_data.get('title') or 'Uploaded Video'
    project_id = job.get('project_id')
    
    if not temp_filename or not project_id:
        raise ValueError("Filename and project_id required")
    
    temp_path = os.path.join(Config.UPLOAD_FOLDER, temp_filename)
    final_id = str(uuid.uuid4())
    final_filename = f"{final_id}.mp4"
    final_path = os.path.join(Config.UPLOAD_FOLDER, final_filename)
    
    update_job_progress(job['id'], 30, "Importing video safely...")
    final_path = safe_import_video(temp_path, final_path, job['id'])
    final_filename = os.path.basename(final_path)
    
    # Remove original temp file
    if os.path.exists(temp_path) and os.path.abspath(temp_path) != os.path.abspath(final_path):
        os.remove(temp_path)
        
    size_bytes = os.path.getsize(final_path) if os.path.exists(final_path) else None
    video = Video.create(
        project_id=project_id,
        title=title,
        filename=final_filename,
        size_bytes=size_bytes
    )
    
    return {'video_id': video['id'], 'filename': final_filename}


def handle_caption_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle caption generation job.
    
    Input data:
        - model_size: Whisper model size (tiny, base, small, medium, large)
        - word_level: Boolean for word-level timestamps
    
    Output data:
        - caption_id: Created caption ID
        - filename: Caption filename
    """
    logger.info(f"Processing caption job: {job['id']}")
    
    input_data = job.get('input_data', {})
    video_id = job.get('video_id')
    model_size = input_data.get('model_size', 'tiny')
    word_level = input_data.get('word_level', False)
    
    if not video_id:
        raise ValueError("video_id is required for caption job")
    
    video = Video.get_by_id(video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    video_path = get_video_path(video)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    update_job_progress(job['id'], 10, "Loading Whisper model...")
    
    # Get Whisper model
    model = get_whisper_model(model_size)
    
    update_job_progress(job['id'], 20, "Transcribing audio...")
    
    # Transcribe
    segments, _ = model.transcribe(video_path, word_timestamps=word_level)
    segments_list = list(segments)
    
    update_job_progress(job['id'], 80, "Writing caption file...")
    
    # Write SRT file
    caption_filename = f"{os.path.splitext(video['filename'])[0]}.srt"
    caption_path = os.path.join(Config.CAPTIONS_FOLDER, caption_filename)
    
    write_srt(segments_list, caption_path, word_level)
    
    # Create caption record
    caption = Caption.create(
        video_id=video_id,
        filename=caption_filename,
        language='en',
        format='srt'
    )
    
    logger.info(f"Caption job completed: {caption['id']}")
    
    return {
        'caption_id': caption['id'],
        'filename': caption_filename
    }


def handle_burn_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle caption burning job.
    
    Input data:
        - caption_id: Caption to burn (optional, will use latest if not specified)
        - style: Caption style dict (optional)
    
    Output data:
        - video_id: Created burned video ID
        - filename: Output filename
    """
    logger.info(f"Processing burn job: {job['id']}")
    
    input_data = job.get('input_data', {})
    video_id = job.get('video_id')
    caption_id = input_data.get('caption_id')
    style = input_data.get('style')
    
    if not video_id:
        raise ValueError("video_id is required for burn job")
    
    video = Video.get_by_id(video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    video_path = get_video_path(video)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Get caption
    if caption_id:
        caption = Caption.get_by_id(caption_id)
    else:
        # Get latest caption for this video
        captions = Caption.get_by_video(video_id)
        caption = captions[0] if captions else None
    
    if not caption:
        raise ValueError(f"No caption found for video {video_id}")
    
    caption_path = os.path.join(Config.CAPTIONS_FOLDER, caption['filename'])
    if not os.path.exists(caption_path):
        raise FileNotFoundError(f"Caption file not found: {caption_path}")
    
    # Generate unique output filename to avoid browser caching
    burned_filename = f"burned_{uuid.uuid4()}_{video['filename']}"
    if not burned_filename.endswith('.mp4'):
        burned_filename = os.path.splitext(burned_filename)[0] + '.mp4'
    output_path = os.path.join(Config.PROCESSED_FOLDER, burned_filename)
    
    update_job_progress(job['id'], 10, "Burning captions...")
    
    # Burn captions
    burn_captions(video_path, caption_path, output_path, job['id'], style)
    
    update_job_progress(job['id'], 90, "Creating database entry...")
    
    # Get file size
    size_bytes = os.path.getsize(output_path) if os.path.exists(output_path) else None
    
    # Create new video record for burned version
    burned_video = Video.create(
        project_id=video['project_id'],
        title=f"{video['title']} (Captioned)",
        filename=burned_filename,
        parent_video_id=video_id,
        size_bytes=size_bytes,
        is_clip=video.get('is_clip', 0)
    )
    
    logger.info(f"Burn job completed: {burned_video['id']}")
    
    return {
        'video_id': burned_video['id'],
        'filename': burned_filename
    }


def handle_split_scenes_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle scene-based video splitting job.
    
    Input data:
        - min_scene_len: Minimum scene length in seconds
        - threshold: Scene detection threshold
    
    Output data:
        - video_ids: List of created clip video IDs
        - count: Number of clips created
    """
    logger.info(f"Processing split scenes job: {job['id']}")
    
    input_data = job.get('input_data', {})
    video_id = job.get('video_id')
    min_scene_len = input_data.get('min_scene_len', 2.0)
    threshold = input_data.get('threshold', 3.0)
    
    if not video_id:
        raise ValueError("video_id is required for split job")
    
    video = Video.get_by_id(video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    video_path = get_video_path(video)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Create output directory
    output_dir = Config.PROCESSED_FOLDER
    os.makedirs(output_dir, exist_ok=True)
    
    update_job_progress(job['id'], 10, "Detecting scenes...")
    
    # Split video
    status_key = f"split_{job['id']}"
    clips_data = split_scenes(video_path, output_dir, job['id'], min_scene_len, threshold)
    
    update_job_progress(job['id'], 80, "Creating database entries...")
    
    # Create video records for clips
    video_ids = []
    for data in clips_data:
        clip_filename = data['filename']
        clip_path = os.path.join(output_dir, clip_filename)
        size_bytes = os.path.getsize(clip_path) if os.path.exists(clip_path) else None
        
        clip_video = Video.create(
            project_id=video['project_id'],
            title=data['title'],
            filename=clip_filename,
            parent_video_id=video_id,
            is_clip=1,
            size_bytes=size_bytes
        )
        video_ids.append(clip_video['id'])
    
    logger.info(f"Split completed: {len(video_ids)} clips")
    return {'video_ids': video_ids, 'count': len(video_ids)}

def handle_split_fixed_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Handle fixed interval video splitting job."""
    logger.info(f"Processing split fixed job: {job['id']}")
    input_data = job.get('input_data', {})
    video_id = job.get('video_id')
    interval = input_data.get('interval', 30)
    
    if not video_id:
        raise ValueError("video_id required")
    
    video = Video.get_by_id(video_id)
    video_path = get_video_path(video)
    output_dir = Config.PROCESSED_FOLDER
    os.makedirs(output_dir, exist_ok=True)
    
    update_job_progress(job['id'], 10, "Splitting video...")
    clips_data = split_fixed(video_path, output_dir, job['id'], interval)
    
    update_job_progress(job['id'], 80, "Creating database entries...")
    video_ids = []
    for data in clips_data:
        clip_filename = data['filename']
        clip_path = os.path.join(output_dir, clip_filename)
        size_bytes = os.path.getsize(clip_path) if os.path.exists(clip_path) else None
        
        clip_video = Video.create(
            project_id=video['project_id'],
            title=data['title'],
            filename=clip_filename,
            parent_video_id=video_id,
            is_clip=1,
            size_bytes=size_bytes
        )
        video_ids.append(clip_video['id'])
    
    return {'video_ids': video_ids, 'count': len(video_ids)}


def handle_trim_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle video trimming job.
    
    Input data:
        - start_time: Start time in seconds
        - end_time: End time in seconds
        - title: Title for trimmed video (optional)
    
    Output data:
        - video_id: Created trimmed video ID
        - filename: Output filename
    """
    logger.info(f"Processing trim job: {job['id']}")
    
    input_data = job.get('input_data', {})
    video_id = job.get('video_id')
    start_time = input_data.get('start_time')
    end_time = input_data.get('end_time')
    title = input_data.get('title', 'Trimmed Video')
    
    if not video_id or start_time is None or end_time is None:
        raise ValueError("video_id, start_time, and end_time are required for trim job")
    
    video = Video.get_by_id(video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    video_path = get_video_path(video)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # Generate output filename
    trim_id = str(uuid.uuid4())
    trimmed_filename = f"trim_{trim_id}.mp4"
    output_path = os.path.join(Config.PROCESSED_FOLDER, trimmed_filename)
    
    update_job_progress(job['id'], 10, "Trimming video...")
    
    # Trim video
    trim_video(video_path, output_path, start_time, end_time, job['id'])
    
    update_job_progress(job['id'], 90, "Creating database entry...")
    
    # Get file size
    size_bytes = os.path.getsize(output_path) if os.path.exists(output_path) else None
    
    # Create video record for trimmed version
    trimmed_video = Video.create(
        project_id=video['project_id'],
        title=title,
        filename=trimmed_filename,
        parent_video_id=video_id,
        is_clip=1,
        size_bytes=size_bytes
    )
    
    logger.info(f"Trim job completed: {trimmed_video['id']}")
    
    return {
        'video_id': trimmed_video['id'],
        'filename': trimmed_filename
    }


def handle_make_vertical_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Handle vertical video conversion."""
    video_id = job.get('video_id')
    if not video_id: raise ValueError("video_id required")
    
    video = Video.get_by_id(video_id)
    video_path = get_video_path(video)
    
    output_filename = f"vertical_{video['filename']}"
    output_path = os.path.join(Config.PROCESSED_FOLDER, output_filename)
    
    update_job_progress(job['id'], 20, "Detecting dimensions...")
    
    # FFmpeg command to force 9:16 aspect ratio (1080x1920)
    # Uses crop if landscape, or padding if thin
    vf = "scale=w=1080:h=1920:force_original_aspect_ratio=increase,crop=1080:1920"
    
    cmd = [
        'ffmpeg', '-i', video_path,
        '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
        '-crf', '23', '-c:a', 'copy', '-y', output_path
    ]
    
    update_job_progress(job['id'], 40, "Converting to vertical...")
    import subprocess
    subprocess.run(cmd, check=True)
    
    vertical_video = Video.create(
        project_id=video['project_id'],
        title=f"Vertical - {video['title']}",
        filename=output_filename,
        parent_video_id=video_id,
        is_clip=1,
        size_bytes=os.path.getsize(output_path)
    )
    
    return {'video_id': vertical_video['id'], 'filename': output_filename}


def handle_browser_import_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Handle importing a file already on disk (from browser download)."""
    logger.info(f"Processing browser import job: {job['id']}")
    input_data = job.get('input_data', {})
    temp_path = input_data.get('temp_path')
    original_name = input_data.get('original_name')
    project_id = job.get('project_id')
    
    if not temp_path or not project_id:
        raise ValueError("temp_path and project_id are required")
        
    if not os.path.exists(temp_path):
        raise FileNotFoundError(f"Source file not found: {temp_path}")
        
    # Generate final filenames
    final_id = str(uuid.uuid4())
    final_filename = f"{final_id}.mp4"
    final_path = os.path.join(Config.UPLOAD_FOLDER, final_filename)
    
    update_job_progress(job['id'], 20, "Normalizing video format...")
    
    # Use convert_to_tiktok_aspect for consistency with other imports
    # or just use a direct copy if it's already compatible.
    # To be "perfect", we'll use convert_to_tiktok_aspect to ensure vertical 9:16
    # as requested by the app's overall design for viral content.
    try:
        final_path = safe_import_video(temp_path, final_path, job['id'])
        final_filename = os.path.basename(final_path)
    except Exception as e:
        logger.error(f"Import failed, trying fallback move: {e}")
        import shutil
        shutil.move(temp_path, final_path.replace('.mp4', os.path.splitext(original_name)[1]))
        final_filename = final_filename.replace('.mp4', os.path.splitext(original_name)[1])
    
    # Cleanup temp file if it still exists (convert_to_tiktok_aspect doesn't delete input)
    if os.path.exists(temp_path):
        try: os.remove(temp_path)
        except: pass
        
    size_bytes = os.path.getsize(final_path) if os.path.exists(final_path) else None
    video = Video.create(
        project_id=project_id,
        title=original_name,
        filename=final_filename,
        size_bytes=size_bytes
    )
    
    return {'video_id': video['id'], 'filename': final_filename}

# Dictionary of all job handlers
JOB_HANDLERS = {
    'download': handle_download_job,
    'upload': handle_upload_job,
    'caption': handle_caption_job,
    'burn': handle_burn_job,
    'split_scenes': handle_split_scenes_job,
    'split_fixed': handle_split_fixed_job,
    'trim': handle_trim_job,
    'make_vertical': handle_make_vertical_job,
    'browser_import': handle_browser_import_job
}
