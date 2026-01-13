"""
Remote Browser Control System with WebRTC/WebSocket Streaming
Single-file FastAPI application with FFmpeg streaming and Playwright automation

This updated version adds "stealth" (undetection) measures using Playwright
init scripts (no external undetected-playwright dependency required) and
adds real-time mouse movement / hold / hover support. The web UI was
minimally extended to send pointer events (move, down, up) so you can
hover and hold elements remotely in real time.

Notes:
- The stealth measures are heuristic (navigator.webdriver override, languages,
  plugins, vendor, platform, userAgent tweaks). For some high-security sites
  further steps or additional libraries may be required.
- Real-time pointer streaming is throttled on the client to avoid flooding the
  WebSocket. Server uses Playwright's mouse API with step interpolation for
  smoother movement.
- WebRTC code and other functionality remain unchanged.
"""
import asyncio
import base64
import io
import json
import os
import platform
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from PIL import Image

# Optional imports for WebRTC (aiortc). The server will still work for WebSocket-only
# streaming even if aiortc/av are not installed.
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
    import av
    AIORTC_AVAILABLE = True
except Exception:
    AIORTC_AVAILABLE = False


# ======================================================================
# CONFIGURATION
# ======================================================================

class Config:
    """System configuration"""
    IS_DOCKER = os.path.exists("/.dockerenv")
    IS_WINDOWS = platform.system() == "Windows"

    # Display settings
    DISPLAY = ":99" if IS_DOCKER else None
    VIRTUAL_DISPLAY_SIZE = "1920x1080x24"

    # Browser settings
    HEADLESS = not IS_DOCKER  # Headless on Windows, headed in Docker with Xvfb
    VIEWPORT = {"width": 1280, "height": 720}  # reduced to 1280x720 for smoother streaming

    # Streaming settings
    FPS = 20  # lower FPS for smoother, consistent streaming over network
    JPEG_QUALITY = 75  # tradeoff quality/size for throughput
    WEBRTC_BITRATE = "2M"

    # FFmpeg settings
    FFMPEG_PRESET = "ultrafast"
    FFMPEG_TUNE = "zerolatency"

    # Pointer smoothing
    POINTER_STEPS_BASE = 8  # base number of steps for mouse.move interpolation


# ======================================================================
# VIRTUAL DISPLAY MANAGER (for Docker)
# ======================================================================

class VirtualDisplay:
    """Manages Xvfb virtual display for Docker environments"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        """Start Xvfb virtual display"""
        if not Config.IS_DOCKER:
            return

        try:
            # Start Xvfb
            self.process = subprocess.Popen([
                "Xvfb",
                Config.DISPLAY,
                "-screen", "0", Config.VIRTUAL_DISPLAY_SIZE,
                "-ac",
                "+extension", "GLX",
                "+render",
                "-noreset"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Set DISPLAY environment variable
            os.environ["DISPLAY"] = Config.DISPLAY

            # Wait for display to be ready (blocking small sleep is fine here)
            time.sleep(2)
            print(f"✓ Virtual display started: {Config.DISPLAY}")

        except Exception as e:
            print(f"✗ Failed to start virtual display: {e}")

    def stop(self):
        """Stop Xvfb virtual display"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
            print("✓ Virtual display stopped")


# ======================================================================
# BROWSER MANAGER
# ======================================================================

