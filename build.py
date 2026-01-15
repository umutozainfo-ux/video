import os
import sys
import subprocess
import time
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_command(cmd, name):
    logger.info(f"Running: {name}...")
    try:
        subprocess.run(cmd, check=True, shell=True)
        logger.info(f"✅ {name} completed.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ {name} failed: {e}")
        return False

def build():
    logger.info("🚀 Starting AG Studio Build Process...")
    
    # 1. Environment Check
    logger.info("Checking dependencies...")
    if not run_command("ffmpeg -version", "FFmpeg check"):
        logger.warning("FFmpeg not found! Please install FFmpeg for video processing.")

    # 2. Database Initialization
    logger.info("Initializing Database...")
    from database import init_database
    init_database()
    from database.models import User
    User.ensure_admin()
    logger.info("✅ Database ready.")

    # 3. PWA Version Update
    logger.info("Updating PWA Service Worker version...")
    sw_path = os.path.join("static", "sw.js")
    if os.path.exists(sw_path):
        with open(sw_path, "r") as f:
            content = f.read()
        
        # Replace version string with a new timestamp
        new_version = f"ag-video-editor-v{int(time.time())}"
        import re
        content = re.sub(r"const CACHE_NAME = 'ag-video-editor-v\d+';", f"const CACHE_NAME = '{new_version}';", content)
        
        with open(sw_path, "w") as f:
            f.write(content)
        logger.info(f"✅ PWA version updated to {new_version}")

    # 4. Pre-download Whisper Model (Optional but recommended for speed)
    logger.info("Checking Whisper models...")
    try:
        from faster_whisper import WhisperModel
        # This will download the model to the local cache if not present
        WhisperModel("tiny", device="cpu", compute_type="int8")
        logger.info("✅ Whisper 'tiny' model verified.")
    except Exception as e:
        logger.warning(f"Could not pre-download Whisper model: {e}")
        
    # 5. Download Fonts (Pro Captions)
    logger.info("Downloading Pro Fonts...")
    try:
        import requests
        # Use local 'fonts' directory for portability
        font_dir = os.path.join(os.getcwd(), "fonts")
        os.makedirs(font_dir, exist_ok=True)
        
        fonts = {
            "Montserrat-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf",
            "Lobster-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/lobster/Lobster-Regular.ttf",
            "Poppins-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
            "Bangers-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
            "LuckiestGuy-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/luckiestguy/LuckiestGuy-Regular.ttf",
            "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
            "Oswald-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/oswald/static/Oswald-Bold.ttf",
            "BebasNeue-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
            "TitanOne-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/titanone/TitanOne-Regular.ttf",
        }
        
        for name, url in fonts.items():
            path = os.path.join(font_dir, name)
            if not os.path.exists(path):
                logger.info(f"Downloading {name}...")
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        with open(path, 'wb') as f:
                            f.write(r.content)
                except Exception as ex:
                    logger.warning(f"Failed to download {name}: {ex}")
        
        logger.info("✅ Fonts downloaded to local 'fonts' directory.")
            
    except Exception as e:
        logger.warning(f"Font download error: {e}")

    logger.info("🎉 Build successful! You can now run the app with 'python app.py'")

if __name__ == "__main__":
    build()
