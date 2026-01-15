import os
import re
import logging
import shutil
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, Response, current_app, session
from werkzeug.utils import secure_filename

from config import Config
from utils.helpers import (
    is_valid_url, 
    sanitize_filename, 
    ensure_project_dirs
)
from database.models import Project, Video, Job, Caption, User
from task_queue.job_queue import get_job_queue
from utils.auth import login_required

api_bp = Blueprint('api', __name__)
logger = logging.getLogger(__name__)

@api_bp.before_request
@login_required
def before_request():
    pass

# --- Project CRUD ---

@api_bp.route('/projects', methods=['GET', 'POST'])
def projects():
    user_id = session.get('user_id')
    if request.method == 'GET':
        return jsonify(Project.get_all(user_id=user_id))
    
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Project name is required'}), 400

    project = Project.create(name=name, user_id=user_id, description=data.get('description'))
    # Ensure physical directories exist for this project
    ensure_project_dirs(project['id'])
    return jsonify(project), 201

@api_bp.route('/projects/<project_id>', methods=['GET', 'PUT', 'DELETE'])
def project_detail(project_id):
    user_id = session.get('user_id')
    project = Project.get_by_id(project_id)
    if not project or project.get('user_id') != user_id:
        return jsonify({'error': 'Project not found'}), 404

    if request.method == 'GET':
        return jsonify(project)
    
    if request.method == 'PUT':
        data = request.get_json() or {}
        updated = Project.update(project_id, **data)
        return jsonify(updated)

    # DELETE: Soft delete project
    Project.delete(project_id)
    return jsonify({'status': 'deleted', 'id': project_id})

# --- Video CRUD ---

