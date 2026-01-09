#!/usr/bin/env python3
"""
Video Downloader & Clipper Web Application
Downloads videos from YouTube, Instagram, TikTok with yt-dlp
Clips videos with FFmpeg and provides in-browser playback
"""

from flask import Flask, render_template_string, request, jsonify, send_file, Response
import yt_dlp
import subprocess
import os
import json
import uuid
from pathlib import Path
import threading
import time

app = Flask(__name__)

# Configuration
DOWNLOAD_DIR = Path("downloads")
CLIPS_DIR = Path("clips")
COOKIES_DIR = Path("cookies")
DOWNLOAD_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)

# Store download progress
download_status = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Downloader & Clipper</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
        }
        .content {
            padding: 30px;
        }
        .section {
            margin-bottom: 30px;
            padding: 25px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        .section h2 {
            color: #667eea;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
        }
        input[type="text"],
        input[type="number"],
        input[type="file"],
        select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus,
        input[type="number"]:focus,
        select:focus {
            outline: none;
            border-color: #667eea;
        }
        button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .progress-container {
            display: none;
            margin-top: 20px;
        }
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin-bottom: 10px;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            width: 0%;
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
        }
        .progress-text {
            color: #666;
            font-size: 14px;
        }
        .video-container {
            display: none;
            margin-top: 20px;
            background: #000;
            border-radius: 10px;
            padding: 10px;
        }
        video {
            width: 100%;
            max-height: 500px;
            border-radius: 8px;
            display: block;
        }
        .video-info {
            color: white;
            padding: 10px;
            font-size: 14px;
        }
        .download-link {
            display: inline-block;
            margin-top: 10px;
            padding: 10px 20px;
            background: #28a745;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            transition: background 0.3s;
        }
        .download-link:hover {
            background: #218838;
        }
        .clip-controls {
            display: none;
            margin-top: 20px;
            padding: 20px;
            background: white;
            border-radius: 10px;
            border: 2px solid #667eea;
        }
        .time-inputs {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 15px;
        }
        .preset-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }
        .preset-btn {
            padding: 8px 16px;
            background: #f0f0f0;
            border: 2px solid #ddd;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            color: #333;
        }
        .preset-btn:hover {
            background: #e0e0e0;
            border-color: #667eea;
        }
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .alert-info {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
        }
        .cookie-info {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
            font-style: italic;
        }
        .clip-section {
            margin-top: 30px;
            padding: 25px;
            background: #f0f4ff;
            border-radius: 10px;
            border: 2px solid #667eea;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 Video Downloader & Clipper</h1>
            <p>Download from YouTube, Instagram, TikTok and create clips</p>
        </div>
        
        <div class="content">
            <!-- Download Section -->
            <div class="section">
                <h2>📥 Download Video</h2>
                
                <div class="form-group">
                    <label>Video URL</label>
                    <input type="text" id="videoUrl" placeholder="Paste YouTube, Instagram, or TikTok URL here">
                </div>
                
                <div class="form-group">
                    <label>Quality</label>
                    <select id="quality">
                        <option value="best">Best Quality (Highest Resolution)</option>
                        <option value="1080p">1080p</option>
                        <option value="720p">720p</option>
                        <option value="480p">480p</option>
                        <option value="360p">360p</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>Cookies File (Optional - for private/age-restricted videos)</label>
                    <input type="file" id="cookiesFile" accept=".txt">
                    <div class="cookie-info">
                        Upload cookies in Netscape format. You can export cookies using browser extensions.
                    </div>
                </div>
                
                <button onclick="downloadVideo()" id="downloadBtn">Download Video</button>
                
                <div class="progress-container" id="progressContainer">
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill">0%</div>
                    </div>
                    <div class="progress-text" id="progressText">Initializing...</div>
                </div>
                
                <div id="alertContainer"></div>
                
                <div class="video-container" id="videoContainer">
                    <video id="videoPlayer" controls></video>
                    <div class="video-info">
                        <strong>Downloaded Video:</strong> <span id="videoFileName"></span>
                    </div>
                    <a href="#" class="download-link" id="downloadLink" download>📥 Download Video File</a>
                </div>
            </div>
            
            <!-- Clip Section -->
            <div class="clip-section" id="clipControls" style="display: none;">
                <h2>✂️ Create Clip</h2>
                
                <div class="preset-buttons">
                    <button class="preset-btn" onclick="setClipDuration(60)">60 seconds</button>
                    <button class="preset-btn" onclick="setClipDuration(30)">30 seconds</button>
                    <button class="preset-btn" onclick="setClipDuration(15)">15 seconds</button>
                    <button class="preset-btn" onclick="setClipDuration(10)">10 seconds</button>
                </div>
                
                <div class="time-inputs">
                    <div class="form-group">
                        <label>Start Time (seconds)</label>
                        <input type="number" id="startTime" value="0" min="0" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>Duration (seconds)</label>
                        <input type="number" id="duration" value="60" min="1" step="0.1">
                    </div>
                </div>
                
                <button onclick="createClip()" id="clipBtn">Create Clip</button>
                
                <div class="progress-container" id="clipProgressContainer">
                    <div class="progress-bar">
                        <div class="progress-fill" id="clipProgressFill">0%</div>
                    </div>
                    <div class="progress-text" id="clipProgressText">Processing...</div>
                </div>
                
                <div class="video-container" id="clipVideoContainer">
                    <video id="clipPlayer" controls></video>
                    <div class="video-info">
                        <strong>Clipped Video:</strong> <span id="clipFileName"></span>
                    </div>
                    <a href="#" class="download-link" id="clipDownloadLink" download>📥 Download Clip</a>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentVideoPath = null;
        let currentVideoFilename = null;
        let downloadTaskId = null;

        function showAlert(message, type) {
            const container = document.getElementById('alertContainer');
            const alert = document.createElement('div');
            alert.className = `alert alert-${type}`;
            alert.textContent = message;
            container.innerHTML = '';
            container.appendChild(alert);
            setTimeout(() => alert.remove(), 5000);
        }

        async function uploadCookies() {
            const fileInput = document.getElementById('cookiesFile');
            if (!fileInput.files.length) return null;
            
            const formData = new FormData();
            formData.append('cookies', fileInput.files[0]);
            
            const response = await fetch('/upload_cookies', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            return data.cookie_file;
        }

        async function downloadVideo() {
            const url = document.getElementById('videoUrl').value.trim();
            const quality = document.getElementById('quality').value;
            
            if (!url) {
                showAlert('Please enter a video URL', 'error');
                return;
            }
            
            const downloadBtn = document.getElementById('downloadBtn');
            const progressContainer = document.getElementById('progressContainer');
            const videoContainer = document.getElementById('videoContainer');
            const clipControls = document.getElementById('clipControls');
            const clipVideoContainer = document.getElementById('clipVideoContainer');
            
            downloadBtn.disabled = true;
            progressContainer.style.display = 'block';
            videoContainer.style.display = 'none';
            clipControls.style.display = 'none';
            clipVideoContainer.style.display = 'none';
            
            try {
                // Upload cookies if provided
                const cookieFile = await uploadCookies();
                
                // Start download
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url, quality, cookie_file: cookieFile})
                });
                
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error || 'Download failed');
                }
                
                downloadTaskId = data.task_id;
                
                // Poll for progress
                checkProgress();
                
            } catch (error) {
                showAlert(error.message, 'error');
                downloadBtn.disabled = false;
                progressContainer.style.display = 'none';
            }
        }

        async function checkProgress() {
            try {
                const response = await fetch(`/progress/${downloadTaskId}`);
                const data = await response.json();
                
                const progressFill = document.getElementById('progressFill');
                const progressText = document.getElementById('progressText');
                
                if (data.status === 'downloading' || data.status === 'processing') {
                    const percent = data.progress || 0;
                    progressFill.style.width = percent + '%';
                    progressFill.textContent = Math.round(percent) + '%';
                    progressText.textContent = data.message || 'Downloading...';
                    setTimeout(checkProgress, 500);
                } else if (data.status === 'completed') {
                    progressFill.style.width = '100%';
                    progressFill.textContent = '100%';
                    progressText.textContent = 'Download complete!';
                    
                    currentVideoPath = data.file_path;
                    currentVideoFilename = data.filename;
                    
                    // Show video player
                    const videoContainer = document.getElementById('videoContainer');
                    const videoPlayer = document.getElementById('videoPlayer');
                    const downloadLink = document.getElementById('downloadLink');
                    const videoFileName = document.getElementById('videoFileName');
                    
                    // Add timestamp to force reload
                    videoPlayer.src = '/video/' + encodeURIComponent(currentVideoFilename) + '?t=' + Date.now();
                    videoPlayer.load();
                    
                    downloadLink.href = '/download_file/' + encodeURIComponent(currentVideoFilename);
                    downloadLink.download = currentVideoFilename;
                    videoFileName.textContent = currentVideoFilename;
                    
                    videoContainer.style.display = 'block';
                    
                    // Show clip controls
                    document.getElementById('clipControls').style.display = 'block';
                    
                    showAlert('Video downloaded successfully!', 'success');
                    document.getElementById('downloadBtn').disabled = false;
                } else if (data.status === 'error') {
                    throw new Error(data.error || 'Download failed');
                }
            } catch (error) {
                showAlert(error.message, 'error');
                document.getElementById('downloadBtn').disabled = false;
                document.getElementById('progressContainer').style.display = 'none';
            }
        }

        function setClipDuration(seconds) {
            document.getElementById('duration').value = seconds;
        }

        async function createClip() {
            if (!currentVideoFilename) {
                showAlert('Please download a video first', 'error');
                return;
            }
            
            const startTime = parseFloat(document.getElementById('startTime').value);
            const duration = parseFloat(document.getElementById('duration').value);
            
            if (isNaN(startTime) || isNaN(duration) || duration <= 0) {
                showAlert('Please enter valid time values', 'error');
                return;
            }
            
            const clipBtn = document.getElementById('clipBtn');
            const clipProgressContainer = document.getElementById('clipProgressContainer');
            const clipVideoContainer = document.getElementById('clipVideoContainer');
            
            clipBtn.disabled = true;
            clipProgressContainer.style.display = 'block';
            clipVideoContainer.style.display = 'none';
            
            const clipProgressFill = document.getElementById('clipProgressFill');
            const clipProgressText = document.getElementById('clipProgressText');
            
            try {
                // Show initial progress
                clipProgressFill.style.width = '10%';
                clipProgressFill.textContent = '10%';
                clipProgressText.textContent = 'Starting FFmpeg...';
                
                const response = await fetch('/clip', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        video_filename: currentVideoFilename,
                        start_time: startTime,
                        duration: duration
                    })
                });
                
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error || 'Clipping failed');
                }
                
                // Simulate progress
                clipProgressFill.style.width = '50%';
                clipProgressFill.textContent = '50%';
                clipProgressText.textContent = 'Processing video...';
                
                await new Promise(resolve => setTimeout(resolve, 500));
                
                clipProgressFill.style.width = '100%';
                clipProgressFill.textContent = '100%';
                clipProgressText.textContent = 'Clip created!';
                
                // Show clip player
                const clipPlayer = document.getElementById('clipPlayer');
                const clipDownloadLink = document.getElementById('clipDownloadLink');
                const clipFileName = document.getElementById('clipFileName');
                
                clipPlayer.src = '/video/' + encodeURIComponent(data.clip_filename) + '?t=' + Date.now();
                clipPlayer.load();
                
                clipDownloadLink.href = '/download_file/' + encodeURIComponent(data.clip_filename);
                clipDownloadLink.download = data.clip_filename;
                clipFileName.textContent = data.clip_filename;
                
                clipVideoContainer.style.display = 'block';
                
                showAlert('Clip created successfully!', 'success');
                clipBtn.disabled = false;
                
            } catch (error) {
                showAlert(error.message, 'error');
                clipBtn.disabled = false;
                clipProgressContainer.style.display = 'none';
            }
        }
    </script>
