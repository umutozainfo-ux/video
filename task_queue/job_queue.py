"""
Professional job queue system with worker pool for concurrent processing.
Handles multiple jobs simultaneously with priority support and real-time updates.
"""

import logging
import queue
import threading
import time
import traceback
from typing import Callable, Dict, Any, Optional, List
from datetime import datetime
from database.models import Job

logger = logging.getLogger(__name__)


class JobWorker(threading.Thread):
    """Worker thread that processes jobs from the queue."""
    
    def __init__(self, worker_id: int, job_queue: queue.PriorityQueue,
                 job_handlers: Dict[str, Callable], stop_event: threading.Event):
        super().__init__(daemon=True)
        self.worker_id = worker_id
        self.job_queue = job_queue
        self.job_handlers = job_handlers
        self.stop_event = stop_event
        self.current_job_id = None
        self.name = f"JobWorker-{worker_id}"
        logger.info(f"Initialized {self.name}")
    
    def run(self):
        """Main worker loop."""
        logger.info(f"{self.name} started and waiting for jobs...")
        
        while not self.stop_event.is_set():
            try:
                # Get job from queue with timeout to check stop_event periodically
                try:
                    priority, job_id = self.job_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Process the job
                self.process_job(job_id)
                self.job_queue.task_done()
                
            except Exception as e:
                logger.error(f"{self.name} encountered error: {str(e)}")
                logger.error(traceback.format_exc())
        
        logger.info(f"{self.name} stopped")
    
    def process_job(self, job_id: str):
        """Process a single job."""
        self.current_job_id = job_id
        
        try:
            # Get job from database
            job = Job.get_by_id(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in database")
                return
            
            # Check if job was cancelled
            if job['status'] == Job.STATUS_CANCELLED:
                logger.info(f"{self.name} - Job {job_id} was cancelled, skipping")
                return
            
            # Update status to running
            Job.update_status(job_id, Job.STATUS_RUNNING, progress=0)
            logger.info(f"{self.name} - Processing job {job_id} ({job['type']})")
            
            # Get appropriate handler for job type
            handler = self.job_handlers.get(job['type'])
            if not handler:
                raise ValueError(f"No handler registered for job type: {job['type']}")
            
            # Execute the job handler
            start_time = time.time()
            result = handler(job)
            execution_time = time.time() - start_time
            
            # Update job as completed
            Job.update_status(
                job_id,
                Job.STATUS_COMPLETED,
                progress=100,
                output_data=result or {}
            )
            
            logger.info(
                f"{self.name} - Job {job_id} completed successfully "
                f"in {execution_time:.2f}s"
            )
            
        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"{self.name} - Job {job_id} failed: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Update job as failed
            Job.update_status(
                job_id,
                Job.STATUS_FAILED,
                error_message=error_msg
            )
            
            # Check if job should be retried
            job = Job.get_by_id(job_id)
            if job and job['retry_count'] < job['max_retries']:
                logger.info(f"Job {job_id} will be retried")
                Job.retry(job_id)
        
        finally:
            self.current_job_id = None


class JobQueue:
    """
    Professional job queue manager with worker pool.
    Handles job submission, prioritization, and concurrent execution.
    """
    
    def __init__(self, num_workers: int = 4):
        self.num_workers = num_workers
        self.queue = queue.PriorityQueue()
        self.workers = []
        self.job_handlers = {}
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._started = False
        
        logger.info(f"JobQueue initialized with {num_workers} workers")
    
    def register_handler(self, job_type: str, handler: Callable):
        """
        Register a handler function for a specific job type.
        Handler should accept job dict and return result dict.
        """
        self.job_handlers[job_type] = handler
        logger.info(f"Registered handler for job type: {job_type}")
    
    def start(self):
        """Start the worker threads."""
        with self._lock:
            if self._started:
                logger.warning("JobQueue already started")
                return
            
            logger.info(f"Starting {self.num_workers} worker threads...")
            
            # Create and start workers
            for i in range(self.num_workers):
                worker = JobWorker(
                    worker_id=i + 1,
                    job_queue=self.queue,
                    job_handlers=self.job_handlers,
                    stop_event=self.stop_event
                )
                worker.start()
                self.workers.append(worker)
            
            # Load pending jobs from database
            self._load_pending_jobs()
            
            self._started = True
            logger.info("JobQueue started successfully")
    
    def stop(self, wait: bool = True):
        """Stop all workers."""
        with self._lock:
            if not self._started:
                return
            
            logger.info("Stopping JobQueue...")
            self.stop_event.set()
            
            if wait:
                for worker in self.workers:
                    worker.join(timeout=5.0)
            
            self.workers.clear()
            self._started = False
            logger.info("JobQueue stopped")
    
    def submit_job(self, job_type: str, project_id: str = None, video_id: str = None,
                   input_data: Dict[str, Any] = None, priority: int = 0) -> str:
        """
        Submit a new job to the queue.
        
        Args:
            job_type: Type of job (download, caption, burn, etc.)
            project_id: Associated project ID
            video_id: Associated video ID
            input_data: Job-specific input parameters
            priority: Job priority (higher = processed first)
        
        Returns:
            job_id: Unique job identifier
        """
        # Create job in database
        job = Job.create(
            job_type=job_type,
            project_id=project_id,
            video_id=video_id,
            input_data=input_data,
            priority=priority
        )
        
        job_id = job['id']
        
        # Add to queue (negative priority for max heap behavior)
        self.queue.put((-priority, job_id))
        
        logger.info(f"Submitted job {job_id} ({job_type}) with priority {priority}")
        return job_id
    
    def _load_pending_jobs(self):
        """Load pending jobs from database on startup."""
        pending_jobs = Job.get_pending_jobs()
        
        if not pending_jobs:
            logger.info("No pending jobs found in database")
            return
        
        logger.info(f"Loading {len(pending_jobs)} pending jobs from database...")
        
        for job in pending_jobs:
            self.queue.put((-job['priority'], job['id']))
        
        logger.info(f"Loaded {len(pending_jobs)} pending jobs into queue")
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job."""
        success = Job.cancel(job_id)
        if success:
            logger.info(f"Cancelled job: {job_id}")
        return success
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a job."""
        return Job.get_by_id(job_id)
    
    def get_queue_size(self) -> int:
        """Get number of jobs waiting in queue."""
        return self.queue.qsize()
    
    def get_worker_status(self) -> List[Dict[str, Any]]:
        """Get status of all workers."""
        return [
            {
                'worker_id': worker.worker_id,
                'name': worker.name,
                'alive': worker.is_alive(),
                'current_job_id': worker.current_job_id
            }
            for worker in self.workers
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            'num_workers': self.num_workers,
            'queue_size': self.get_queue_size(),
            'workers': self.get_worker_status(),
            'started': self._started
        }


# Global job queue instance
_job_queue: Optional[JobQueue] = None


def get_job_queue(num_workers: int = 4) -> JobQueue:
    """Get or create the global job queue instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue(num_workers=num_workers)
    return _job_queue


def init_job_queue(num_workers: int = 4) -> JobQueue:
    """Initialize and start the job queue."""
    job_queue = get_job_queue(num_workers)
    if not job_queue._started:
        job_queue.start()
    return job_queue


# Progress update helper function
def update_job_progress(job_id: str, progress: int, message: str = None):
    """
    Update job progress. Can be called from job handlers.
    
    Args:
        job_id: Job ID
        progress: Progress percentage (0-100)
        message: Optional progress message
    """
    try:
        output_data = {}
        if message:
            output_data['progress_message'] = message
        
        Job.update_status(job_id, Job.STATUS_RUNNING, progress=progress, output_data=output_data)
        logger.debug(f"Job {job_id} progress: {progress}% - {message if message else ''}")
    except Exception as e:
        logger.error(f"Failed to update job progress: {str(e)}")
