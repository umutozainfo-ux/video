import os
import sys
print(">>> AG STUDIO SYSTEM BOOTING...", flush=True)

from flask import Flask, request
from flask_socketio import SocketIO, emit
from config import Config, init_app_dirs
from routes.api import api_bp
from routes.pages import pages_bp
from utils.helpers import check_ffmpeg_available
from database import init_database
from task_queue import init_job_queue
from task_queue.handlers import JOB_HANDLERS
from services.browser_service import BrowserManager
import logging
import atexit
import asyncio
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

logger = logging.getLogger(__name__)

socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')

def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.from_object(Config)
    
    # Initialize directories
    init_app_dirs(Config)
    
    # Initialize database
    logger.info("Initializing SQLite database...")
    init_database()
    from database.models import User
    User.ensure_admin()
    logger.info("Database initialized successfully")
    
    # Initialize job queue with 4 workers
    logger.info("Initializing job queue with 4 workers...")
    job_queue = init_job_queue(num_workers=4)
    
    # Register job handlers
    logger.info("Registering job handlers...")
    for job_type, handler in JOB_HANDLERS.items():
        job_queue.register_handler(job_type, handler)
    logger.info(f"Registered {len(JOB_HANDLERS)} job handlers")
    
    # Store job queue in app config for access in routes
    app.config['JOB_QUEUE'] = job_queue
    
    # Register cleanup on shutdown
    def cleanup():
        logger.info("Shutting down job queue...")
        job_queue.stop(wait=True)
        logger.info("Job queue stopped")
    
    atexit.register(cleanup)
    
    # Register blueprints
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/sw.js')
    def serve_sw():
        return app.send_static_file('sw.js')

    @app.route('/manifest.json')
    def serve_manifest():
        return app.send_static_file('manifest.json')
    
    socketio.init_app(app)
    
    # WebSocket Events for RBC
    @socketio.on('connect')
    def handle_connect():
        logger.info(f"Client connected: {request.sid}")

    @socketio.on('disconnect')
    def handle_disconnect():
        BrowserManager.stop_instance(request.sid)
        logger.info(f"Client disconnected: {request.sid}")

    @socketio.on('browser_init')
    def handle_browser_init(data):
        url = data.get('url', 'https://google.com')
        instance = BrowserManager.get_instance(request.sid, socketio)
        instance.start(url)

    @socketio.on('browser_stop')
    def handle_browser_stop():
        BrowserManager.stop_instance(request.sid)
        logger.info(f"Browser stopped for client: {request.sid}")

    @socketio.on('browser_input')
    def handle_browser_input(data):
        instance = BrowserManager.get_instance(request.sid, socketio)
        if instance.loop:
            # We use a future to see if we need to trigger a job
            async def run_and_check():
                try:
                    res = await instance.handle_input(data)
                    if not res: return False

                    from task_queue.job_queue import get_job_queue
                    jq = get_job_queue()

                    if res.get('type') == 'browser_import':
                        jq.submit_job('browser_import', project_id=res['project_id'], input_data={
                            'temp_path': res['temp_path'],
                            'original_name': res['original_name']
                        })
                        socketio.emit('browser_status_update', {'message': f"Import queued for {res['original_name']}", 'type': 'info'}, room=request.sid)
                        return True
                    elif res.get('url'):
                        # Trigger download job
                        jq.submit_job('download', project_id=res['project_id'], input_data={'url': res['url']})
                        socketio.emit('browser_status_update', {'message': "Download task submitted", 'type': 'info'}, room=request.sid)
                        return True
                except Exception as e:
                    logger.error(f"Error in browser input handler: {e}")
                    socketio.emit('browser_status_update', {'message': f"Failed to process request: {str(e)}", 'type': 'error'}, room=request.sid)
                return False
            
            asyncio.run_coroutine_threadsafe(run_and_check(), instance.loop)

    logger.info("Application initialized successfully with WebSockets")
    return app

app = create_app()

if __name__ == '__main__':
    if not check_ffmpeg_available():
        logger.warning("FFmpeg not found! Video processing will fail. Please install FFmpeg.")
    
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask-SocketIO server on http://0.0.0.0:{port}")
    
    # Run a one-time cleanup on startup
    from utils.cleanup import run_storage_cleanup
    run_storage_cleanup(max_age_hours=48)
    
    socketio.run(app, debug=False, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