</body>
</html>
"""

def progress_hook(d, task_id):
    """Hook for yt-dlp to update download progress"""
    if d['status'] == 'downloading':
        if 'total_bytes' in d:
            downloaded = d.get('downloaded_bytes', 0)
            total = d['total_bytes']
            percent = (downloaded / total) * 100
            download_status[task_id] = {
                'status': 'downloading',
                'progress': percent,
                'message': f"Downloading... {percent:.1f}%"
            }
        elif '_percent_str' in d:
            percent_str = d['_percent_str'].strip().replace('%', '')
            try:
                percent = float(percent_str)
                download_status[task_id] = {
                    'status': 'downloading',
                    'progress': percent,
                    'message': f"Downloading... {percent:.1f}%"
                }
            except:
                download_status[task_id] = {
                    'status': 'downloading',
                    'progress': 50,
                    'message': 'Downloading...'
                }
    elif d['status'] == 'finished':
        download_status[task_id] = {
            'status': 'processing',
            'progress': 90,
            'message': 'Processing video...'
        }

def download_video_thread(url, quality, task_id, cookie_file=None):
    """Download video in a separate thread"""
    try:
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s_%(id)s.%(ext)s'),
            'progress_hooks': [lambda d: progress_hook(d, task_id)],
            'merge_output_format': 'mp4',
            'postprocessor_args': ['-loglevel', 'error'],
        }
        
        # Add cookie file if provided
        if cookie_file:
            cookie_path = COOKIES_DIR / cookie_file
            if cookie_path.exists():
                ydl_opts['cookiefile'] = str(cookie_path)
        
        # Adjust quality settings
        if quality != 'best':
            if quality == '1080p':
                ydl_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
            elif quality == '720p':
                ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
            elif quality == '480p':
                ydl_opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
            elif quality == '360p':
                ydl_opts['format'] = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Get just the filename without path
            filename_only = os.path.basename(filename)
            
            download_status[task_id] = {
                'status': 'completed',
                'file_path': filename,
                'filename': filename_only,
                'message': 'Download complete!'
            }
    except Exception as e:
        download_status[task_id] = {
            'status': 'error',
            'error': str(e)
        }

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload_cookies', methods=['POST'])
def upload_cookies():
    """Upload cookies file"""
    try:
        if 'cookies' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})
        
        file = request.files['cookies']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Save with unique name
        cookie_filename = f"{uuid.uuid4().hex}_cookies.txt"
        file.save(COOKIES_DIR / cookie_filename)
        
        return jsonify({'success': True, 'cookie_file': cookie_filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download', methods=['POST'])
def download():
    """Start video download"""
    try:
        data = request.json
        url = data.get('url')
        quality = data.get('quality', 'best')
        cookie_file = data.get('cookie_file')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})
        
        # Generate task ID
        task_id = str(uuid.uuid4())
        download_status[task_id] = {
            'status': 'downloading',
            'progress': 0,
            'message': 'Starting download...'
        }
        
        # Start download in thread
        thread = threading.Thread(
            target=download_video_thread,
            args=(url, quality, task_id, cookie_file)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'task_id': task_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/progress/<task_id>')
def progress(task_id):
    """Get download progress"""
    status = download_status.get(task_id, {
        'status': 'unknown',
        'error': 'Task not found'
    })
    return jsonify(status)

@app.route('/clip', methods=['POST'])
def clip():
    """Create video clip using FFmpeg"""
    try:
        data = request.json
        video_filename = data.get('video_filename')
        start_time = data.get('start_time', 0)
        duration = data.get('duration', 60)
        
        if not video_filename:
            return jsonify({'success': False, 'error': 'Video filename is required'})
        
        # Build full path
        video_path = DOWNLOAD_DIR / video_filename
        
        if not video_path.exists():
            return jsonify({'success': False, 'error': f'Video file not found: {video_filename}'})
        
        # Generate output filename
        input_name = Path(video_filename).stem
        input_ext = Path(video_filename).suffix
        output_filename = f"{input_name}_clip_{int(start_time)}s_{int(duration)}s{input_ext}"
        output_path = CLIPS_DIR / output_filename
        
        # Run FFmpeg with re-encoding for better compatibility
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-ss', str(start_time),
            '-t', str(duration),
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'fast',
            '-y',
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return jsonify({'success': False, 'error': f'FFmpeg error: {result.stderr}'})
        
        if not output_path.exists():
            return jsonify({'success': False, 'error': 'Clip file was not created'})
        
        return jsonify({
            'success': True,
            'clip_path': str(output_path),
            'clip_filename': output_filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/video/<path:filename>')
def serve_video(filename):
    """Serve video file with proper headers for streaming"""
    try:
        # Check in downloads first, then clips
        file_path = DOWNLOAD_DIR / filename
        if not file_path.exists():
            file_path = CLIPS_DIR / filename
        
        if not file_path.exists():
            return "File not found", 404
        
        # Get file size
        file_size = file_path.stat().st_size
        
        # Handle range requests for video streaming
        range_header = request.headers.get('Range')
        if range_header:
            byte_start, byte_end = 0, file_size - 1
            match = range_header.replace('bytes=', '').split('-')
            byte_start = int(match[0]) if match[0] else 0
            byte_end = int(match[1]) if match[1] else byte_end
            
            length = byte_end - byte_start + 1
            
            with open(file_path, 'rb') as f:
                f.seek(byte_start)
                data = f.read(length)
            
            response = Response(
                data,
                206,
                mimetype='video/mp4',
                direct_passthrough=True
            )
            response.headers.add('Content-Range', f'bytes {byte_start}-{byte_end}/{file_size}')
            response.headers.add('Accept-Ranges', 'bytes')
            response.headers.add('Content-Length', str(length))
            return response
        
        # Regular request
        return send_file(
            file_path,
            mimetype='video/mp4',
            as_attachment=False
        )
    except Exception as e:
        return str(e), 500

@app.route('/download_file/<path:filename>')
def download_file(filename):
    """Download video file"""
    try:
        # Check in downloads first, then clips
        file_path = DOWNLOAD_DIR / filename
        if not file_path.exists():
            file_path = CLIPS_DIR / filename
        
        if not file_path.exists():
            return "File not found", 404
        
        return send_file(
            file_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🎬 Video Downloader & Clipper Server Starting...")
    print("="*60)
    print("\n📋 Requirements:")
    print("   - yt-dlp: pip install yt-dlp")
    print("   - Flask: pip install flask")
    print("   ✓ Create clips with FFmpeg")
    print("   ✓ In-browser video player")
    print("\n" + "="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)