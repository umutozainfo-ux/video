import asyncio
import base64
import logging
import os
import threading
import time
import platform
import subprocess
import shutil
import uuid
from typing import Dict, Any, Optional
from config import Config
import numpy as np
import cv2
from playwright.async_api import async_playwright
from undetected_playwright import stealth_async

logger = logging.getLogger(__name__)

# Try to import virtual display for Docker/Linux
try:
    from pyvirtualdisplay import Display
    HAS_VIRTUAL_DISPLAY = True
except ImportError:
    HAS_VIRTUAL_DISPLAY = False

class BrowserInstance:
    STEALTH_INIT_SCRIPT = r"""
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    window.navigator.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    try {
        const originalQuery = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.'; 
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return originalQuery.call(this, param);
        };
    } catch(e) {}
    """

    def __init__(self, socket_id, socketio):
        self.socket_id = socket_id
        self.socketio = socketio
        self.browser = None
        self.context = None
        self.page = None
        self.running = False
        self.thread = None
        self.loop = None
        self.display = None
        self._pointer_queue: Optional[asyncio.Queue] = None
        self._active_downloads = {}

    def start(self, url="https://google.com"):
        if self.running and self.thread and self.thread.is_alive():
            logger.info(f"Browser for {self.socket_id} already running, navigating to {url}")
            if self.loop and self.page:
                asyncio.run_coroutine_threadsafe(self.page.goto(url), self.loop)
            return

        logger.info(f"Starting browser instance for {self.socket_id} with url: {url}")
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, args=(url,))
        self.thread.daemon = True
        self.thread.start()

    def _run_loop(self, url):
        logger.info(f"Thread started for browser {self.socket_id}")
        if platform.system() == 'Linux' and HAS_VIRTUAL_DISPLAY:
            try:
                logger.info("Starting virtual display (Xvfb)...")
                self.display = Display(visible=0, size=(1280, 720))
                self.display.start()
            except Exception as e:
                logger.error(f"Failed to start virtual display: {e}")

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        logger.info(f"Event loop created for {self.socket_id}. Running session...")
        try:
            self.loop.run_until_complete(self._browser_session(url))
        except Exception as e:
            logger.error(f"Error in browser session loop for {self.socket_id}: {e}")
        finally:
            if self.display:
                self.display.stop()
            logger.info(f"Thread finishing for {self.socket_id}")

    async def _browser_session(self, url):
        self._pointer_queue = asyncio.Queue(maxsize=1)
        asyncio.create_task(self._pointer_loop())

        async with async_playwright() as p:
            is_headless = True
            if self.display:
                is_headless = False

            # Optimized launch args from reference
            args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-gpu",
                "--force-color-profile=srgb"
            ]

            # Load proxy from config if available
            proxy_config = None
            try:
                import json
                config_path = os.path.join(os.getcwd(), 'admin_config.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        if config.get('proxy_enabled') and config.get('proxy'):
                            proxy_str = config['proxy'].strip()
                            if proxy_str:
                                if not proxy_str.startswith('http'):
                                    proxy_str = f'http://{proxy_str}'
                                proxy_config = {'server': proxy_str}
                                logger.info(f"Browser will launch with proxy: {proxy_str}")
            except Exception as e:
                logger.warning(f"Could not load proxy config: {e}")

            # Optimized launch args from reference
            args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-gpu",
                "--force-color-profile=srgb"
            ]

            self.browser = await p.chromium.launch(
                headless=is_headless, 
                args=args,
                proxy=proxy_config # MUST be here for Playwright to allow context proxies or use global
            )
            
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            
            context_opts = {
                'viewport': {'width': 1280, 'height': 720},
                'user_agent': ua,
                'bypass_csp': True
            }
            # We also keep it in context_opts for good measure, though launch() handles it globally
            if proxy_config:
                context_opts['proxy'] = proxy_config
            
            self.context = await self.browser.new_context(**context_opts)
            
            await self.context.add_init_script(self.STEALTH_INIT_SCRIPT)
            
            self.page = await self.context.new_page()
            await self.page.set_viewport_size({'width': 1280, 'height': 720})
            await stealth_async(self.page)
            
            # Start streaming immediately
            self.socketio.emit('browser_status', {'status': 'loading', 'url': url}, room=self.socket_id)
            
            self._active_downloads = {}

            # Listen for downloads
            async def on_download(download):
                try:
                    filename = download.suggested_filename
                    url = download.url
                    download_id = str(uuid.uuid4())
                    
                    logger.info(f"Download started: {filename} from {url}")
                    self._active_downloads[download_id] = filename
                    
                    self.socketio.emit('browser_download_detected', {
                        'id': download_id,
                        'filename': filename,
                        'url': url
                    }, room=self.socket_id)

                    # Wait for download to finish in background
                    path = await download.path() # This waits for completion
                    if path:
                        # CRITICAL: Playwright deletes the temp path when the browser closes.
                        # We must move it to a safe, persistent stage area immediately.
                        stage_dir = os.path.join(Config.UPLOAD_FOLDER, 'browser_staged')
                        os.makedirs(stage_dir, exist_ok=True)

                        # Ensure safe filename for the stage path
                        from utils.helpers import sanitize_filename
                        safe_name = sanitize_filename(filename)
                        
                        stable_path = os.path.join(stage_dir, f"stage_{download_id}_{safe_name}")
                        shutil.move(path, stable_path)
                        
                        logger.info(f"Download secured to stage: {safe_name} at {stable_path}")
                        # Store info for later import when user confirms project
                        self._active_downloads[download_id] = {
                            'filename': filename, # keep original for title
                            'temp_path': stable_path,
                            'status': 'finished'
                        }
                        self.socketio.emit('browser_download_finished', {
                            'id': download_id,
                            'filename': filename
                        }, room=self.socket_id)
                except Exception as e:
                    logger.error(f"Error handling download: {e}")

            self.page.on("download", on_download)

            async def streaming_task():
                frame_count = 0
                error_count = 0
                while self.running:
                    if not self.browser or not self.page or self.page.is_closed(): break
                    try:
                        screenshot = await self.page.screenshot(type='jpeg', quality=50)
                        if screenshot:
                            encoded = base64.b64encode(screenshot).decode('utf-8')
                            self.socketio.emit('browser_frame', {'image': encoded}, room=self.socket_id)
                            frame_count += 1
                            if frame_count == 1:
                                self.socketio.emit('browser_status', {'status': 'rendering'}, room=self.socket_id)
                            if frame_count % 50 == 0:
                                logger.info(f"Stream [ID:{self.socket_id}] - {frame_count} frames")
                        await asyncio.sleep(0.12)
                    except:
                        error_count += 1
                        if error_count > 30: break
                        await asyncio.sleep(1)

            stream_job = asyncio.create_task(streaming_task())
            
            logger.info(f"Navigating to {url}...")
            try:
                # Use none or commit for fastest feedback
                await self.page.goto(url, wait_until="commit", timeout=30000)
                logger.info(f"Navigation to {url} reached commit.")
                self.socketio.emit('browser_status', {'status': 'ready'}, room=self.socket_id)
            except Exception as e:
                logger.warning(f"Navigation reached timeout/error but continuing stream: {e}")
                self.socketio.emit('browser_status', {'status': 'ready', 'msg': 'Partial load'}, room=self.socket_id)
            
            # Keep the session alive until self.running is False AND no active downloads
            while self.running or bool(self._active_downloads):
                # If not running but has downloads wait for them to finish capturing
                is_capturing = any(isinstance(v, str) or (isinstance(v, dict) and v.get('status') != 'finished') for v in self._active_downloads.values())
                
                if not self.running and not is_capturing:
                    # All downloads finished, wait for user to hit Import
                    # But don't wait forever (max 5 minutes)
                    logger.info("Browser session idling for pending imports...")
                    await asyncio.sleep(300) 
                    break

                if self.page and self.page.is_closed() and self.running:
                    break
                    
                await asyncio.sleep(1)
            
            logger.info("Browser session ending.")

            logger.info("Closing browser - all tasks finished.")
            stream_job.cancel()
            if self.browser:
                await self.browser.close()

    async def _pointer_loop(self):
        """Consume pointer events with low latency"""
        while self.running:
            if not self.page:
                await asyncio.sleep(0.1)
                continue
            try:
                action = await self._pointer_queue.get()
                if not action: continue

                type = action.get('type')
                if type == 'mousemove':
                    await self.page.mouse.move(int(action['x']), int(action['y']), steps=1)
                elif type == 'mousedown':
                    await self.page.mouse.down()
                elif type == 'mouseup':
                    await self.page.mouse.up()
                elif type == 'click':
                    await self.page.mouse.click(int(action['x']), int(action['y']))
                elif type == 'keydown':
                    await self.page.keyboard.down(action['key'])
                elif type == 'keyup':
                    await self.page.keyboard.up(action['key'])
                elif type == 'reload':
                    await self.page.reload(wait_until="domcontentloaded")
                elif type == 'back':
                    await self.page.go_back(wait_until="domcontentloaded")
                elif type == 'scroll':
                    await self.page.mouse.wheel(0, int(action.get('deltaY', 0)))
                
                await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"Pointer error: {e}")
                await asyncio.sleep(0.01)

    def stop(self):
        self.running = False

    async def handle_input(self, data):
        # Special case for download as it's not a pointer event
        if data.get('type') == 'download':
            download_id = data.get('download_id')
            project_id = data.get('project_id')
            
            if download_id and download_id in self._active_downloads:
                info = self._active_downloads[download_id]
                if isinstance(info, dict) and info.get('status') == 'finished':
                    temp_path = info['temp_path']
                    original_name = info['filename']
                    
                    del self._active_downloads[download_id]
                    return {
                        'type': 'browser_import',
                        'project_id': project_id,
                        'temp_path': temp_path,
                        'original_name': original_name
                    }

            url = data.get('url') or (self.page.url if self.page else None)
            return {'url': url, 'project_id': project_id}

        if not self._pointer_queue: return
            
        try:
            self._pointer_queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                self._pointer_queue.get_nowait()
                self._pointer_queue.put_nowait(data)
            except: pass

class BrowserManager:
    _instances: Dict[str, BrowserInstance] = {}

    @classmethod
    def get_instance(cls, socket_id, socketio) -> BrowserInstance:
        if socket_id not in cls._instances:
            cls._instances[socket_id] = BrowserInstance(socket_id, socketio)
        return cls._instances[socket_id]

    @classmethod
    def stop_instance(cls, socket_id):
        if socket_id in cls._instances:
            cls._instances[socket_id].stop()
            del cls._instances[socket_id]

