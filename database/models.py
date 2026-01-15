"""
Database models with full CRUD operations.
Provides clean, maintainable data access layer.
"""

import os
import uuid
import json
import logging
import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime
from database.schema import get_db_manager

logger = logging.getLogger(__name__)


class BaseModel:
    """Base model with common CRUD operations."""
    
    table_name = None
    
    @classmethod
    def _row_to_dict(cls, row) -> Dict[str, Any]:
        """Convert SQLite row to dictionary."""
        if row is None:
            return None
        return dict(row)
    
    @classmethod
    def _rows_to_list(cls, rows) -> List[Dict[str, Any]]:
        """Convert SQLite rows to list of dictionaries."""
        return [cls._row_to_dict(row) for row in rows]


class User(BaseModel):
    """User model for multi-passcode access."""
    
    table_name = 'users'
    
    @classmethod
    def create(cls, username: str, passcode: str, role: str = 'user') -> Dict[str, Any]:
        """Create a new user/passcode."""
        user_id = str(uuid.uuid4())
        db = get_db_manager()
        try:
            db.execute_write(
                "INSERT INTO users (id, username, passcode, role) VALUES (?, ?, ?, ?)",
                (user_id, username, passcode, role)
            )
            return cls.get_by_id(user_id)
        except sqlite3.IntegrityError:
            return None

    @classmethod
    def get_by_id(cls, user_id: str) -> Optional[Dict[str, Any]]:
        db = get_db_manager()
        row = db.execute_query("SELECT * FROM users WHERE id = ? AND is_deleted = 0", (user_id,), fetch_one=True)
        return cls._row_to_dict(row)

    @classmethod
    def get_by_passcode(cls, passcode: str) -> Optional[Dict[str, Any]]:
        db = get_db_manager()
        row = db.execute_query("SELECT * FROM users WHERE passcode = ? AND is_deleted = 0", (passcode,), fetch_one=True)
        return cls._row_to_dict(row)

    @classmethod
    def ensure_admin(cls):
        """Setup default admin if none exists, reading from admin_config.json if available."""
        db = get_db_manager()
        
        # Default fallback
        passcode = 'admin'
        
        # Try to read from JSON config
        import json
        config_path = os.path.join(os.getcwd(), 'admin_config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    passcode = config.get('admin_passcode', passcode)
                logger.info("Loaded admin passcode from admin_config.json")
            except Exception as e:
                logger.error(f"Error reading admin_config.json: {e}")

        row = db.execute_query("SELECT * FROM users WHERE username = 'admin'", fetch_one=True)
        if not row:
            cls.create('admin', passcode, 'admin')
            logger.info(f"Created admin user with passcode from config")
        else:
            # Sync passcode if it changed in JSON
            if row['passcode'] != passcode:
                db.execute_write("UPDATE users SET passcode = ? WHERE username = 'admin'", (passcode,))
                logger.info("Updated admin passcode in database to match config")


class Project(BaseModel):
    """Project model with CRUD operations."""
    
    table_name = 'projects'
    
    @classmethod
    def create(cls, name: str, user_id: str = None, description: str = None) -> Dict[str, Any]:
        """Create a new project."""
        project_id = str(uuid.uuid4())
        db = get_db_manager()
        
        db.execute_write(
            """INSERT INTO projects (id, user_id, name, description) 
               VALUES (?, ?, ?, ?)""",
            (project_id, user_id, name, description)
        )
        
        logger.info(f"Created project: {project_id} - {name}")
        return cls.get_by_id(project_id)
    
    @classmethod
    def get_by_id(cls, project_id: str) -> Optional[Dict[str, Any]]:
        """Get project by ID."""
        db = get_db_manager()
        row = db.execute_query(
            """SELECT * FROM projects WHERE id = ? AND is_deleted = 0""",
            (project_id,),
            fetch_one=True
        )
        return cls._row_to_dict(row)
    
    @classmethod
    def get_all(cls, user_id: str = None, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all projects, optionally filtered by user."""
        db = get_db_manager()
        query = "SELECT * FROM projects WHERE 1=1"
        params = []
        if not include_deleted:
            query += " AND is_deleted = 0"
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        query += " ORDER BY created_at DESC"
        
        rows = db.execute_query(query, tuple(params))
        return cls._rows_to_list(rows)
    
    @classmethod
    def update(cls, project_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update project fields."""
        allowed_fields = ['name', 'description']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return cls.get_by_id(project_id)
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [project_id]
        
        db = get_db_manager()
        db.execute_write(
            f"UPDATE projects SET {set_clause} WHERE id = ?",
            tuple(values)
        )
        
        logger.info(f"Updated project: {project_id}")
        return cls.get_by_id(project_id)
    
    @classmethod
    def delete(cls, project_id: str, hard_delete: bool = False) -> bool:
        """Delete project (soft delete by default)."""
        db = get_db_manager()
        
        if hard_delete:
            # Hard delete: permanently remove from database
            db.execute_write("DELETE FROM projects WHERE id = ?", (project_id,))
            logger.info(f"Hard deleted project: {project_id}")
        else:
            # Soft delete: mark as deleted
            db.execute_write(
                "UPDATE projects SET is_deleted = 1 WHERE id = ?",
                (project_id,)
            )
            logger.info(f"Soft deleted project: {project_id}")
        
        return True
    
    @classmethod
    def restore(cls, project_id: str) -> Optional[Dict[str, Any]]:
        """Restore a soft-deleted project."""
        db = get_db_manager()
        db.execute_write(
            "UPDATE projects SET is_deleted = 0 WHERE id = ?",
            (project_id,)
        )
        logger.info(f"Restored project: {project_id}")
        return cls.get_by_id(project_id)


class Video(BaseModel):
    """Video model with CRUD operations."""
    
    table_name = 'videos'
    
    @classmethod
    def create(cls, project_id: str, title: str, filename: str, **kwargs) -> Dict[str, Any]:
        """Create a new video."""
        video_id = str(uuid.uuid4())
        db = get_db_manager()
        
        # Extract optional fields
        source_url = kwargs.get('source_url')
        duration = kwargs.get('duration')
        width = kwargs.get('width')
        height = kwargs.get('height')
        size_bytes = kwargs.get('size_bytes')
        is_clip = kwargs.get('is_clip', 0)
        parent_video_id = kwargs.get('parent_video_id')
        
        db.execute_write(
            """INSERT INTO videos 
               (id, project_id, title, filename, source_url, duration, 
                width, height, size_bytes, is_clip, parent_video_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (video_id, project_id, title, filename, source_url, duration,
             width, height, size_bytes, is_clip, parent_video_id)
        )
        
        logger.info(f"Created video: {video_id} - {title}")
        return cls.get_by_id(video_id)
    
    @classmethod
    def get_by_id(cls, video_id: str) -> Optional[Dict[str, Any]]:
        """Get video by ID."""
        db = get_db_manager()
        row = db.execute_query(
            "SELECT * FROM videos WHERE id = ? AND is_deleted = 0",
            (video_id,),
            fetch_one=True
        )
        return cls._row_to_dict(row)
    
    @classmethod
    def get_by_project(cls, project_id: str, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all videos for a project."""
        db = get_db_manager()
        query = "SELECT * FROM videos WHERE project_id = ?"
        params = [project_id]
        
        if not include_deleted:
            query += " AND is_deleted = 0"
        
        query += " ORDER BY created_at DESC"
        
        rows = db.execute_query(query, tuple(params))
        return cls._rows_to_list(rows)
    
    @classmethod
    def get_by_filename(cls, filename: str) -> Optional[Dict[str, Any]]:
        """Get video by filename."""
        db = get_db_manager()
        row = db.execute_query(
            "SELECT * FROM videos WHERE filename = ? AND is_deleted = 0",
            (filename,),
            fetch_one=True
        )
        return cls._row_to_dict(row)
    
    @classmethod
    def update(cls, video_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update video fields."""
        allowed_fields = ['title', 'filename', 'source_url', 'duration',
                         'width', 'height', 'size_bytes', 'is_clip', 'parent_video_id']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return cls.get_by_id(video_id)
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [video_id]
        
        db = get_db_manager()
        db.execute_write(
            f"UPDATE videos SET {set_clause} WHERE id = ?",
            tuple(values)
        )
        
        logger.info(f"Updated video: {video_id}")
        return cls.get_by_id(video_id)
    
    @classmethod
    def delete(cls, video_id: str, hard_delete: bool = False) -> bool:
        """Delete video (soft delete by default)."""
        db = get_db_manager()
        
        if hard_delete:
            db.execute_write("DELETE FROM videos WHERE id = ?", (video_id,))
            logger.info(f"Hard deleted video: {video_id}")
        else:
            db.execute_write(
                "UPDATE videos SET is_deleted = 1 WHERE id = ?",
                (video_id,)
            )
            logger.info(f"Soft deleted video: {video_id}")
        
        return True
    
    @classmethod
    def restore(cls, video_id: str) -> Optional[Dict[str, Any]]:
        """Restore a soft-deleted video."""
        db = get_db_manager()
        db.execute_write(
            "UPDATE videos SET is_deleted = 0 WHERE id = ?",
            (video_id,)
        )
        logger.info(f"Restored video: {video_id}")
        return cls.get_by_id(video_id)

    @classmethod
    def delete_multiple(cls, video_ids: List[str]) -> bool:
        """Soft delete multiple videos."""
        if not video_ids:
            return True
        db = get_db_manager()
        placeholders = ', '.join(['?' for _ in video_ids])
        db.execute_write(
            f"UPDATE videos SET is_deleted = 1 WHERE id IN ({placeholders})",
            tuple(video_ids)
        )
        logger.info(f"Soft deleted {len(video_ids)} videos")
        return True


class Job(BaseModel):
    """Job model with CRUD operations."""
    
    table_name = 'jobs'
    
    # Job status constants
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'
    
    # Job type constants
    TYPE_DOWNLOAD = 'download'
    TYPE_UPLOAD = 'upload'
    TYPE_CAPTION = 'caption'
    TYPE_BURN = 'burn'
    TYPE_SPLIT = 'split'
    TYPE_TRIM = 'trim'
    
    @classmethod
    def create(cls, job_type: str, project_id: str = None, video_id: str = None,
               input_data: Dict = None, priority: int = 0) -> Dict[str, Any]:
        """Create a new job."""
        job_id = str(uuid.uuid4())
        db = get_db_manager()
        
        input_json = json.dumps(input_data) if input_data else None
        
        db.execute_write(
            """INSERT INTO jobs 
               (id, type, status, priority, project_id, video_id, input_data)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, job_type, cls.STATUS_PENDING, priority,
             project_id, video_id, input_json)
        )
        
        logger.info(f"Created job: {job_id} - {job_type}")
        return cls.get_by_id(job_id)
    
    @classmethod
    def get_by_id(cls, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID."""
        db = get_db_manager()
        row = db.execute_query(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
            fetch_one=True
        )
        result = cls._row_to_dict(row)
        
        # Parse JSON fields
        if result:
            if result.get('input_data'):
                result['input_data'] = json.loads(result['input_data'])
            if result.get('output_data'):
                result['output_data'] = json.loads(result['output_data'])
        
        return result
    
    @classmethod
    def get_pending_jobs(cls, limit: int = None) -> List[Dict[str, Any]]:
        """Get pending jobs ordered by priority."""
        db = get_db_manager()
        query = """SELECT * FROM jobs WHERE status = ? 
                   ORDER BY priority DESC, created_at ASC"""
        
        if limit:
            query += f" LIMIT {limit}"
        
        rows = db.execute_query(query, (cls.STATUS_PENDING,))
        jobs = cls._rows_to_list(rows)
        
        # Parse JSON fields
        for job in jobs:
            if job.get('input_data'):
                job['input_data'] = json.loads(job['input_data'])
            if job.get('output_data'):
                job['output_data'] = json.loads(job['output_data'])
        
        return jobs
    
    @classmethod
    def get_by_status(cls, status: str) -> List[Dict[str, Any]]:
        """Get jobs by status."""
        db = get_db_manager()
        rows = db.execute_query(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC",
            (status,)
        )
        jobs = cls._rows_to_list(rows)
        
        # Parse JSON fields
        for job in jobs:
            if job.get('input_data'):
                job['input_data'] = json.loads(job['input_data'])
            if job.get('output_data'):
                job['output_data'] = json.loads(job['output_data'])
        
        return jobs
    
    @classmethod
    def get_by_project(cls, project_id: str) -> List[Dict[str, Any]]:
        """Get all jobs for a project."""
        db = get_db_manager()
        rows = db.execute_query(
            "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        )
        jobs = cls._rows_to_list(rows)
        
        # Parse JSON fields
        for job in jobs:
            if job.get('input_data'):
                job['input_data'] = json.loads(job['input_data'])
            if job.get('output_data'):
                job['output_data'] = json.loads(job['output_data'])
        
        return jobs
    
    @classmethod
    def update_status(cls, job_id: str, status: str, progress: int = None,
                      error_message: str = None, output_data: Dict = None) -> Optional[Dict[str, Any]]:
        """Update job status and related fields."""
        db = get_db_manager()
        
        updates = {'status': status}
        
        if progress is not None:
            updates['progress'] = progress
        
        if error_message:
            updates['error_message'] = error_message
        
        if output_data:
            updates['output_data'] = json.dumps(output_data)
        
        # Set timestamps based on status
        if status == cls.STATUS_RUNNING and not updates.get('started_at'):
            updates['started_at'] = datetime.utcnow().isoformat()
        elif status in [cls.STATUS_COMPLETED, cls.STATUS_FAILED, cls.STATUS_CANCELLED]:
            updates['completed_at'] = datetime.utcnow().isoformat()
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]
        
        db.execute_write(
            f"UPDATE jobs SET {set_clause} WHERE id = ?",
            tuple(values)
        )
        
        return None
    
    @classmethod
    def cancel(cls, job_id: str) -> bool:
        """Cancel a job."""
        job = cls.get_by_id(job_id)
        if not job:
            return False
        
        if job['status'] in [cls.STATUS_COMPLETED, cls.STATUS_FAILED, cls.STATUS_CANCELLED]:
            logger.warning(f"Cannot cancel job {job_id} with status {job['status']}")
            return False
        
        cls.update_status(job_id, cls.STATUS_CANCELLED)
        logger.info(f"Cancelled job: {job_id}")
        return True

    @classmethod
    def delete(cls, job_id: str) -> bool:
        """Permanently delete a job."""
        db = get_db_manager()
        db.execute_write("DELETE FROM jobs WHERE id = ?", (job_id,))
        logger.info(f"Deleted job: {job_id}")
        return True
    
    @classmethod
    def retry(cls, job_id: str) -> bool:
        """Retry a failed job."""
        job = cls.get_by_id(job_id)
        if not job:
            return False
        
        if job['retry_count'] >= job['max_retries']:
            logger.warning(f"Job {job_id} has exceeded max retries")
            return False
        
        db = get_db_manager()
        db.execute_write(
            """UPDATE jobs SET status = ?, retry_count = retry_count + 1,
               error_message = NULL WHERE id = ?""",
            (cls.STATUS_PENDING, job_id)
        )
        
        logger.info(f"Retrying job: {job_id}")
        return True
    
    @classmethod
    def delete_old_jobs(cls, days: int = 30) -> int:
        """Delete completed/failed jobs older than specified days."""
        db = get_db_manager()
        count = db.execute_write(
            """DELETE FROM jobs 
               WHERE status IN (?, ?) 
               AND datetime(completed_at) < datetime('now', '-' || ? || ' days')""",
            (cls.STATUS_COMPLETED, cls.STATUS_FAILED, days)
        )
        logger.info(f"Deleted {count} old jobs")
        return count


class Caption(BaseModel):
    """Caption model with CRUD operations."""
    
    table_name = 'captions'
    
    @classmethod
    def create(cls, video_id: str, filename: str, language: str = 'en',
               format: str = 'srt', style: Dict = None) -> Dict[str, Any]:
        """Create a new caption."""
        caption_id = str(uuid.uuid4())
        db = get_db_manager()
        
        style_json = json.dumps(style) if style else None
        
        db.execute_write(
            """INSERT INTO captions 
               (id, video_id, filename, language, format, style)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (caption_id, video_id, filename, language, format, style_json)
        )
        
        logger.info(f"Created caption: {caption_id}")
        return cls.get_by_id(caption_id)
    
    @classmethod
    def get_by_id(cls, caption_id: str) -> Optional[Dict[str, Any]]:
        """Get caption by ID."""
        db = get_db_manager()
        row = db.execute_query(
            "SELECT * FROM captions WHERE id = ? AND is_deleted = 0",
            (caption_id,),
            fetch_one=True
        )
        result = cls._row_to_dict(row)
        
        if result and result.get('style'):
            result['style'] = json.loads(result['style'])
        
        return result
    
    @classmethod
    def get_by_video(cls, video_id: str) -> List[Dict[str, Any]]:
        """Get all captions for a video."""
        db = get_db_manager()
        rows = db.execute_query(
            "SELECT * FROM captions WHERE video_id = ? AND is_deleted = 0 ORDER BY created_at DESC",
            (video_id,)
        )
        captions = cls._rows_to_list(rows)
        
        for caption in captions:
            if caption.get('style'):
                caption['style'] = json.loads(caption['style'])
        
        return captions
    
    @classmethod
    def update(cls, caption_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update caption fields."""
        allowed_fields = ['filename', 'language', 'format']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if 'style' in kwargs:
            updates['style'] = json.dumps(kwargs['style'])
        
        if not updates:
            return cls.get_by_id(caption_id)
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [caption_id]
        
        db = get_db_manager()
        db.execute_write(
            f"UPDATE captions SET {set_clause} WHERE id = ?",
            tuple(values)
        )
        
        logger.info(f"Updated caption: {caption_id}")
        return cls.get_by_id(caption_id)
    
    @classmethod
    def delete(cls, caption_id: str, hard_delete: bool = False) -> bool:
        """Delete caption (soft delete by default)."""
        db = get_db_manager()
        
        if hard_delete:
            db.execute_write("DELETE FROM captions WHERE id = ?", (caption_id,))
            logger.info(f"Hard deleted caption: {caption_id}")
        else:
            db.execute_write(
                "UPDATE captions SET is_deleted = 1 WHERE id = ?",
                (caption_id,)
            )
            logger.info(f"Soft deleted caption: {caption_id}")
        
        return True


class Setting(BaseModel):
    """Settings model for application configuration."""
    
    table_name = 'settings'
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        db = get_db_manager()
        row = db.execute_query(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
            fetch_one=True
        )
        
        if row:
            try:
                return json.loads(row['value'])
            except:
                return row['value']
        
        return default
    
    @classmethod
    def set(cls, key: str, value: Any, description: str = None) -> None:
        """Set a setting value."""
        db = get_db_manager()
        
        # Convert value to JSON string if not already string
        if not isinstance(value, str):
            value = json.dumps(value)
        
        db.execute_write(
            """INSERT OR REPLACE INTO settings (key, value, description)
               VALUES (?, ?, ?)""",
            (key, value, description)
        )
        
        logger.info(f"Set setting: {key}")
    
    @classmethod
    def delete(cls, key: str) -> bool:
        """Delete a setting."""
        db = get_db_manager()
        count = db.execute_write("DELETE FROM settings WHERE key = ?", (key,))
        return count > 0
    
    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        """Get all settings as a dictionary."""
        db = get_db_manager()
        rows = db.execute_query("SELECT key, value FROM settings")
        
        settings = {}
        for row in rows:
            try:
                settings[row['key']] = json.loads(row['value'])
            except:
                settings[row['key']] = row['value']
        
        return settings
