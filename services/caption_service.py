import os
import threading
import logging
import subprocess
import tempfile
from typing import List
from faster_whisper import WhisperModel
from config import Config
from utils.helpers import thread_safe_status_update, retry_on_failure

logger = logging.getLogger(__name__)
whisper_models = {}

def get_whisper_model(size: str) -> WhisperModel:
    """Load and cache faster-whisper model."""
    size = size or Config.WHISPER_MODEL_DEFAULT
    if size not in whisper_models:
        whisper_models[size] = WhisperModel(size, device="auto", compute_type="auto")
    return whisper_models[size]

def write_srt(segments, path: str, word_level: bool):
    """Write segments/words to SRT file."""
    def format_ts(t):
        hrs = int(t // 3600)
        mins = int((t % 3600) // 60)
        secs = int(t % 60)
        millis = int((t - int(t)) * 1000)
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

    lines: List[str] = []
    idx = 1
    if word_level:
        for seg in segments:
            for w in seg.words:
                start, end, text = w.start, w.end, w.word.strip()
                if not text:
                    continue
                lines.append(str(idx))
                lines.append(f"{format_ts(start)} --> {format_ts(end)}")
                lines.append(text.upper())
                lines.append("")
                idx += 1
    else:
        for seg in segments:
            start, end, text = seg.start, seg.end, seg.text.strip()
            if not text:
                continue
            lines.append(str(idx))
            lines.append(f"{format_ts(start)} --> {format_ts(end)}")
            lines.append(text.upper())
            lines.append("")
            idx += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def to_ass_color(hex_color):
    """Convert hex (#RRGGBB) to ASS color format (&HAABBGGRR)."""
    if not hex_color: return "&H00FFFFFF"
    hex_val = hex_color.replace('#', '')
    if len(hex_val) == 6:
        r, g, b = hex_val[:2], hex_val[2:4], hex_val[4:6]
        return f"&H00{b}{g}{r}"
    return "&HA0000000" # Default semi-transparent black for backgrounds

def srt_to_ass_time(srt_time):
    """Convert SRT timestamp (00:00:00,000) to ASS timestamp (0:00:00.00)."""
    try:
        h, m, s = srt_time.split(':')
        s_sec, s_ms = s.split(',')
        h_int = int(h)
        ms_cs = s_ms[:2]
        return f"{h_int}:{m}:{s_sec}.{ms_cs}"
    except:
        return "0:00:00.00"

def create_ass_file(srt_path, style):
    """Convert SRT to ASS with embedded styling."""
    font_name = style.get('fontName', 'Arial Black')
    font_size = style.get('fontSize', 32)
    primary = to_ass_color(style.get('primaryColor', '#ffffff'))
    outline = to_ass_color(style.get('outlineColor', '#000000'))
    back = to_ass_color(style.get('backgroundColor', '#000000'))
    
    # ASS Standard Alignment: 1-3 (Bottom), 4-6 (Middle), 7-9 (Top)
    # Target Center usually: 2=Bottom Center, 5=Middle Center, 8=Top Center
    ui_alignment = str(style.get('alignment', '2'))
    mapping = {'2': '2', '10': '5', '6': '8'}
    ass_alignment = mapping.get(ui_alignment, '2')

    border_style = style.get('borderStyle', '1')
    # If using Outline style (1), Outline is width. If Box (3), BackColour is the box.
    outline_val = 2 if border_style == '1' else 0
    shadow_val = 0 # Usually keep shadow low for clean viral look
    
    # Viral fonts often need Bold forced in ASS
    bold = 1
    
    # Mapping certain common viral fonts to system defaults if they might be missing
    # But we try the requested one first in the style string.
    
    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1280",
        "PlayResY: 720",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},{back},{bold},0,0,0,100,100,0,0,{border_style},{outline_val},{shadow_val},{ass_alignment},10,10,20,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    
    if os.path.exists(srt_path):
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        blocks = content.split('\n\n')
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) >= 3:
                # Line 0 is index, Line 1 is timestamps, Line 2+ is text
                time_line = lines[1]
                if ' --> ' in time_line:
                    times = time_line.split(' --> ')
                    start = srt_to_ass_time(times[0])
                    end = srt_to_ass_time(times[1])
                    text = " ".join(lines[2:]).replace('"', '""')
                    # Force uppercase for viral impact if it fits the style
                    text = text.upper()
                    ass_content.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
                
    ass_path = srt_path.replace('.srt', '.ass')
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(ass_content))
        
    return ass_path

@retry_on_failure(max_retries=2, delay=2)
def burn_captions(video_path, srt_path, output_path, status_key, style=None):
    """
    Professional caption burning logic.
    Converts SRT to styled ASS format for bulletproof rendering.
    """
    try:
        thread_safe_status_update(status_key, {'status': 'burning', 'progress': 20})
        style = style or {}
        
        # Create professional ASS file with embedded styles
        ass_path = create_ass_file(srt_path, style)
        
        # FFmpeg filter escape for windows paths
        ass_path_fixed = ass_path.replace('\\', '/').replace(':', '\\:')
        vf = f"subtitles='{ass_path_fixed}'"

        logger.info(f"Burning captions with ASS and Font: {style.get('fontName')}")

        cmd = [
            'ffmpeg', '-i', video_path, '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'copy', '-y', output_path
        ]
        
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg Error: {result.stderr}")
            # Final fallback: if ASS failed, try the old force_style way as a last resort
            raise Exception(f"FFmpeg failed: {result.stderr}")

        # Cleanup temporary ASS file
        if os.path.exists(ass_path):
            try: os.remove(ass_path)
            except: pass

        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return True
    except Exception as e:
        logger.error(f"Burn failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise
