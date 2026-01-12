# Video Downloader & Converter

A powerful Flask-based web application to download videos from YouTube, TikTok, Instagram, and direct URLs, then convert them to TikTok format (9:16 aspect ratio) with optimized quality for web playback.

## Features

- 🎬 **Multi-Platform Support**: Download from YouTube, TikTok, Instagram, and direct video URLs
- 📱 **TikTok Format Conversion**: Automatically converts videos to 9:16 aspect ratio (720x1280)
- 🎥 **Optimized Encoding**: Medium quality videos optimized for web streaming with H.264 codec
- 🌐 **Smooth Playback**: Progressive streaming support for smooth playback even on slow internet
- 💻 **Modern UI**: Beautiful, responsive interface with real-time progress tracking
- ⚡ **Fast Processing**: Efficient video processing with optimized FFmpeg settings

## Requirements

- Python 3.8+
- FFmpeg (must be installed and available in PATH)

### Installing FFmpeg

**Windows:**
1. Download from https://ffmpeg.org/download.html
2. Extract and add to PATH, or use: `choco install ffmpeg`

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt-get install ffmpeg
```

## Installation

1. Clone or download this repository
2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the Flask server:
```bash
python app.py
```

2. Open your browser and navigate to:
```
http://localhost:5000
```

3. Paste a video URL (YouTube, TikTok, Instagram, or direct URL)
4. Click "Download & Convert"
5. Wait for processing to complete
6. Preview and download your converted video

## How It Works

1. **Download**: Uses `yt-dlp` to download videos from various platforms in medium quality (720p max)
2. **Process**: Uses FFmpeg to:
   - Convert aspect ratio to 9:16 (TikTok format)
   - Encode with H.264 codec for web compatibility
   - Optimize for streaming with faststart flag
   - Maintain good quality with CRF 23
3. **Serve**: Provides optimized video files ready for web playback

## Technical Details

- **Video Codec**: H.264 (libx264) for maximum compatibility
- **Audio Codec**: AAC at 128kbps
- **Resolution**: 720x1280 (9:16 aspect ratio)
- **Quality**: CRF 23 (medium-high quality)
- **Streaming**: Faststart enabled for progressive download

## Notes

- Videos are processed in the background
- Processed videos are stored in the `processed/` folder
- Temporary files are automatically cleaned up
- The server handles multiple concurrent requests

## Troubleshooting

- **FFmpeg not found**: Make sure FFmpeg is installed and in your PATH
- **Download fails**: Check your internet connection and verify the URL is valid
- **Processing slow**: Large videos take more time to process

## License

MIT License - Feel free to use and modify as needed.
