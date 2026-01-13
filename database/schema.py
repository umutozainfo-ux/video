"""
Database schema definitions for the video platform.
Provides a professional, scalable SQLite database structure.
"""

import sqlite3
import logging
import time
from typing import Optional
from contextlib import contextmanager
from threading import Lock
import os

logger = logging.getLogger(__name__)

# Database schema DDL statements
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Users table: for multi-user passcode access
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    passcode TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'user', -- 'admin', 'user'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0
);

-- Projects table: stores video projects
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT, -- Link project to a specific user
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Videos table: stores video files and metadata
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_url TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    size_bytes INTEGER,
    is_clip INTEGER DEFAULT 0,
    parent_video_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_video_id) REFERENCES videos(id) ON DELETE SET NULL
);

-- Jobs table: tracks all background processing jobs
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- 'download', 'caption', 'burn', 'split', 'trim', 'upload'
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed', 'cancelled'
    priority INTEGER DEFAULT 0,  -- Higher number = higher priority
    project_id TEXT,
    video_id TEXT,
    input_data TEXT,  -- JSON string of input parameters
    output_data TEXT,  -- JSON string of output/result
    progress INTEGER DEFAULT 0,  -- 0-100
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Captions table: stores caption/subtitle data
CREATE TABLE IF NOT EXISTS captions (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    format TEXT DEFAULT 'srt',  -- 'srt', 'vtt', 'ass'
    style TEXT,  -- JSON string of style parameters
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Settings table: application-wide settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Metadata table: schema version and migration tracking
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_passcode ON users(passcode);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_videos_project_id ON videos(project_id);
CREATE INDEX IF NOT EXISTS idx_videos_is_deleted ON videos(is_deleted);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_project_id ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id);
CREATE INDEX IF NOT EXISTS idx_captions_video_id ON captions(video_id);
CREATE INDEX IF NOT EXISTS idx_projects_is_deleted ON projects(is_deleted);

-- Triggers for automatic updated_at timestamps
CREATE TRIGGER IF NOT EXISTS update_projects_timestamp 
    AFTER UPDATE ON projects
BEGIN
    UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_videos_timestamp 
    AFTER UPDATE ON videos
BEGIN
    UPDATE videos SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_jobs_timestamp 
    AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_captions_timestamp 
    AFTER UPDATE ON captions
BEGIN
    UPDATE captions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


class DatabaseManager:
    """
    Thread-safe database connection manager with connection pooling.
    Implements best practices for SQLite in multi-threaded environments.
    """
    
    def __init__(self, db_path: str = 'video_platform.db'):
        self.db_path = db_path
        self._lock = Lock()
        self._initialized = False
        logger.info(f"Database manager initialized with path: {db_path}")
    
    def initialize(self) -> None:
        """Initialize database schema and metadata."""
        with self._lock:
            if self._initialized:
                return
            
            try:
                with self.get_connection() as conn:
                    # Enable foreign keys
                    conn.execute("PRAGMA foreign_keys = ON")
                    
                    # Execute schema creation
                    conn.executescript(SCHEMA_SQL)
                    
                    # Set schema version
                    conn.execute(
                        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                        ('schema_version', str(SCHEMA_VERSION))
                    )
                    
                    conn.commit()
                    logger.info(f"Database initialized successfully (schema v{SCHEMA_VERSION})")
                    
                self._initialized = True
                
            except Exception as e:
                logger.error(f"Failed to initialize database: {str(e)}")
                raise
    
    @contextmanager
    def get_connection(self):
        """
        Get a database connection with proper configuration.
        Use as context manager for automatic cleanup.
        """
        conn = None
        try:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None  # Autocommit mode for better concurrency
            )
            
            # Configure connection for optimal performance
            conn.row_factory = sqlite3.Row  # Access columns by name
            conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
            conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety and performance
            conn.execute("PRAGMA cache_size=10000")  # Increase cache size
            conn.execute("PRAGMA temp_store=MEMORY")  # Store temp tables in memory
            conn.execute("PRAGMA foreign_keys=ON")  # Enable foreign key constraints
            
            yield conn
            
        except Exception as e:
            logger.error(f"Database connection error: {str(e)}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: tuple = (), fetch_one: bool = False):
        """Execute a SELECT query and return results with retries."""
        for i in range(5):
            try:
                with self.get_connection() as conn:
                    cursor = conn.execute(query, params)
                    if fetch_one:
                        return cursor.fetchone()
                    return cursor.fetchall()
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() and i < 4:
                    time.sleep(0.05 * (i + 1))
                    continue
                raise

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT/UPDATE/DELETE query with retries."""
        # Use the global lock to prevent multiple threads from hammering SQLite at exactly the same time
        with self._lock:
            for i in range(5):
                try:
                    with self.get_connection() as conn:
                        cursor = conn.execute(query, params)
                        # isolation_level=None means autocommit, but we commit just in case
                        # or if BEGIN was used.
                        if not conn.in_transaction:
                            conn.execute("BEGIN")
                        conn.commit()
                        return cursor.rowcount
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and i < 4:
                        time.sleep(0.1 * (i + 1))
                        continue
                    raise
                except Exception as e:
                    logger.error(f"Write failed: {str(e)}")
                    raise
    
    def execute_many(self, query: str, params_list: list) -> int:
        """Execute multiple INSERT/UPDATE/DELETE queries in a transaction."""
        with self.get_connection() as conn:
            cursor = conn.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
    
    def get_schema_version(self) -> int:
        """Get current database schema version."""
        try:
            row = self.execute_query(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                fetch_one=True
            )
            return int(row['value']) if row else 0
        except:
            return 0
    
    def vacuum(self) -> None:
        """Optimize database by reclaiming space and defragmenting."""
        logger.info("Running database VACUUM operation...")
        with self.get_connection() as conn:
            conn.execute("VACUUM")
        logger.info("VACUUM completed successfully")
    
    def analyze(self) -> None:
        """Update database statistics for query optimization."""
        with self.get_connection() as conn:
            conn.execute("ANALYZE")
        logger.info("Database ANALYZE completed")


# Global database instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager(db_path: str = 'video_platform.db') -> DatabaseManager:
    """Get or create the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(db_path)
        _db_manager.initialize()
    return _db_manager


def init_database(db_path: str = 'video_platform.db') -> DatabaseManager:
    """Initialize the database and return the manager instance."""
    db = get_db_manager(db_path)
    db.initialize()
    return db