@api_bp.route('/projects/<project_id>/videos', methods=['GET'])
def project_videos(project_id):
    project = Project.get_by_id(project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    videos = Video.get_by_project(project_id)
    # Add captions info to each video
    for v in videos:
        v['captions'] = Caption.get_by_video(v['id'])
    
    return jsonify(videos)

@api_bp.route('/projects/<project_id>/videos/bulk-delete', methods=['POST'])
def bulk_delete_videos(project_id):
    data = request.get_json() or {}
    video_ids = data.get('video_ids', [])
    if not video_ids:
        return jsonify({'error': 'No video IDs provided'}), 400
    Video.delete_multiple(video_ids)
    return jsonify({'status': 'deleted', 'count': len(video_ids)})

@api_bp.route('/projects/<project_id>/videos/<video_id>', methods=['GET', 'PUT', 'DELETE'])
def project_video_detail(project_id, video_id):
    video = Video.get_by_id(video_id)
    if not video or video['project_id'] != project_id:
        return jsonify({'error': 'Video not found'}), 404

    if request.method == 'GET':
        video['captions'] = Caption.get_by_video(video_id)
        return jsonify(video)
    
    if request.method == 'PUT':
        data = request.get_json() or {}
        updated = Video.update(video_id, **data)
        return jsonify(updated)

    # DELETE: Soft delete video
    Video.delete(video_id)
    return jsonify({'status': 'deleted', 'id': video_id})

# --- Job Submission (Tasks) ---

@api_bp.route('/download', methods=['POST'])
def download():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    project_id = data.get('project_id')
    
    if not url or not project_id or not is_valid_url(url):
        return jsonify({'error': 'Invalid URL or project ID'}), 400
    
    # Load global proxy if enabled
    proxy = None
    try:
        import json
        config_path = os.path.join(os.getcwd(), 'admin_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                if config.get('proxy_enabled') and config.get('proxy'):
                    proxy = config['proxy'].strip()
    except: pass

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='download',
        project_id=project_id,
        input_data={
            'url': url, 
            'title': data.get('title'),
            'resolution': data.get('resolution', '720'),
            'proxy': proxy
        },
        priority=data.get('priority', 0)
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    project_id = request.form.get('project_id')
    
    if file.filename == '' or not project_id:
        return jsonify({'error': 'No selected file or project ID'}), 400

    filename = secure_filename(file.filename)
    # Give it a unique name to avoid collisions
    import uuid
    unique_filename = f"{uuid.uuid4()}_{filename}"
    save_path = os.path.join(Config.UPLOAD_FOLDER, unique_filename)
    file.save(save_path)
    
    size_bytes = os.path.getsize(save_path)
    
    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='upload',
        project_id=project_id,
        input_data={
            'filename': unique_filename, 
            'title': os.path.splitext(filename)[0],
            'size_bytes': size_bytes
        }
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/caption', methods=['POST'])
def generate_caption(project_id, video_id):
    data = request.get_json(force=True, silent=True) or {}
    level = data.get('level', 'sentence')
    model_size = data.get('model', 'tiny')
    
    video = Video.get_by_id(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='caption',
        project_id=project_id,
        video_id=video_id,
        input_data={
            'model_size': model_size,
            'word_level': (level == 'word')
        }
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/convert-aspect', methods=['POST'])
def convert_aspect(project_id, video_id):
    """Convert video to different aspect ratios with multiple options"""
    data = request.get_json(force=True, silent=True) or {}
    aspect = data.get('aspect', '9:16')  # Default to vertical
    
    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='convert_aspect',
        project_id=project_id,
        video_id=video_id,
        input_data={'aspect': aspect}
    )
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/burn', methods=['POST'])
def burn_caption(project_id, video_id):
    data = request.get_json(force=True, silent=True) or {}
    caption_id = data.get('caption_id')
    style = data.get('style')

    video = Video.get_by_id(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='burn',
        project_id=project_id,
        video_id=video_id,
        input_data={
            'caption_id': caption_id,
            'style': style
        }
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/split-scenes', methods=['POST'])
def split_scenes_route(project_id, video_id):
    data = request.get_json(force=True, silent=True) or {}
    min_scene_len = data.get('min_scene_len', 2.0)
    threshold = data.get('threshold', 3.0)

    video = Video.get_by_id(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='split_scenes',
        project_id=project_id,
        video_id=video_id,
        input_data={
            'min_scene_len': min_scene_len,
            'threshold': threshold
        }
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/split-fixed', methods=['POST'])
def split_fixed_route(project_id, video_id):
    data = request.get_json(force=True, silent=True) or {}
    interval = data.get('interval', 30)

    video = Video.get_by_id(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='split_fixed',
        project_id=project_id,
        video_id=video_id,
        input_data={'interval': interval}
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/projects/<project_id>/videos/<video_id>/trim', methods=['POST'])
def trim_video_route(project_id, video_id):
    data = request.get_json(force=True, silent=True) or {}
    start = data.get('start_time', 0)
    end = data.get('end_time', 10)
    title = data.get('title', 'Clip')

    video = Video.get_by_id(video_id)
    if not video:
        return jsonify({'error': 'Video not found'}), 404

    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        job_type='trim',
        project_id=project_id,
        video_id=video_id,
        input_data={
            'start_time': start,
            'end_time': end,
            'title': title
        }
    )
    
    return jsonify({'id': job_id, 'status': 'pending'})

# --- Status & Meta Endpoints ---

@api_bp.route('/status/<job_id>')
def get_status(job_id):
    """Get status of a job."""
    job = Job.get_by_id(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(job)

@api_bp.route('/queue/stats')
def queue_stats():
    """Get job queue and worker statistics."""
    job_queue = current_app.config['JOB_QUEUE']
    return jsonify(job_queue.get_stats())

@api_bp.route('/jobs', methods=['GET'])
def get_jobs():
    """Get recent jobs, optionally filter by project."""
    user_id = session.get('user_id')
    user_role = session.get('user_role')
    project_id = request.args.get('project_id')
    
    if project_id:
        project = Project.get_by_id(project_id)
        if not project or (user_role != 'admin' and project.get('user_id') != user_id):
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(Job.get_by_project(project_id))
    
    status = request.args.get('status')
    if status and user_role == 'admin':
        return jsonify(Job.get_by_status(status))
    
    # Return last 50 jobs for the user
    from database.schema import get_db_manager
    db = get_db_manager()
    
    if user_role == 'admin':
        rows = db.execute_query("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50")
    else:
        # Filter jobs by user's projects
        rows = db.execute_query("""
            SELECT j.* FROM jobs j 
            JOIN projects p ON j.project_id = p.id 
            WHERE p.user_id = ? 
            ORDER BY j.created_at DESC LIMIT 50
        """, (user_id,))

    jobs = [dict(r) for r in rows]
    import json
    for j in jobs:
        if j.get('input_data'): j['input_data'] = json.loads(j['input_data'])
        if j.get('output_data'): j['output_data'] = json.loads(j['output_data'])
    return jsonify(jobs)

@api_bp.route('/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    job_queue = current_app.config['JOB_QUEUE']
    success = job_queue.cancel_job(job_id)
    return jsonify({'success': success})

@api_bp.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    success = Job.delete(job_id)
    return jsonify({'success': success})

@api_bp.route('/jobs/<job_id>/retry', methods=['POST'])
def retry_job(job_id):
    success = Job.retry(job_id)
    if success:
        # If successfully marked as pending, add to queue
        job_queue = current_app.config['JOB_QUEUE']
        job = Job.get_by_id(job_id)
        job_queue.queue.put((-job['priority'], job_id))
    return jsonify({'success': success})

# --- Serving Files ---

@api_bp.route('/caption/<project_id>/<filename>')
def serve_caption(project_id, filename):
    filename = secure_filename(filename)
    file_path = os.path.join(Config.CAPTIONS_FOLDER, filename)
    return send_file(file_path, as_attachment=True)

@api_bp.route('/video/<project_id>/<filename>')
def serve_video(project_id, filename):
    filename = secure_filename(filename)
    
    # Check possible locations
    paths = [
        os.path.join(Config.PROCESSED_FOLDER, filename),
        os.path.join(Config.UPLOAD_FOLDER, filename),
    ]
    
    # Also check any clips subdirectory in processed
    found_path = None
    for p in paths:
        if os.path.exists(p):
            found_path = p
            break
            
    if not found_path:
        # Detailed search in subdirectories if not found in root
        for root, dirs, files in os.walk(Config.PROCESSED_FOLDER):
            if filename in files:
                found_path = os.path.join(root, filename)
                break
                
    if not found_path:
        return jsonify({'error': 'Video file not found'}), 404
        
    import mimetypes
    mime_type, _ = mimetypes.guess_type(found_path)
    if not mime_type or not mime_type.startswith('video/'):
        mime_type = 'video/mp4'
        
    return send_file(found_path, mimetype=mime_type, as_attachment=False, conditional=True)

# --- Storage Management ---

def get_dir_size(path):
    total = 0
    if not os.path.exists(path):
        return 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_dir_size(entry.path)
    except Exception as e:
        logger.error(f"Error calculating dir size for {path}: {str(e)}")
    return total

@api_bp.route('/storage/stats')
def storage_stats():
    import shutil
    total, used, free = shutil.disk_usage("/")
    
    stats = {
        'disk': {
            'total': total,
            'used': used,
            'free': free,
            'percent': (used / total) * 100
        },
        'app': {
            'uploads': get_dir_size(Config.UPLOAD_FOLDER),
            'processed': get_dir_size(Config.PROCESSED_FOLDER),
            'captions': get_dir_size(Config.CAPTIONS_FOLDER)
        }
    }
    return jsonify(stats)

@api_bp.route('/storage/files')
def storage_files():
    files = []
    # Use absolute paths to ensure reliability
    dirs_to_check = [
        ('uploads', os.path.abspath(Config.UPLOAD_FOLDER)),
        ('processed', os.path.abspath(Config.PROCESSED_FOLDER)),
        ('captions', os.path.abspath(Config.CAPTIONS_FOLDER))
    ]
    for dir_name, dir_path in dirs_to_check:
        if not os.path.exists(dir_path):
            continue
        for root, dirs, filenames in os.walk(dir_path):
            for f in filenames:
                p = os.path.join(root, f)
                try:
                    stat = os.stat(p)
                    files.append({
                        'name': f,
                        'type': dir_name,
                        'size': stat.st_size,
                        'path': p,
                        'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat()
                    })
                except: continue
    return jsonify(sorted(files, key=lambda x: x['created_at'], reverse=True))

@api_bp.route('/browser/staged')
def list_staged_files():
    """List files in the storage area that could be imported (staged and general uploads)."""
    scan_dirs = [
        ('Staged', os.path.join(Config.UPLOAD_FOLDER, 'browser_staged')),
        ('Uploads', Config.UPLOAD_FOLDER)
    ]
    
    files = []
    seen_paths = set()
    
    for label, dir_path in scan_dirs:
        if not os.path.exists(dir_path):
            continue
            
        try:
            for f in os.listdir(dir_path):
                p = os.path.join(dir_path, f)
                abs_p = os.path.abspath(p)
                
                if os.path.isfile(p) and abs_p not in seen_paths:
                    # Only show video files
                    if f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv')):
                        # Skip files that look like they belong to the DB or are already processed
                        if f.startswith('raw_'): continue
                        
                        stat = os.stat(p)
                        files.append({
                            'name': f if label == 'Uploads' else f"[Staged] {f}",
                            'display_name': f,
                            'path': abs_p,
                            'size': stat.st_size,
                            'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            'source': label
                        })
                        seen_paths.add(abs_p)
        except Exception as e:
            logger.error(f"Error scanning {dir_path}: {e}")
            
    return jsonify(sorted(files, key=lambda x: x['created_at'], reverse=True))

@api_bp.route('/import/server-file', methods=['POST'])
def import_server_file():
    """Trigger a job to import a file already on disk."""
    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get('path')
    project_id = data.get('project_id')
    
    if not file_path or not project_id:
        return jsonify({'error': 'Path and project_id required'}), 400
        
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found on server'}), 404
        
    # Get original name from path (it's usually staged as stage_id_name)
    original_name = os.path.basename(file_path)
    if original_name.startswith('stage_'):
        # Try to strip stage_uuid_
        parts = original_name.split('_', 2)
        if len(parts) > 2:
            original_name = parts[2]
            
    job_queue = current_app.config['JOB_QUEUE']
    job_id = job_queue.submit_job(
        'browser_import',
        project_id=project_id,
        input_data={
            'temp_path': file_path,
            'original_name': original_name
        }
    )
    return jsonify({'id': job_id, 'status': 'pending'})

@api_bp.route('/users', methods=['GET', 'POST'])
def manage_users():
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
        
    from database.schema import get_db_manager
    if request.method == 'GET':
        db = get_db_manager()
        users = db.execute_query("SELECT id, username, passcode, role FROM users WHERE is_deleted = 0")
        return jsonify([dict(u) for u in users])
    
    data = request.get_json(force=True, silent=True) or {}
    username = data.get('username')
    passcode = data.get('passcode')
    role = data.get('role', 'user')
    
    if not username or not passcode:
        return jsonify({'error': 'Username and passcode required'}), 400
        
    user = User.create(username, passcode, role)
    if not user:
        return jsonify({'error': 'Username or passcode already exists'}), 400
        
    return jsonify(user)

@api_bp.route('/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    from database.schema import get_db_manager
    db = get_db_manager()
    db.execute_write("UPDATE users SET is_deleted = 1 WHERE id = ?", (user_id,))
    return jsonify({'success': True})

@api_bp.route('/storage/cleanup', methods=['POST'])
def storage_cleanup():
    """Delete all files in app directories - Admin only"""
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    
    dirs = [Config.UPLOAD_FOLDER, Config.PROCESSED_FOLDER, Config.CAPTIONS_FOLDER]
    count = 0
    for d in dirs:
        if not os.path.exists(d): continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    count += 1
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except: continue
    return jsonify({'success': True, 'count': count})

@api_bp.route('/storage/bulk-delete', methods=['POST'])
def storage_bulk_delete():
    if session.get('user_role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    
    data = request.get_json(force=True, silent=True) or {}
    paths = data.get('paths', [])
    count = 0
    for p in paths:
        abs_p = os.path.abspath(p)
        # Check safety
        allowed = [os.path.abspath(Config.UPLOAD_FOLDER), os.path.abspath(Config.PROCESSED_FOLDER), os.path.abspath(Config.CAPTIONS_FOLDER)]
        if any(abs_p.startswith(d) for d in allowed) and os.path.exists(abs_p):
            try:
                os.remove(abs_p)
                count += 1
            except: continue
    return jsonify({'success': True, 'count': count})

@api_bp.route('/storage/files/delete', methods=['POST'])
def delete_file():
    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get('path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Safety check: only allow files inside our app dirs
    allowed_dirs = [
        os.path.abspath(Config.UPLOAD_FOLDER),
        os.path.abspath(Config.PROCESSED_FOLDER),
        os.path.abspath(Config.CAPTIONS_FOLDER)
    ]
    abs_path = os.path.abspath(file_path)
    if not any(abs_path.startswith(d) for d in allowed_dirs):
        return jsonify({'error': 'Permission denied'}), 403
        
    try:
        os.remove(abs_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stream/<project_id>/<filename>')
def stream_video(project_id, filename):
    # Prevent directory traversal
    filename = os.path.basename(filename)
    
    # Check possible locations
    paths = [
        os.path.join(Config.PROCESSED_FOLDER, filename),
        os.path.join(Config.UPLOAD_FOLDER, filename),
    ]
    
    found_path = None
    for p in paths:
        if os.path.exists(p):
            found_path = p
            break
            
    if not found_path:
        # Deep search in processed folder (for clips)
        for root, dirs, files in os.walk(Config.PROCESSED_FOLDER):
            if filename in files:
                found_path = os.path.join(root, filename)
                break
                
    if not found_path:
        logger.warning(f"Stream: File not found: {filename}")
        return jsonify({'error': 'Video file not found'}), 404

    import mimetypes
    mime_type, _ = mimetypes.guess_type(found_path)
    if filename.lower().endswith('.mp4'):
        mime_type = 'video/mp4'
    elif not mime_type or not mime_type.startswith('video/'):
        mime_type = 'video/mp4'

    size = os.path.getsize(found_path)
    range_header = request.headers.get('Range', None)

    def _add_common_headers(res):
        res.headers.add('Content-Disposition', 'inline')
        res.headers.add('Accept-Ranges', 'bytes')
        res.headers.add('X-Content-Type-Options', 'nosniff')
        res.headers.add('Cache-Control', 'no-cache') # Don't cache during stream to avoid mixups
        return res

    if not range_header:
        # Full file request
        logger.info(f"Streaming full video (200): {found_path}")
        response = send_file(found_path, mimetype=mime_type, as_attachment=False)
        return _add_common_headers(response)

    # Range request (Seeking)
    try:
        m = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if not m:
            return send_file(found_path, mimetype=mime_type, as_attachment=False)

        byte1, byte2 = m.groups()
        byte1 = int(byte1)
        byte2 = int(byte2) if byte2 else size - 1

        if byte1 >= size:
            return Response("Range Not Satisfiable", status=416)

        length = byte2 - byte1 + 1
        
        # Read the requested chunk
        with open(found_path, 'rb') as f:
            f.seek(byte1)
            data = f.read(length)

        rv = Response(data, 206, mimetype=mime_type, direct_passthrough=True)
        rv.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{size}')
        rv = _add_common_headers(rv)
        rv.headers.add('Content-Length', str(length))
        logger.debug(f"Streaming range {byte1}-{byte2} for {filename}")
        return rv
    except Exception as e:
        logger.error(f"Error in range streaming for {filename}: {e}")
        return send_file(found_path, mimetype=mime_type, as_attachment=False)
