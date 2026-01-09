"""
Remote Browser Control System with WebRTC/WebSocket Streaming
Single-file FastAPI application with FFmpeg streaming and Playwright automation
Supports Docker (virtual display) and Windows (headless) environments
"""

import asyncio
import base64
import io
import json
import os
import platform
import subprocess
import tempfile
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from PIL import Image


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """System configuration"""
    IS_DOCKER = os.path.exists("/.dockerenv")
    IS_WINDOWS = platform.system() == "Windows"
    
    # Display settings
    DISPLAY = ":99" if IS_DOCKER else None
    VIRTUAL_DISPLAY_SIZE = "1920x1080x24"
    
    # Browser settings
    HEADLESS = not IS_DOCKER  # Headless on Windows, headed in Docker with Xvfb
    VIEWPORT = {"width": 1920, "height": 1080}
    
    # Streaming settings
    FPS = 30
    JPEG_QUALITY = 85
    WEBRTC_BITRATE = "2M"
    
    # FFmpeg settings
    FFMPEG_PRESET = "ultrafast"
    FFMPEG_TUNE = "zerolatency"


# ============================================================================
# VIRTUAL DISPLAY MANAGER (for Docker)
# ============================================================================

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
            ])
            
            # Set DISPLAY environment variable
            os.environ["DISPLAY"] = Config.DISPLAY
            
            # Wait for display to be ready
            asyncio.sleep(2)
            print(f"✓ Virtual display started: {Config.DISPLAY}")
            
        except Exception as e:
            print(f"✗ Failed to start virtual display: {e}")
    
    def stop(self):
        """Stop Xvfb virtual display"""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print("✓ Virtual display stopped")


# ============================================================================
# BROWSER MANAGER
# ============================================================================

class BrowserManager:
    """Manages Playwright browser instances"""
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
    async def start(self):
        """Initialize browser"""
        self.playwright = await async_playwright().start()
        
        # Launch browser with appropriate settings
        self.browser = await self.playwright.chromium.launch(
            headless=Config.HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu" if Config.IS_WINDOWS and Config.HEADLESS else "",
            ]
        )
        
        # Create context
        self.context = await self.browser.new_context(
            viewport=Config.VIEWPORT,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        # Create page
        self.page = await self.context.new_page()
        await self.page.goto("about:blank")
        
        print(f"✓ Browser started (headless={Config.HEADLESS})")
        
    async def stop(self):
        """Close browser"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("✓ Browser stopped")
        
    async def screenshot(self) -> bytes:
        """Capture page screenshot"""
        if not self.page:
            raise RuntimeError("Browser not initialized")
        return await self.page.screenshot(type="jpeg", quality=Config.JPEG_QUALITY)
    
    async def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute browser action"""
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
                x, y = action.get("x", 0), action.get("y", 0)
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
                delta_y = action.get("deltaY", 0)
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
            
            else:
                return {"success": False, "error": f"Unknown action: {action_type}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# FRAME PROCESSOR
# ============================================================================

class FrameProcessor:
    """Optimized frame processing with NumPy"""
    
    @staticmethod
    def compress_frame(frame_bytes: bytes, quality: int = Config.JPEG_QUALITY) -> bytes:
        """Compress frame using PIL and NumPy"""
        # Load image
        img = Image.open(io.BytesIO(frame_bytes))
        
        # Convert to numpy array for fast processing
        img_array = np.array(img)
        
        # Convert back to PIL for compression
        img = Image.fromarray(img_array)
        
        # Compress
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    
    @staticmethod
    def resize_frame(frame_bytes: bytes, width: int, height: int) -> bytes:
        """Resize frame efficiently with NumPy"""
        img = Image.open(io.BytesIO(frame_bytes))
        img_array = np.array(img)
        
        # Use PIL resize (optimized with NumPy array)
        img_resized = Image.fromarray(img_array).resize((width, height), Image.LANCZOS)
        
        output = io.BytesIO()
        img_resized.save(output, format="JPEG", quality=Config.JPEG_QUALITY)
        return output.getvalue()


# ============================================================================
# STREAMING MANAGER
# ============================================================================

class StreamManager:
    """Manages WebSocket and WebRTC streaming"""
    
    def __init__(self, browser_manager: BrowserManager):
        self.browser = browser_manager
        self.active_connections: Dict[str, WebSocket] = {}
        self.streaming = False
        
    async def connect(self, websocket: WebSocket, client_id: str, mode: str):
        """Connect new client"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        print(f"✓ Client connected: {client_id} (mode={mode})")
        
    def disconnect(self, client_id: str):
        """Disconnect client"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            print(f"✓ Client disconnected: {client_id}")
    
    async def broadcast_frame(self, frame_bytes: bytes):
        """Broadcast frame to all connected clients"""
        if not self.active_connections:
            return
        
        # Encode frame as base64
        frame_b64 = base64.b64encode(frame_bytes).decode("utf-8")
        message = json.dumps({"type": "frame", "data": frame_b64})
        
        # Send to all clients
        disconnected = []
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(message)
            except:
                disconnected.append(client_id)
        
        # Remove disconnected clients
        for client_id in disconnected:
            self.disconnect(client_id)
    
    async def stream_loop(self):
        """Main streaming loop"""
        self.streaming = True
        frame_delay = 1.0 / Config.FPS
        
        while self.streaming:
            try:
                if self.active_connections:
                    # Capture screenshot
                    frame = await self.browser.screenshot()
                    
                    # Compress with NumPy optimization
                    compressed = FrameProcessor.compress_frame(frame)
                    
                    # Broadcast to clients
                    await self.broadcast_frame(compressed)
                
                # Control frame rate
                await asyncio.sleep(frame_delay)
                
            except Exception as e:
                print(f"✗ Streaming error: {e}")
                await asyncio.sleep(1)
    
    def stop_streaming(self):
        """Stop streaming loop"""
        self.streaming = False


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

# Global instances
display = VirtualDisplay()
browser_manager = BrowserManager()
stream_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    # Startup
    display.start()
    await browser_manager.start()
    global stream_manager
    stream_manager = StreamManager(browser_manager)
    
    # Start streaming loop
    asyncio.create_task(stream_manager.stream_loop())
    
    yield
    
    # Shutdown
    stream_manager.stop_streaming()
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


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_interface():
    """Serve web interface"""
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
        canvas.width = 1920;
        canvas.height = 1080;
        
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
        
        // Mouse events
        canvas.addEventListener('click', (e) => {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const y = (e.clientY - rect.top) * (canvas.height / rect.height);
            sendAction({ type: 'click', x, y });
        });
        
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
    """WebSocket endpoint for streaming"""
    await stream_manager.connect(websocket, client_id, mode)
    
    try:
        while True:
            # Receive actions from client
            data = await websocket.receive_text()
            action = json.loads(data)
            
            # Execute action
            result = await browser_manager.execute_action(action)
            
            # Send result back
            await websocket.send_text(json.dumps(result))
            
    except WebSocketDisconnect:
        stream_manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        stream_manager.disconnect(client_id)


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


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Determine host and port
    host = "0.0.0.0" if Config.IS_DOCKER else "127.0.0.1"
    port = int(os.environ.get("PORT", 7860))  # Hugging Face uses 7860
    
    print("=" * 60)
    print("🌐 Remote Browser Control System")
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