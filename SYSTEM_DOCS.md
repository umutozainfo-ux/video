# Professional Video Platform - System Documentation

## 🎯 Overview

This is a **professional, high-performance video content creation platform** featuring:
- **SQLite Database**: Robust data persistence with ACID guarantees
- **Job Queue System**: Concurrent processing with 4 worker threads
- **Full CRUD Operations**: Complete database management for all entities
- **Real-time Updates**: Job progress tracking and status monitoring
- **Scalable Architecture**: Designed for production use

## 🏗️ Architecture

### Database Layer
- **SQLite with WAL mode**: Write-Ahead Logging for better concurrency
- **Connection pooling**: Optimized database access
- **Soft deletes**: Data recovery capabilities
- **Foreign keys**: Referential integrity
- **Automatic timestamps**: Created/updated tracking
- **Indexes**: Optimized query performance

### Job Queue System
- **Multi-threaded workers**: 4 concurrent job processors (configurable)
- **Priority queue**: High-priority jobs processed first
- **Automatic retries**: Failed jobs retry up to 3 times
- **Job cancellation**: Cancel running or pending jobs
- **Progress tracking**: Real-time progress updates (0-100%)
- **Job history**: Track all jobs with status and error logging

### Data Models

#### Projects
```python
{
    'id': str,              # UUID
    'name': str,            # Project name
    'description': str,     # Optional description
    'created_at': datetime,
    'updated_at': datetime,
    'is_deleted': bool      # Soft delete flag
}
```

#### Videos
```python
{
    'id': str,              # UUID
    'project_id': str,      # Parent project
    'title': str,           # Video title
    'filename': str,        # File name on disk
    'source_url': str,      # Original download URL
    'duration': float,      # Duration in seconds
    'width': int,           # Video width
    'height': int,          # Video height
    'size_bytes': int,      # File size
    'is_clip': bool,        # Is this a clip/segment?
    'parent_video_id': str, # Parent video if clip
    'created_at': datetime,
    'updated_at': datetime,
    'is_deleted': bool
}
```

#### Jobs
```python
{
    'id': str,              # UUID
    'type': str,            # Job type (download, caption, burn, split, trim)
    'status': str,          # pending, running, completed, failed, cancelled
    'priority': int,        # Higher = processed first (default 0)
    'project_id': str,      # Associated project
    'video_id': str,        # Associated video
    'input_data': dict,     # Job-specific parameters
    'output_data': dict,    # Job results
    'progress': int,        # 0-100
    'error_message': str,   # Error details if failed
    'retry_count': int,     # Number of retries attempted
    'max_retries': int,     # Maximum retries allowed
    'created_at': datetime,
    'started_at': datetime,
    'completed_at': datetime,
    'updated_at': datetime
}
```

#### Captions
```python
{
    'id': str,              # UUID
    'video_id': str,        # Parent video
    'filename': str,        # Caption file name
    'language': str,        # Language code (default: 'en')
    'format': str,          # Format (srt, vtt, ass)
    'style': dict,          # Style parameters (JSON)
    'created_at': datetime,
    'updated_at': datetime,
    'is_deleted': bool
}
```

## 📂 Directory Structure

```
video/
├── database/               # Database layer
│   ├── __init__.py
│   ├── schema.py          # Database schema and connection management
│   ├── models.py          # CRUD models for all entities
│   └── migration.py       # JSON to SQLite migration tool
├── queue/                 # Job queue system
│   ├── __init__.py
│   ├── job_queue.py       # Job queue implementation
│   └── handlers.py        # Job type handlers
├── services/              # Business logic
│   ├── video_service.py   # Video processing services
│   └── caption_service.py # Caption generation services
├── routes/                # API routes
│   ├── api.py            # REST API endpoints
│   └── pages.py          # Web page routes
├── utils/                 # Utilities
│   ├── helpers.py
│   ├── storage.py
│   └── auth.py
├── static/                # Frontend assets
│   ├── css/
│   └── js/
├── templates/             # HTML templates
├── downloads/             # Uploaded/downloaded videos
├── processed/             # Processed videos
├── captions/              # Caption files
├── app.py                 # Application entry point
├── config.py              # Configuration
└── video_platform.db      # SQLite database
```

## 🚀 Job Types

### Download Job
Downloads video from URL
```python
input_data = {
    'url': 'https://youtube.com/watch?v=...',
    'title': 'Optional video title'
}
```

### Upload Job
Processes uploaded file
```python
input_data = {
    'filename': 'uploaded_file.mp4',
    'title': 'Video title',
    'size_bytes': 12345678
}
```

### Caption Job
Generates captions using Whisper AI
```python
input_data = {
    'model_size': 'tiny',  # tiny, base, small, medium, large
    'word_level': False    # Word-level timestamps
}
```

### Burn Job
Burns captions into video
```python
input_data = {
    'caption_id': 'uuid',  # Optional, uses latest if not specified
    'style': {
        'fontSize': 20,
        'fontName': 'Arial Black',
        'primaryColor': '#ffff00',
        'outlineColor': '#000000',
        'alignment': '2'
    }
}
```

### Split Scenes Job
Splits video based on scene detection
```python
input_data = {
    'min_scene_len': 2.0,  # Minimum scene length in seconds
    'threshold': 3.0       # Scene detection threshold
}
```

### Split Fixed Job
Splits video at fixed intervals
```python
input_data = {
    'interval': 30  # Interval in seconds
}
```

### Trim Job
Trims video to specific time range
```python
input_data = {
    'start_time': 10.5,  # Start time in seconds
    'end_time': 60.0,    # End time in seconds
    'title': 'Trimmed clip'
}
```

## 🔧 API Usage Examples

### Submit a Job
```python
from queue import get_job_queue

job_queue = get_job_queue()

# Submit download job with high priority
job_id = job_queue.submit_job(
    job_type='download',
    project_id='project-uuid',
    input_data={
        'url': 'https://youtube.com/watch?v=...',
        'title': 'My Video'
    },
    priority=10  # Higher priority than default (0)
)

print(f"Job submitted: {job_id}")
```

### Check Job Status
```python
from database.models import Job

job = Job.get_by_id(job_id)
print(f"Status: {job['status']}")
print(f"Progress: {job['progress']}%")
if job['error_message']:
    print(f"Error: {job['error_message']}")
```

### Cancel a Job
```python
from database.models import Job

Job.cancel(job_id)
```

### CRUD Operations

#### Projects
```python
from database.models import Project

# Create
project = Project.create(name="My Project", description="Description")

# Read
project = Project.get_by_id(project_id)
all_projects = Project.get_all()

# Update
project = Project.update(project_id, name="New Name")

# Delete (soft delete)
Project.delete(project_id)

# Restore
Project.restore(project_id)

# Hard delete
Project.delete(project_id, hard_delete=True)
```

#### Videos
```python
from database.models import Video

# Create
video = Video.create(
    project_id=project_id,
    title="My Video",
    filename="video.mp4",
    source_url="https://...",
    size_bytes=12345678
)

# Read
video = Video.get_by_id(video_id)
project_videos = Video.get_by_project(project_id)

# Update
video = Video.update(video_id, title="New Title")

# Delete
Video.delete(video_id)
```

## 🔄 Migration from JSON

To migrate existing data from `projects.json` to SQLite:

```bash
# Run migration script
python -m database.migration
```

This will:
1. Create a backup of `projects.json`
2. Initialize the SQLite database
3. Import all projects and videos
4. Verify data integrity

## ⚡ Performance Optimizations

1. **WAL Mode**: Write-Ahead Logging for better concurrency
2. **Connection Pooling**: Reuse database connections
3. **Indexes**: Optimized queries on frequently accessed columns
4. **Batch Operations**: Execute multiple operations in single transaction
5. **Multi-threading**: 4 concurrent job workers
6. **Priority Queue**: Process important jobs first
7. **Caching**: Whisper models cached in memory

## 🛡️ Error Handling

- **Automatic Retries**: Failed jobs retry up to 3 times
- **Error Logging**: Detailed error messages and stack traces
- **Transaction Safety**: Database operations are transactional
- **Foreign Key Constraints**: Referential integrity enforced
- **Soft Deletes**: Accidental deletions can be recovered

## 📊 Monitoring

### Queue Statistics
```python
from queue import get_job_queue

job_queue = get_job_queue()
stats = job_queue.get_stats()

print(f"Workers: {stats['num_workers']}")
print(f"Queue size: {stats['queue_size']}")
print(f"Workers status: {stats['workers']}")
```

### Database Cleanup
```python
from database.models import Job

# Delete completed jobs older than 30 days
count = Job.delete_old_jobs(days=30)
print(f"Deleted {count} old jobs")
```

### Database Maintenance
```python
from database.schema import get_db_manager

db = get_db_manager()

# Optimize database
db.vacuum()  # Reclaim space
db.analyze()  # Update statistics
```

## 🎨 Features Maintained

All existing features are fully maintained:
- ✅ Video downloading from URLs
- ✅ File uploads
- ✅ Auto-captioning with Whisper
- ✅ Caption burning with custom styles
- ✅ Scene-based video splitting
- ✅ Fixed-interval video splitting
- ✅ Video trimming
- ✅ Project management
- ✅ Authentication
- ✅ Progress tracking
- ✅ Real-time updates

## 🔜 Future Enhancements

- WebSocket support for real-time job updates
- Job scheduling and cron jobs
- Video transcoding with multiple formats
- Cloud storage integration
- API rate limiting
- User management and permissions
- Analytics and reporting
- Video thumbnails generation
- Batch operations API

## 🐛 Troubleshooting

### Database locked errors
- The system uses WAL mode which greatly reduces lock contention
- If issues persist, reduce NUM_JOB_WORKERS in config

### Jobs not processing
- Check that workers are running: `job_queue.get_stats()`
- Check job status: `Job.get_by_id(job_id)`
- Check logs for errors

### Migration issues
- Ensure `projects.json` exists and is valid JSON
- Check file permissions
- Review migration errors in logs

## 📝 License

This is a professional video content creation platform designed for production use.