class BrowserManager:
    """Manages Playwright browser instances with simple stealth init scripts"""

    STEALTH_INIT_SCRIPT = r"""
// Basic stealth/init script to reduce automation fingerprints.
// This tries to mirror common browser properties (not 100% foolproof).
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.navigator.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
try {
    const originalQuery = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        // pretend to be a common GPU
        if (param === 37445) return 'Intel Inc.'; // VENDOR
        if (param === 37446) return 'Intel Iris OpenGL Engine'; // RENDERER
        return originalQuery.call(this, param);
    };
} catch(e) {}
// Prevent detection via permissions query
const _permissions = navigator.permissions;
if (_permissions && _permissions.query) {
    const originalQuery = _permissions.query.bind(_permissions);
    _permissions.query = (parameters) => (
        parameters.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)
    );
}
"""

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Pointer handling for real-time control: a small queue that always holds the latest pointer event.
        self._pointer_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._pointer_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize browser"""
        # Try to use undetected-playwright if available. We'll attempt a few common import paths
        ud_async_playwright = None
        try:
            # Common direct import (if package exposes async_playwright at top-level)
            import undetected_playwright as undpw  # type: ignore
            ud_async_playwright = getattr(undpw, "async_playwright", None)
        except Exception:
            ud_async_playwright = None

        if ud_async_playwright is None:
            try:
                # Some versions expose async_api.async_playwright
                from undetected_playwright import async_api as undpw_async_api  # type: ignore
                ud_async_playwright = getattr(undpw_async_api, "async_playwright", None)
            except Exception:
                ud_async_playwright = None

        try:
            if ud_async_playwright:
                # Use undetected-playwright's async_playwright if we found it
                self.playwright = await ud_async_playwright().start()
                print("✓ Using undetected-playwright (async) for browser start")
            else:
                # Fallback to standard Playwright
                self.playwright = await async_playwright().start()
                print("✓ Using standard playwright.async_playwright() for browser start")
        except Exception as e:
            # If starting undetected-playwright failed for any reason, fallback to standard Playwright
            print(f"✗ Failed to start undetected-playwright: {e}. Falling back to standard Playwright.")
            self.playwright = await async_playwright().start()

        # Build args and filter out empty entries
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        if Config.IS_WINDOWS and Config.HEADLESS:
            args.append("--disable-gpu")

        # Launch browser
        self.browser = await self.playwright.chromium.launch(
            headless=Config.HEADLESS,
            args=args
        )

        # Create context with viewport and a stable user agent
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
        self.context = await self.browser.new_context(
            viewport=Config.VIEWPORT,
            user_agent=ua,
            bypass_csp=True,  # sometimes helps with injected scripts
            java_script_enabled=True,
        )

        # Add stealth/init scripts to reduce detection
        await self.context.add_init_script(self.STEALTH_INIT_SCRIPT)

        # Optionally set extra headers or timezone/locale
        await self.context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

        # Create page
        self.page = await self.context.new_page()
        await self.page.goto("about:blank")

        # Start pointer processing loop for real-time pointer events
        if not self._pointer_task:
            self._pointer_task = asyncio.create_task(self._pointer_loop(), name="pointer_loop")

        print(f"✓ Browser started (headless={Config.HEADLESS}) with stealth init script")

    async def stop(self):
        """Close browser"""
        try:
            # Stop pointer task
            if self._pointer_task:
                self._pointer_task.cancel()
                try:
                    await self._pointer_task
                except Exception:
                    pass
                self._pointer_task = None

            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"✗ Error closing browser: {e}")
        print("✓ Browser stopped")

    async def screenshot(self) -> bytes:
        """Capture page screenshot (JPEG, clipped to configured viewport for performance)"""
        if not self.page:
            raise RuntimeError("Browser not initialized")

        # Use clip to ensure size is consistent and avoid full-page captures
        clip = {"x": 0, "y": 0, "width": Config.VIEWPORT["width"], "height": Config.VIEWPORT["height"]}
        return await self.page.screenshot(type="jpeg", quality=Config.JPEG_QUALITY, clip=clip, full_page=False)

    async def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute browser action, includes real-time mouse movement and pointer events."""
        if not self.page:
            return {"success": False, "error": "Browser not initialized"}

        try:
            action_type = action.get("type")

            if action_type == "navigate":
                url = action.get("url", "")
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                await self.page.goto(url, wait_until="networkidle", timeout=30000)
                return {"success": True, "url": self.page.url}

            elif action_type == "click":
                x, y = int(action.get("x", 0)), int(action.get("y", 0))
                await self.page.mouse.click(x, y)
                return {"success": True}

            elif action_type == "type":
                text = action.get("text", "")
                await self.page.keyboard.type(text)
                return {"success": True}

            elif action_type == "key":
                key = action.get("key", "")
                await self.page.keyboard.press(key)
                return {"success": True}

            elif action_type == "scroll":
                delta_y = int(action.get("deltaY", 0))
                await self.page.mouse.wheel(0, delta_y)
                return {"success": True}

            elif action_type == "back":
                await self.page.go_back()
                return {"success": True}

            elif action_type == "forward":
                await self.page.go_forward()
                return {"success": True}

            elif action_type == "refresh":
                await self.page.reload()
                return {"success": True}

            # New pointer/mouse actions for realtime control
            elif action_type == "mousemove":
                # move pointer smoothly to x,y
                x = float(action.get("x", 0))
                y = float(action.get("y", 0))
                # Optional absolute or relative flag (default absolute)
                # Calculate steps based on distance
                try:
                    current = await self.page.evaluate("() => { return {x: window.__remote_mouse_x||0, y: window.__remote_mouse_y||0}; }")
                    cur_x = float(current.get("x", 0))
                    cur_y = float(current.get("y", 0))
                except Exception:
                    # Fallback: no stored position client-side, just use target as single move
                    cur_x, cur_y = x, y

                dx = abs(x - cur_x)
                dy = abs(y - cur_y)
                dist = max(dx, dy)
                steps = max(1, int(dist / 10) * 1 + Config.POINTER_STEPS_BASE)
                steps = min(60, steps)

                # Interpolate with Playwright mouse.move
                await self.page.mouse.move(int(x), int(y), steps=steps)

                # Store remote mouse position (so next interpolation can be smoother)
                # This is a lightweight page variable to help subsequent moves
                try:
                    await self.page.evaluate(f"(x,y) => (window.__remote_mouse_x = x, window.__remote_mouse_y = y)", x, y)
                except Exception:
                    pass

                return {"success": True}

            elif action_type == "mousedown":
                # button: left/right/middle
                button = action.get("button", "left")
                await self.page.mouse.down(button=button)
                return {"success": True}

            elif action_type == "mouseup":
                button = action.get("button", "left")
                await self.page.mouse.up(button=button)
                return {"success": True}

            elif action_type == "hover_selector":
                # Hover an element by CSS selector
                selector = action.get("selector", "")
                if selector:
                    await self.page.hover(selector, timeout=5000)
                    return {"success": True}
                else:
                    return {"success": False, "error": "Missing selector"}

            elif action_type == "drag":
                # drag from x1,y1 to x2,y2
                x1 = int(action.get("x1", 0))
                y1 = int(action.get("y1", 0))
                x2 = int(action.get("x2", 0))
                y2 = int(action.get("y2", 0))
                await self.page.mouse.move(x1, y1)
                await self.page.mouse.down()
                await self.page.mouse.move(x2, y2, steps=max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / 10)))
                await self.page.mouse.up()
                return {"success": True}

            else:
                return {"success": False, "error": f"Unknown action: {action_type}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # Real-time pointer queueing API ------------------------------------------------
    def queue_pointer_event(self, action: Dict[str, Any]):
        """Queue a pointer-related action for real-time processing.
        The queue is size 1 and will always keep the most recent event.
        This is non-blocking and safe to call from websocket handler.
        """
        try:
            self._pointer_queue.put_nowait(action)
        except asyncio.QueueFull:
            # Replace the oldest with the newest
            try:
                _ = self._pointer_queue.get_nowait()
            except Exception:
                pass
            try:
                self._pointer_queue.put_nowait(action)
            except Exception:
                pass

    async def _pointer_loop(self):
        """Consume pointer queue and apply events to the page immediately.
        This loop ensures high-frequency pointer updates don't backlog and
        gives more responsive, real-time control (mousemove/mousedown/mouseup/drag/scroll).
        """
        if not self.page:
            # Wait a bit for page to be ready if loop started early
            await asyncio.sleep(0.1)

        try:
            while True:
                try:
                    action = await self._pointer_queue.get()
                    if not action:
                        continue

                    typ = action.get("type")

                    if typ == "mousemove":
                        x = float(action.get("x", 0))
                        y = float(action.get("y", 0))
                        # For real-time, use small steps (1) to move quickly and smoothly
                        try:
                            await self.page.mouse.move(int(x), int(y), steps=1)
                        except Exception:
                            # fallback to single-step move without steps param
                            try:
                                await self.page.mouse.move(int(x), int(y))
                            except Exception:
                                pass
                        # store remote position for smoother subsequent moves
                        try:
                            await self.page.evaluate(f"(x,y) => (window.__remote_mouse_x = x, window.__remote_mouse_y = y)", x, y)
                        except Exception:
                            pass

                    elif typ == "mousedown":
                        button = action.get("button", "left")
                        try:
                            await self.page.mouse.down(button=button)
                        except Exception:
                            try:
                                await self.page.mouse.down()
                            except Exception:
                                pass

                    elif typ == "mouseup":
                        button = action.get("button", "left")
                        try:
                            await self.page.mouse.up(button=button)
                        except Exception:
                            try:
                                await self.page.mouse.up()
                            except Exception:
                                pass

                    elif typ == "drag":
                        x1 = int(action.get("x1", 0))
                        y1 = int(action.get("y1", 0))
                        x2 = int(action.get("x2", 0))
                        y2 = int(action.get("y2", 0))
                        try:
                            await self.page.mouse.move(x1, y1)
                            await self.page.mouse.down()
                            await self.page.mouse.move(x2, y2, steps=max(1, int(max(abs(x2 - x1), abs(y2 - y1)) / 10)))
                            await self.page.mouse.up()
                        except Exception:
                            # best-effort; ignore failures to keep loop running
                            pass

                    elif typ == "scroll":
                        delta_y = int(action.get("deltaY", 0))
                        try:
                            await self.page.mouse.wheel(0, delta_y)
                        except Exception:
                            pass

                    elif typ == "hover_selector":
                        selector = action.get("selector", "")
                        if selector:
                            try:
                                await self.page.hover(selector, timeout=5000)
                            except Exception:
                                pass

                    # yield to event loop briefly to allow other tasks to proceed
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # Protect loop from unexpected errors
                    print(f"✗ Pointer loop error: {e}")
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass


# ======================================================================
# FRAME PROCESSOR
# ======================================================================

class FrameProcessor:
    """Optimized frame processing with Pillow/NumPy"""

    @staticmethod
    def compress_frame(frame_bytes: bytes, quality: int = Config.JPEG_QUALITY) -> bytes:
        """Compress frame using PIL and optional numpy step (kept lightweight)"""
        img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")

        # Optional: downscale to target viewport (already ensured by screenshot clip)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()

    @staticmethod
    def resize_frame(frame_bytes: bytes, width: int, height: int) -> bytes:
        """Resize frame efficiently"""
        img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        img_resized = img.resize((width, height), Image.LANCZOS)

        output = io.BytesIO()
        img_resized.save(output, format="JPEG", quality=Config.JPEG_QUALITY)
        return output.getvalue()


# ======================================================================
# STREAMING MANAGER
# ======================================================================

class StreamManager:
    """Manages WebSocket streaming and optional WebRTC tracks"""

    def __init__(self, browser_manager: BrowserManager):
        self.browser = browser_manager
        self.active_connections: Dict[str, WebSocket] = {}
        self.streaming = False

        # Frame queue holds most recent frames. Small maxsize to avoid backlog.
        self.frame_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)

        # Tasks
        self._capture_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None

        # Lock for active_connections updates
        self._conn_lock = asyncio.Lock()

    async def start(self):
        """Start internal tasks"""
        if self.streaming:
            return
        self.streaming = True
        self._capture_task = asyncio.create_task(self._capture_loop(), name="capture_loop")
        self._broadcast_task = asyncio.create_task(self._broadcast_loop(), name="broadcast_loop")

    async def stop(self):
        """Stop internal tasks"""
        self.streaming = False
        tasks = [t for t in (self._capture_task, self._broadcast_task) if t is not None]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._capture_task = None
        self._broadcast_task = None

    async def connect(self, websocket: WebSocket, client_id: str, mode: str):
        """Connect new client"""
        await websocket.accept()
        async with self._conn_lock:
            self.active_connections[client_id] = websocket
        print(f"✓ Client connected: {client_id} (mode={mode})")

    async def disconnect(self, client_id: str):
        """Disconnect client"""
        async with self._conn_lock:
            ws = self.active_connections.pop(client_id, None)
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
            print(f"✓ Client disconnected: {client_id}")

    async def _capture_loop(self):
        """Continuously capture screenshots at target FPS and put them in the queue.
        If queue is full, replace the oldest entry to avoid backlog (we always want latest frame).
        """
        frame_delay = 1.0 / max(1, Config.FPS)
        try:
            while self.streaming:
                start = time.perf_counter()
                try:
                    frame = await self.browser.screenshot()
                    compressed = FrameProcessor.compress_frame(frame)
                    # If queue is full, remove oldest to keep only latest frames
                    try:
                        self.frame_queue.put_nowait(compressed)
                    except asyncio.QueueFull:
                        try:
                            _ = self.frame_queue.get_nowait()
                        except Exception:
                            pass
                        try:
                            self.frame_queue.put_nowait(compressed)
                        except Exception:
                            pass
                except Exception as e:
                    # capture errors should not kill the loop
                    print(f"✗ Capture error: {e}")

                elapsed = time.perf_counter() - start
                sleep_for = frame_delay - elapsed
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    # if capture is slow, yield a small amount to event loop
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"✗ Capture loop stopped unexpectedly: {e}")

    async def _send_with_timeout(self, client_id: str, websocket: WebSocket, message: str, timeout: float = 0.6):
        """Send a message to a websocket with a short timeout to avoid slow clients blocking."""
        try:
            await asyncio.wait_for(websocket.send_text(message), timeout=timeout)
        except (asyncio.TimeoutError, RuntimeError, ConnectionResetError, WebSocketDisconnect):
            # client is too slow or disconnected: remove it
            await self.disconnect(client_id)
        except Exception:
            await self.disconnect(client_id)

    async def _broadcast_loop(self):
        """Consume frames from queue and broadcast to all connected clients.
        Uses gather to send concurrently and short send timeout to drop slow clients.
        """
        try:
            while self.streaming:
                try:
                    # Get latest frame; if multiple frames queued, consume latest to avoid sending stale frames
                    frame = await self.frame_queue.get()
                    # empty the queue to always use the newest available
                    while not self.frame_queue.empty():
                        try:
                            frame = self.frame_queue.get_nowait()
                        except Exception:
                            break

                    # Prepare message once
                    frame_b64 = base64.b64encode(frame).decode("utf-8")
                    message = json.dumps({"type": "frame", "data": frame_b64})

                    # Send to all clients concurrently (snapshot of connections)
                    async with self._conn_lock:
                        clients = list(self.active_connections.items())

                    if not clients:
                        # No clients, small sleep to avoid busy loop
                        await asyncio.sleep(0.05)
                        continue

                    send_tasks = [self._send_with_timeout(cid, ws, message) for cid, ws in clients]
                    # await all sends but don't fail the loop for individual failures
                    await asyncio.gather(*send_tasks, return_exceptions=True)

                except Exception as e:
                    print(f"✗ Broadcast error: {e}")
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"✗ Broadcast loop stopped unexpectedly: {e}")

    # Optional: server-side WebRTC using aiortc. The endpoint below uses this.
    # A small VideoTrack implementation that pulls frames from the same frame_queue.
    if AIORTC_AVAILABLE:
        class _VideoTrack(MediaStreamTrack):
            kind = "video"

            def __init__(self, parent: "StreamManager"):
                super().__init__()  # don't forget to call the parent ctor
                self.parent = parent
                self.width = Config.VIEWPORT["width"]
                self.height = Config.VIEWPORT["height"]

            async def recv(self):
                # Wait for next frame (with timeout)
                try:
                    frame_bytes = await asyncio.wait_for(self.parent.frame_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # generate a black frame if no frame available
                    img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
                    frame_bytes_io = io.BytesIO()
                    img.save(frame_bytes_io, format="JPEG", quality=Config.JPEG_QUALITY)
                    frame_bytes = frame_bytes_io.getvalue()

                # Decode JPEG to av.VideoFrame
                np_img = np.asarray(Image.open(io.BytesIO(frame_bytes)).convert("RGB"))
                av_frame = av.VideoFrame.from_ndarray(np_img, format="rgb24")
                av_frame.pts = None
                av_frame.time_base = None
                return av_frame


# ======================================================================
# FASTAPI APPLICATION
# ======================================================================

# Global instances
display = VirtualDisplay()
browser_manager = BrowserManager()
stream_manager: Optional[StreamManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    # Startup
    display.start()
    await browser_manager.start()
    global stream_manager
    stream_manager = StreamManager(browser_manager)

    # Start streaming tasks
    await stream_manager.start()

    yield

    # Shutdown
    if stream_manager:
        await stream_manager.stop()
    await browser_manager.stop()
    display.stop()


# Create FastAPI app
app = FastAPI(
    title="Remote Browser Control",
    description="Real-time browser control with WebRTC/WebSocket streaming",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================================
# API ENDPOINTS
# ======================================================================

@app.get("/", response_class=HTMLResponse)
async def get_interface():
    """Serve web interface (slightly extended to send pointer events for realtime hover/hold)"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Remote Browser Control</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #1a1a1a;
            color: #fff;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .header {
            background: #2a2a2a;
            padding: 15px 20px;
            display: flex;
            gap: 10px;
            align-items: center;
            border-bottom: 2px solid #3a3a3a;
        }
        input[type="text"] {
            flex: 1;
            padding: 10px 15px;
            background: #1a1a1a;
            border: 1px solid #3a3a3a;
            border-radius: 5px;
            color: #fff;
            font-size: 14px;
        }
        button {
            padding: 10px 20px;
            background: #0066ff;
            border: none;
            border-radius: 5px;
            color: #fff;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }
        button:hover { background: #0052cc; }
        button:active { transform: scale(0.98); }
        .mode-switch {
            background: #3a3a3a;
            padding: 5px;
            border-radius: 5px;
            display: flex;
            gap: 5px;
        }
        .mode-switch button {
            padding: 8px 15px;
            background: transparent;
            font-size: 12px;
        }
        .mode-switch button.active { background: #0066ff; }
        .viewer {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #000;
            position: relative;
            overflow: hidden;
        }
        canvas {
            max-width: 100%;
            max-height: 100%;
            border: 2px solid #3a3a3a;
            touch-action: none;
            cursor: default;
        }
        .status {
            position: absolute;
            top: 20px;
            right: 20px;
            padding: 8px 15px;
            background: rgba(0, 0, 0, 0.8);
            border-radius: 5px;
            font-size: 12px;
            font-weight: 600;
        }
        .status.connected { color: #00ff88; }
        .status.disconnected { color: #ff4444; }
        .loading {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 18px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="mode-switch">
            <button id="wsBtn" class="active" onclick="switchMode('websocket')">WebSocket</button>
            <button id="rtcBtn" onclick="switchMode('webrtc')">WebRTC</button>
        </div>
        <input type="text" id="urlInput" placeholder="Enter URL..." />
        <button onclick="navigate()">Go</button>
        <button onclick="goBack()">←</button>
        <button onclick="goForward()">→</button>
        <button onclick="refresh()">⟳</button>
    </div>

    <div class="viewer">
        <div class="loading">Connecting...</div>
        <canvas id="canvas"></canvas>
        <div class="status disconnected" id="status">Disconnected</div>
    </div>

    <script>
        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d');
        const status = document.getElementById('status');
        const urlInput = document.getElementById('urlInput');

        let ws = null;
        let mode = 'websocket';
        let clientId = Math.random().toString(36).substr(2, 9);

        // Set canvas size
        canvas.width = 1280;
        canvas.height = 720;

        // Connect WebSocket
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/${clientId}/${mode}`);

            ws.onopen = () => {
                status.textContent = 'Connected';
                status.className = 'status connected';
                document.querySelector('.loading').style.display = 'none';
            };

            ws.onclose = () => {
                status.textContent = 'Disconnected';
                status.className = 'status disconnected';
                setTimeout(connect, 2000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };

            ws.onmessage = async (event) => {
                const msg = JSON.parse(event.data);

                if (msg.type === 'frame') {
                    // Decode and draw frame
                    const img = new Image();
                    img.onload = () => {
                        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    };
                    img.src = 'data:image/jpeg;base64,' + msg.data;
                }
            };
        }

        // Send action
        function sendAction(action) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify(action));
            }
        }

        // Navigation
        function navigate() {
            const url = urlInput.value;
            if (url) sendAction({ type: 'navigate', url });
        }

        function goBack() { sendAction({ type: 'back' }); }
        function goForward() { sendAction({ type: 'forward' }); }
        function refresh() { sendAction({ type: 'refresh' }); }

        // Mode switching
        function switchMode(newMode) {
            mode = newMode;
            document.getElementById('wsBtn').classList.toggle('active', mode === 'websocket');
            document.getElementById('rtcBtn').classList.toggle('active', mode === 'webrtc');
            if (ws) ws.close();
            connect();
        }

        // Pointer events (move/down/up) to support hover & hold
        let isPointerDown = false;
        let lastSent = 0;
        const POINTER_THROTTLE_MS = 16; // ~60Hz cap on outgoing events

        function getCanvasCoords(e) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const y = (e.clientY - rect.top) * (canvas.height / rect.height);
            return { x: Math.round(x), y: Math.round(y) };
        }

        canvas.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            isPointerDown = true;
            const { x, y } = getCanvasCoords(e);
            sendAction({ type: 'mousemove', x, y });
            sendAction({ type: 'mousedown', button: e.button === 2 ? 'right' : 'left' });
        });

        window.addEventListener('pointerup', (e) => {
            if (!isPointerDown) return;
            isPointerDown = false;
            const { x, y } = getCanvasCoords(e);
            sendAction({ type: 'mousemove', x, y });
            sendAction({ type: 'mouseup', button: e.button === 2 ? 'right' : 'left' });
        });

        canvas.addEventListener('pointermove', (e) => {
            e.preventDefault();
            const now = performance.now();
            if (now - lastSent < POINTER_THROTTLE_MS) return;
            lastSent = now;
            const { x, y } = getCanvasCoords(e);
            // Always send mousemove so hover works, even if not pressed
            sendAction({ type: 'mousemove', x, y });
        });

        // Mouse wheel
        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            sendAction({ type: 'scroll', deltaY: e.deltaY });
        });

        // Keyboard events
        urlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') navigate();
        });

        document.addEventListener('keydown', (e) => {
            if (document.activeElement !== urlInput) {
                sendAction({ type: 'key', key: e.key });
            }
        });

        // Start
        connect();
    </script>
</body>
</html>
    """


@app.websocket("/ws/{client_id}/{mode}")
async def websocket_endpoint(websocket: WebSocket, client_id: str, mode: str):
    """WebSocket endpoint for streaming and control.
    - Keeps the existing UI unchanged (client connects to /ws/{id}/{mode}).
    - Server will accept 'mode' but streaming is managed centrally.
    """
    await stream_manager.connect(websocket, client_id, mode)

    try:
        while True:
            # Receive actions from client
            data = await websocket.receive_text()
            action = json.loads(data)

            # For pointer-related actions (high-frequency), queue them for real-time processing
            # instead of awaiting execute_action and replying (reduces latency and avoids backlog).
            if action.get("type") in ("mousemove", "mousedown", "mouseup", "drag", "scroll", "hover_selector"):
                # Queue for immediate processing by BrowserManager's pointer loop.
                browser_manager.queue_pointer_event(action)
                # Do not send a response for high-frequency pointer events to keep round-trips minimal.
                continue

            # Execute other actions synchronously and return result
            result = await browser_manager.execute_action(action)

            # Send result back
            # Keep sending JSON text so UI remains unchanged
            await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        await stream_manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        await stream_manager.disconnect(client_id)


@app.post("/offer")
async def offer(request: Request):
    """Optional WebRTC SDP endpoint.
    Clients that support WebRTC can POST an SDP offer and receive an SDP answer.
    Requires aiortc and av. If not available, returns 501.
    """
    if not AIORTC_AVAILABLE or stream_manager is None:
        raise HTTPException(status_code=501, detail="WebRTC not available on server (missing aiortc/av).")

    params = await request.json()
    sdp = params.get("sdp")
    if not sdp:
        raise HTTPException(status_code=400, detail="Missing 'sdp' in POST body.")

    pc = RTCPeerConnection()
    video_track = stream_manager._VideoTrack(stream_manager)
    pc.addTrack(video_track)

    # Handle ICE connection state changes (cleanup on close)
    @pc.on("iceconnectionstatechange")
    async def on_ice():
        if pc.iceConnectionState == "failed":
            await pc.close()

    # Set remote description and create answer
    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "platform": platform.system(),
        "is_docker": Config.IS_DOCKER,
        "headless": Config.HEADLESS,
        "display": Config.DISPLAY,
        "active_connections": len(stream_manager.active_connections) if stream_manager else 0
    }


# ======================================================================
# MAIN ENTRY POINT
# ======================================================================

if __name__ == "__main__":
    import uvicorn

    # Determine host and port
    host = "0.0.0.0" if Config.IS_DOCKER else "127.0.0.1"
    port = int(os.environ.get("PORT", 7860))  # Hugging Face uses 7860

    print("=" * 60)
    print("🌐 Remote Browser Control System (improved streaming & pointer control)")
    print("=" * 60)
    print(f"Platform: {platform.system()}")
    print(f"Docker: {Config.IS_DOCKER}")
    print(f"Headless: {Config.HEADLESS}")
    print(f"Display: {Config.DISPLAY or 'N/A'}")
    print(f"Server: http://{host}:{port}")
    print("=" * 60)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )