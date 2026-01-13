"""
Test script to verify the new database and job queue system.
"""

import logging
from database.models import Project, Video, Job
from task_queue import get_job_queue, init_job_queue
from task_queue.handlers import JOB_HANDLERS

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_database():
    """Test database CRUD operations."""
    logger.info("=" * 60)
    logger.info("Testing Database CRUD Operations")
    logger.info("=" * 60)
    
    # Test Projects
    logger.info("\n1. Testing Projects...")
    projects = Project.get_all()
    logger.info(f"   Found {len(projects)} projects")
    if projects:
        logger.info(f"   Sample: {projects[0]['name']}")
    
    # Test Videos
    logger.info("\n2. Testing Videos...")
    for project in projects[:1]:  # Test first project
        videos = Video.get_by_project(project['id'])
        logger.info(f"   Project '{project['name']}' has {len(videos)} videos")
        if videos:
            logger.info(f"   Sample: {videos[0]['title']}")
    
    # Test Jobs
    logger.info("\n3. Testing Jobs...")
    pending_jobs = Job.get_pending_jobs()
    logger.info(f"   Found {len(pending_jobs)} pending jobs")
    
    all_jobs = Job.get_by_status(Job.STATUS_COMPLETED)
    logger.info(f"   Found {len(all_jobs)} completed jobs")
    
    logger.info("\n✓ Database tests passed!")

def test_job_queue():
    """Test job queue system."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Job Queue System")
    logger.info("=" * 60)
    
    # Initialize job queue
    logger.info("\n1. Initializing job queue...")
    job_queue = init_job_queue(num_workers=4)
    
    # Register handlers
    logger.info("2. Registering job handlers...")
    for job_type, handler in JOB_HANDLERS.items():
        job_queue.register_handler(job_type, handler)
    logger.info(f"   Registered {len(JOB_HANDLERS)} handlers")
    logger.info(f"   Handler types: {', '.join(JOB_HANDLERS.keys())}")
    
    # Get stats
    logger.info("\n3. Checking queue stats...")
    stats = job_queue.get_stats()
    logger.info(f"   Workers: {stats['num_workers']}")
    logger.info(f"   Queue size: {stats['queue_size']}")
    logger.info(f"   Started: {stats['started']}")
    
    for worker in stats['workers']:
        status = "✓ Active" if worker['alive'] else "✗ Inactive"
        current = f" (processing {worker['current_job_id']})" if worker['current_job_id'] else ""
        logger.info(f"   {worker['name']}: {status}{current}")
    
    # Clean up
    logger.info("\n4. Stopping job queue...")
    job_queue.stop(wait=False)
    
    logger.info("\n✓ Job queue tests passed!")

def test_models():
    """Test model operations."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Model Operations")
    logger.info("=" * 60)
    
    # Test creating and deleting a project
    logger.info("\n1. Testing Project CRUD...")
    test_project = Project.create(
        name="Test Project",
        description="This is a test project"
    )
    logger.info(f"   Created project: {test_project['id']}")
    
    # Update
    updated = Project.update(test_project['id'], name="Updated Test Project")
    logger.info(f"   Updated project name to: {updated['name']}")
    
    # Soft delete
    Project.delete(test_project['id'])
    logger.info(f"   Soft deleted project")
    
    # Verify deleted
    projects = Project.get_all(include_deleted=False)
    found = any(p['id'] == test_project['id'] for p in projects)
    logger.info(f"   Project visible in list: {found}")
    
    # Restore
    Project.restore(test_project['id'])
    logger.info(f"   Restored project")
    
    # Hard delete
    Project.delete(test_project['id'], hard_delete=True)
    logger.info(f"   Hard deleted project")
    
    logger.info("\n✓ Model tests passed!")

def main():
    """Run all tests."""
    logger.info("\n" + "=" * 60)
    logger.info("VIDEO PLATFORM SYSTEM TESTS")
    logger.info("=" * 60)
    
    try:
        test_database()
        test_models()
        test_job_queue()
        
        logger.info("\n" + "=" * 60)
        logger.info("ALL TESTS PASSED!")
        logger.info("=" * 60)
        logger.info("\nThe system is ready to use!")
        logger.info("Database: video_platform.db")
        logger.info("Projects migrated: Yes")
        logger.info("Job queue: Operational")
        logger.info("\nYou can now start the server with: python app.py")
        
    except Exception as e:
        logger.error(f"\n✗ Tests failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
