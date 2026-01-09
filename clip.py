"""
video_clipper_app.py

Web-based TikTok-style video cropper + clipper using Flask + FFmpeg.

Features:
- Upload a video via a simple web UI.
- Crop/scale video to TikTok aspect ratio (9:16, default 1080x1920).
- Split the (resized) video into multiple clips of configurable length (default 60s).
- Download individual clips or all clips as a ZIP.
- Background processing with a simple status API and basic FFmpeg stderr logging.

Requirements:
- Python 3.8+
- FFmpeg and ffprobe on PATH
- Python packages: flask, werkzeug

Run:
    pip install flask werkzeug
    python video_clipper_app.py
    open http://127.0.0.1:5000
"""

import os
import subprocess
import threading
import shutil
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_file
from werkzeug.utils import secure_filename

# Configuration
UPLOAD_FOLDER = Path("uploads")
OUTPUT_FOLDER = Path("outputs")
MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB
ALLOWED_EXTENSIONS = None  # accept any video mime via browser; further validation by ffmpeg

# Ensure dirs exist
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['OUTPUT_FOLDER'] = str(OUTPUT_FOLDER)

# In-memory job status store (for demo). For production use persistent store.
processing_status = {}


# -------------------------
# Helpers: ffmpeg + ffprobe
# -------------------------
def check_ffmpeg_installed() -> bool:
    """Return True if ffmpeg (and ffprobe) are available on PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def run_ffmpeg(cmd: list, timeout: int = 600) -> tuple[bool, str]:
    """Run ffmpeg command (list-form). Return (ok, stderr_text)."""
    try:
        # Log command to console for debugging
        print("Running ffmpeg:", " ".join(map(str, cmd)))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            # ffmpeg often logs progress to stderr; return that for debugging
            return True, proc.stderr or proc.stdout or ""
        else:
            return False, proc.stderr or proc.stdout or f"ffmpeg exited {proc.returncode}"
    except subprocess.CalledProcessError as e:
        return False, e.stderr or str(e)
    except Exception as e:
        return False, str(e)


def get_video_duration(path: str | Path) -> float | None:
    """Return duration in seconds using ffprobe, or None on error."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(proc.stdout.strip())
    except Exception as e:
        print("get_video_duration error:", e)
        return None


def get_video_dimensions(path: str | Path) -> dict | None:
    """Return dict {'width': int, 'height': int} for primary video stream, or None."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(path)
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = proc.stdout.strip()
        if "x" not in out:
            return None
        w, h = out.split("x")
        return {"width": int(w), "height": int(h)}
    except Exception as e:
        print("get_video_dimensions error:", e)
        return None


def calculate_crop_dimensions(original_width: int, original_height: int, target_ratio: float = 9 / 16) -> dict:
    """Compute centered crop rectangle (width, height, x, y) to match target_ratio."""
    current_ratio = original_width / original_height
    if current_ratio > target_ratio:
        # too wide -> crop left/right
        new_width = int(original_height * target_ratio)
        new_height = original_height
        x = (original_width - new_width) // 2
        y = 0
    else:
        # too tall -> crop top/bottom
        new_width = original_width
        new_height = int(original_width / target_ratio)
        x = 0
        y = (original_height - new_height) // 2
    return {"width": new_width, "height": new_height, "x": x, "y": y}


# -------------------------
# Processing functions
# -------------------------
def resize_to_tiktok_format(input_path: str | Path, output_path: str | Path, target_width: int = 1080,
                            target_height: int = 1920, job_id: str | None = None) -> tuple[bool, str]:
    """
    Crop and scale input_path to 9:16 (default 1080x1920).
    Returns (True, stderr) or (False, stderr).
    """
    dims = get_video_dimensions(input_path)
    if not dims:
        return False, "Could not determine input video dimensions"

    crop = calculate_crop_dimensions(dims['width'], dims['height'], target_ratio=9 / 16)

    vf = f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']},scale={target_width}:{target_height}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    ok, stderr = run_ffmpeg(cmd)
    if not ok:
        # attach job id for easier debugging in logs
        full_err = f"{stderr}"
        if job_id:
            print(f"[{job_id}] resize ffmpeg stderr:\n{full_err}")
        return False, full_err
    return True, stderr or ""


def create_clips_from_video(video_path: str | Path, output_dir: str | Path, clip_duration: float = 60.0,
                            job_id: str | None = None) -> tuple[bool, list | str]:
    """
    Split video_path into multiple clips of length clip_duration seconds.
    Returns (True, clips_list) on success where clips_list is list of dicts,
    otherwise (False, error_message).
    """
    total_duration = get_video_duration(video_path)
    if total_duration is None:
        return False, "Could not determine video duration"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clips = []
    clip_number = 1
    current_time = 0.0

    # We'll use -ss before -i (fast seek). If frame-accurate extraction is required, use -ss after -i.
    while current_time < total_duration - 1e-6:
        end_time = min(current_time + float(clip_duration), total_duration)
        duration_actual = end_time - current_time

        output_filename = f"clip_{clip_number:03d}.mp4"  # no stray spaces
        output_path = output_dir / output_filename

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{current_time:.3f}",
            "-i", str(video_path),
            "-t", f"{duration_actual:.3f}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

        ok, stderr = run_ffmpeg(cmd)
        if not ok:
            # some builds/inputs might refuse to pick muxer if filename is weird;
            # try forcing mp4 format explicitly as a fallback
            if "Unable to choose an output format" in stderr or "use a standard extension" in stderr:
                cmd_forced = cmd[:-1] + ["-f", "mp4", str(output_path)]
                ok2, stderr2 = run_ffmpeg(cmd_forced)
                if not ok2:
                    msg = f"FFmpeg failed (forced mp4):\n{stderr2}"
                    if job_id:
                        print(f"[{job_id}] clip ffmpeg stderr (forced):\n{stderr2}")
                    return False, msg
                else:
                    stderr = stderr2
            else:
                msg = f"FFmpeg failed:\n{stderr}"
                if job_id:
                    print(f"[{job_id}] clip ffmpeg stderr:\n{stderr}")
                return False, msg

        clips.append({
            "filename": output_filename,
            "path": str(output_path),
            "start_time": current_time,
            "end_time": end_time,
            "duration": duration_actual,
            "clip_number": clip_number
        })

        current_time = end_time
        clip_number += 1

    return True, clips


def process_video_complete(job_id: str, upload_path: str, clip_duration: float):
    """Background job: resize then clip; updates processing_status[job_id]."""
    try:
        processing_status[job_id]["status"] = "processing"
        processing_status[job_id]["message"] = "Resizing video to TikTok format..."
        processing_status[job_id]["progress"] = 10

        job_dir = Path(app.config['OUTPUT_FOLDER']) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        resized_path = job_dir / "resized_video.mp4"
        ok, msg = resize_to_tiktok_format(upload_path, resized_path, job_id=job_id)
        if not ok:
            processing_status[job_id]["status"] = "error"
            processing_status[job_id]["message"] = f"Resize failed: {msg}"
            processing_status[job_id]["progress"] = 0
            return

        processing_status[job_id]["message"] = "Creating clips..."
        processing_status[job_id]["progress"] = 60

        clips_dir = job_dir / "clips"
        ok, clips_or_err = create_clips_from_video(resized_path, clips_dir, clip_duration, job_id=job_id)
        if not ok:
            processing_status[job_id]["status"] = "error"
            processing_status[job_id]["message"] = f"Clipping failed: {clips_or_err}"
            processing_status[job_id]["progress"] = 0
            return

        processing_status[job_id]["status"] = "completed"
        processing_status[job_id]["message"] = f"Successfully created {len(clips_or_err)} clips"
        processing_status[job_id]["progress"] = 100
        processing_status[job_id]["clips"] = [
            {
                "number": c["clip_number"],
                "filename": c["filename"],
                "duration": round(c["duration"], 2),
                "start_time": round(c["start_time"], 2),
                "end_time": round(c["end_time"], 2)
            } for c in clips_or_err
        ]
        processing_status[job_id]["clips_dir"] = str(clips_dir)
        processing_status[job_id]["job_dir"] = str(job_dir)
    except Exception as e:
        processing_status[job_id]["status"] = "error"
        processing_status[job_id]["message"] = f"Processing error: {e}"
        processing_status[job_id]["progress"] = 0


# -------------------------
# Flask routes + UI
# -------------------------
HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>TikTok Video Clipper</title>
  <style>
    body{font-family:system-ui,Segoe UI,Roboto,Arial;margin:20px;background:linear-gradient(135deg,#667eea,#764ba2);color:#222}
    .card{background:#fff;padding:24px;border-radius:12px;max-width:900px;margin:24px auto;box-shadow:0 10px 30px rgba(0,0,0,0.15)}
    h1{margin-bottom:8px}
    .row{display:flex;gap:12px;flex-wrap:wrap}
    input[type=file],input[type=number]{width:100%;padding:10px;border-radius:8px;border:1px solid #ddd}
    button{padding:12px 18px;border-radius:8px;border:0;cursor:pointer}
    .primary{background:#667eea;color:#fff}
    .secondary{background:#eee}
    .clips{margin-top:18px}
    .clip{display:flex;justify-content:space-between;padding:10px;background:#f7f7f7;border-radius:8px;margin-bottom:8px}
    .alert{padding:10px;border-radius:8px;margin-top:12px}
    .alert.error{background:#fee;color:#900}
    .alert.success{background:#efe;color:#060}
  </style>
</head>
<body>
  <div class="card">
    <h1>🎬 TikTok Video Clipper</h1>
    <p>Crop to 9:16 (TikTok) and split into clips. FFmpeg must be installed on the server.</p>

    <div id="ffmpegWarning" style="display:none" class="alert error">FFmpeg not found on server. Install ffmpeg.</div>

    <form id="uploadForm">
      <div class="row">
        <div style="flex:1">
          <label>Video file</label>
          <input id="videoFile" type="file" accept="video/*" required />
        </div>
        <div style="width:160px">
          <label>Clip length (s)</label>
          <input id="duration" type="number" value="60" min="5" max="600" />
        </div>
      </div>

      <div style="margin-top:12px" class="row">
        <button id="submitBtn" class="primary" type="submit">Process Video</button>
        <button type="reset" class="secondary">Clear</button>
      </div>
    </form>

    <div id="status" style="display:none;margin-top:16px">
      <div id="statusMessage">Starting...</div>
      <div id="alerts"></div>
      <div class="clips" id="clipsContainer"></div>
      <div style="margin-top:10px">
        <button id="downloadAll" class="primary" style="display:none">Download All (ZIP)</button>
      </div>
    </div>
  </div>

  <script>
    let jobId = null;
    async function checkFFmpeg(){
      const r = await fetch('/api/check-ffmpeg');
      const j = await r.json();
      if(!j.installed){
        document.getElementById('ffmpegWarning').style.display = 'block';
        document.getElementById('submitBtn').disabled = true;
      }
    }
    checkFFmpeg();

    document.getElementById('uploadForm').addEventListener('submit', async (ev)=>{
      ev.preventDefault();
      const file = document.getElementById('videoFile').files[0];
      const duration = Number(document.getElementById('duration').value) || 60;
      if(!file) return alert('Select a file');
      const fd = new FormData();
      fd.append('video', file);
      fd.append('duration', String(duration));
      document.getElementById('submitBtn').textContent = 'Uploading...';
      document.getElementById('submitBtn').disabled = true;
      const rsp = await fetch('/api/process', {method:'POST', body: fd});
      const json = await rsp.json();
      if(!json.success){
        alert(json.message || 'Upload failed');
        document.getElementById('submitBtn').disabled = false;
        document.getElementById('submitBtn').textContent = 'Process Video';
        return;
      }
      jobId = json.job_id;
      document.getElementById('status').style.display = 'block';
      pollStatus();
    });

    function pollStatus(){
      const iv = setInterval(async ()=>{
        const r = await fetch('/api/status/' + jobId);
        if(r.status !== 200){
          clearInterval(iv);
          return;
        }
        const s = await r.json();
        document.getElementById('statusMessage').textContent = s.message || s.status;
        const alerts = document.getElementById('alerts');
        alerts.innerHTML = '';
        if(s.status === 'error') alerts.innerHTML = '<div class="alert error">❌ ' + (s.message||'Error') + '</div>';
        if(s.status === 'completed') alerts.innerHTML = '<div class="alert success">✅ ' + (s.message||'Completed') + '</div>';

        const clipsContainer = document.getElementById('clipsContainer');
        clipsContainer.innerHTML = '';
        if(s.clips && s.clips.length){
          s.clips.forEach(c=>{
            const div = document.createElement('div');
            div.className = 'clip';
            div.innerHTML = '<div><strong>Clip ' + c.number + '</strong><div>' + c.duration + 's (' + c.start_time + '-' + c.end_time + ')</div></div>' +
                            '<div><a href="/api/download/' + jobId + '/clip/' + encodeURIComponent(c.filename) + '">Download</a></div>';
            clipsContainer.appendChild(div);
          });
          document.getElementById('downloadAll').style.display = 'inline-block';
          document.getElementById('downloadAll').onclick = ()=> location.href = '/api/download/' + jobId + '/all';
        } else {
          document.getElementById('downloadAll').style.display = 'none';
        }

        if(s.status === 'completed' || s.status === 'error'){
          clearInterval(iv);
          document.getElementById('submitBtn').disabled = false;
          document.getElementById('submitBtn').textContent = 'Process Video';
        }
      }, 1500);
    }
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/check-ffmpeg", methods=["GET"])
def api_check_ffmpeg():
    return jsonify({"installed": check_ffmpeg_installed()})


@app.route("/api/process", methods=["POST"])
def api_process():
    # basic validations
    if "video" not in request.files:
        return jsonify({"success": False, "message": "No video file provided"}), 400

    video_file = request.files["video"]
    if video_file.filename == "":
        return jsonify({"success": False, "message": "No video file selected"}), 400

    try:
        clip_duration = float(request.form.get("duration", 60))
    except Exception:
        clip_duration = 60.0

    if clip_duration < 1 or clip_duration > 3600:
        return jsonify({"success": False, "message": "Invalid clip duration"}), 400

    # create job id
    job_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_") + os.urandom(4).hex()

    # save uploaded file
    filename = secure_filename(video_file.filename)
    upload_path = UPLOAD_FOLDER / f"{job_id}_{filename}"
    video_file.save(upload_path)

    # init status
    processing_status[job_id] = {
        "status": "started",
        "message": "Queued for processing",
        "progress": 0,
        "clips": []
    }

    # start background thread
    thread = threading.Thread(target=process_video_complete, args=(job_id, str(upload_path), clip_duration))
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id})


@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    if job_id not in processing_status:
        return jsonify({"status": "unknown", "message": "Job not found"}), 404
    return jsonify(processing_status[job_id])


@app.route("/api/download/<job_id>/clip/<filename>", methods=["GET"])
def api_download_clip(job_id, filename):
    if job_id not in processing_status:
        return "Job not found", 404
    clips_dir = processing_status[job_id].get("clips_dir")
    if not clips_dir:
        return "Clips not available", 404
    filepath = Path(clips_dir) / filename
    if not filepath.exists():
        return "Clip not found", 404
    return send_file(str(filepath), as_attachment=True, download_name=filename, mimetype="video/mp4")


@app.route("/api/download/<job_id>/all", methods=["GET"])
def api_download_all(job_id):
    if job_id not in processing_status:
        return "Job not found", 404
    clips_dir = processing_status[job_id].get("clips_dir")
    job_dir = processing_status[job_id].get("job_dir")
    if not clips_dir or not job_dir:
        return "Clips not available", 404

    clips_dir = Path(clips_dir)
    job_dir = Path(job_dir)
    if not clips_dir.exists():
        return "Clips not found", 404

    zip_base = job_dir / "clips"
    # make_archive expects base_name without extension
    archive_path = shutil.make_archive(str(zip_base), "zip", root_dir=str(clips_dir))
    # send the created zip
    return send_file(archive_path, as_attachment=True, download_name=f"tiktok_clips_{job_id}.zip", mimetype="application/zip")


# -------------------------
# Run server
# -------------------------
if __name__ == "__main__":
    print("=" * 40)
    print("TikTok Video Clipper")
    print("FFmpeg installed:", check_ffmpeg_installed())
    print("Uploads:", UPLOAD_FOLDER.resolve())
    print("Outputs:", OUTPUT_FOLDER.resolve())
    print("Open http://127.0.0.1:5000")
    print("=" * 40)
    app.run(host="127.0.0.1", port=5000, debug=True)