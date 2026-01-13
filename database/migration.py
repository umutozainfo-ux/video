"""
Data migration utility to convert existing JSON data to SQLite database.
Ensures no data loss during the transition.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any
from database.schema import init_database
from database.models import Project, Video

logger = logging.getLogger(__name__)


class DataMigrator:
    """Handles migration from JSON storage to SQLite database."""
    
    def __init__(self, json_file: str = 'projects.json', db_path: str = 'video_platform.db'):
        self.json_file = json_file
        self.db_path = db_path
        self.stats = {
            'projects_migrated': 0,
            'videos_migrated': 0,
            'errors': []
        }
    
    def load_json_data(self) -> Dict[str, Any]:
        """Load data from existing JSON file."""
        if not os.path.exists(self.json_file):
            logger.warning(f"JSON file not found: {self.json_file}")
            return {}
        
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"Loaded {len(data)} projects from {self.json_file}")
            return data
        except Exception as e:
            logger.error(f"Failed to load JSON data: {str(e)}")
            raise
    
    def migrate(self, backup_json: bool = True) -> Dict[str, Any]:
        """
        Perform the migration from JSON to SQLite.
        
        Args:
            backup_json: If True, creates a backup of the JSON file before migration
        
        Returns:
            Migration statistics dictionary
        """
        logger.info("=" * 60)
        logger.info("Starting data migration from JSON to SQLite")
        logger.info("=" * 60)
        
        # Create backup if requested
        if backup_json and os.path.exists(self.json_file):
            backup_file = f"{self.json_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                import shutil
                shutil.copy2(self.json_file, backup_file)
                logger.info(f"Created backup: {backup_file}")
            except Exception as e:
                logger.error(f"Failed to create backup: {str(e)}")
                raise
        
        # Initialize database
        logger.info(f"Initializing database: {self.db_path}")
        init_database(self.db_path)
        
        # Load JSON data
        json_data = self.load_json_data()
        
        if not json_data:
            logger.info("No data to migrate")
            return self.stats
        
        # Migrate each project
        for project_id, project_data in json_data.items():
            try:
                self._migrate_project(project_id, project_data)
            except Exception as e:
                error_msg = f"Failed to migrate project {project_id}: {str(e)}"
                logger.error(error_msg)
                self.stats['errors'].append(error_msg)
        
        # Print migration summary
        logger.info("=" * 60)
        logger.info("Migration completed!")
        logger.info(f"  Projects migrated: {self.stats['projects_migrated']}")
        logger.info(f"  Videos migrated: {self.stats['videos_migrated']}")
        logger.info(f"  Errors: {len(self.stats['errors'])}")
        logger.info("=" * 60)
        
        if self.stats['errors']:
            logger.warning("Errors encountered during migration:")
            for error in self.stats['errors']:
                logger.warning(f"  - {error}")
        
        return self.stats
    
    def _migrate_project(self, project_id: str, project_data: Dict[str, Any]):
        """Migrate a single project and its videos."""
        logger.info(f"Migrating project: {project_id} - {project_data.get('name', 'Unnamed')}")
        
        # Check if project already exists
        existing_project = Project.get_by_id(project_id)
        
        if existing_project:
            logger.info(f"  Project {project_id} already exists, updating...")
            Project.update(
                project_id,
                name=project_data.get('name', 'Unnamed'),
                description=project_data.get('description')
            )
        else:
            # Create new project with specified ID (we'll use raw SQL for this)
            from database.schema import get_db_manager
            db = get_db_manager()
            
            db.execute_write(
                """INSERT INTO projects (id, name, description, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    project_id,
                    project_data.get('name', 'Unnamed'),
                    project_data.get('description'),
                    project_data.get('created_at', datetime.utcnow().isoformat())
                )
            )
            logger.info(f"  Created project: {project_id}")
        
        self.stats['projects_migrated'] += 1
        
        # Migrate videos
        videos = project_data.get('videos', [])
        logger.info(f"  Migrating {len(videos)} videos...")
        
        for video_data in videos:
            try:
                self._migrate_video(project_id, video_data)
            except Exception as e:
                error_msg = f"Failed to migrate video {video_data.get('id')}: {str(e)}"
                logger.error(f"  {error_msg}")
                self.stats['errors'].append(error_msg)
    
    def _migrate_video(self, project_id: str, video_data: Dict[str, Any]):
        """Migrate a single video."""
        video_id = video_data.get('id')
        
        # Check if video already exists
        existing_video = Video.get_by_id(video_id)
        
        if existing_video:
            logger.info(f"    Video {video_id} already exists, skipping...")
            return
        
        # Create video with specified ID (use raw SQL)
        from database.schema import get_db_manager
        db = get_db_manager()
        
        db.execute_write(
            """INSERT INTO videos 
               (id, project_id, title, filename, source_url, is_clip, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                video_id,
                project_id,
                video_data.get('title', 'Untitled'),
                video_data.get('filename', ''),
                video_data.get('source_url'),
                1 if video_data.get('is_clip') else 0,
                video_data.get('created_at', datetime.utcnow().isoformat())
            )
        )
        
        self.stats['videos_migrated'] += 1
        logger.debug(f"    Migrated video: {video_id} - {video_data.get('title')}")
    
    def verify_migration(self) -> Dict[str, Any]:
        """Verify that migration was successful by comparing counts."""
        logger.info("Verifying migration...")
        
        json_data = self.load_json_data()
        
        # Count in JSON
        json_project_count = len(json_data)
        json_video_count = sum(len(p.get('videos', [])) for p in json_data.values())
        
        # Count in database
        db_projects = Project.get_all()
        db_project_count = len(db_projects)
        db_video_count = sum(len(Video.get_by_project(p['id'])) for p in db_projects)
        
        verification = {
            'json_projects': json_project_count,
            'db_projects': db_project_count,
            'json_videos': json_video_count,
            'db_videos': db_video_count,
            'projects_match': json_project_count == db_project_count,
            'videos_match': json_video_count == db_video_count
        }
        
        logger.info("Verification results:")
        logger.info(f"  JSON Projects: {json_project_count}, DB Projects: {db_project_count}")
        logger.info(f"  JSON Videos: {json_video_count}, DB Videos: {db_video_count}")
        logger.info(f"  Match: {'✓' if verification['projects_match'] and verification['videos_match'] else '✗'}")
        
        return verification


def migrate_data(json_file: str = 'projects.json', db_path: str = 'video_platform.db',
                 backup: bool = True) -> Dict[str, Any]:
    """
    Convenience function to perform data migration.
    
    Args:
        json_file: Path to JSON data file
        db_path: Path to SQLite database
        backup: Whether to create backup of JSON file
    
    Returns:
        Migration statistics
    """
    migrator = DataMigrator(json_file, db_path)
    stats = migrator.migrate(backup_json=backup)
    verification = migrator.verify_migration()
    
    return {
        'migration': stats,
        'verification': verification
    }


if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run migration
    result = migrate_data()
    
    # Print results
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Projects migrated: {result['migration']['projects_migrated']}")
    print(f"Videos migrated: {result['migration']['videos_migrated']}")
    print(f"Errors: {len(result['migration']['errors'])}")
    
    # Use simple text instead of unicode characters
    verification_passed = result['verification']['projects_match'] and result['verification']['videos_match']
    print(f"\nVerification: {'PASSED' if verification_passed else 'FAILED'}")
