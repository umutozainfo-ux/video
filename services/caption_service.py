import os
import threading
import logging
import subprocess
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

@retry_on_failure(max_retries=2, delay=2)
def burn_captions(video_path, srt_path, output_path, status_key, style=None):
    """Burn captions into video with styling."""
    try:
        thread_safe_status_update(status_key, {'status': 'burning', 'progress': 20})
        
        style = style or {}
        font_size = style.get('fontSize', 24)
        font_name = style.get('fontName', 'Arial Black')
        primary_color = style.get('primaryColor', '#ffffff')
        outline_color = style.get('outlineColor', '#000000')
        alignment = style.get('alignment', '2')
        letter_spacing = style.get('letterSpacing', 0)
        shadow_intensity = style.get('shadowBlur', 0)

        # Mapping for common professional fonts on Windows/FFmpeg
        font_map = {
            'Bebas Neue': 'Bebas Neue',
            'Luckiest Guy': 'Luckiest Guy',
            'Anton': 'Anton',
            'Bangers': 'Bangers',
            'Roboto': 'Roboto Black',
            'Archivo Black': 'Archivo Black',
            'Oswald': 'Oswald Bold',
            'Fredoka One': 'Fredoka One',
            'Titan One': 'Titan One',
            'Permanent Marker': 'Permanent Marker'
        }
        font_name = font_map.get(font_name, font_name)

        def to_ass_color(hex_color):
            hex_val = hex_color.replace('#', '')
            if len(hex_val) == 6:
                r, g, b = hex_val[:2], hex_val[2:4], hex_val[4:6]
                return f"&H00{b}{g}{r}"
            return "&H00FFFFFF"

        ass_primary = to_ass_color(primary_color)
        ass_outline = to_ass_color(outline_color)
        back_color = to_ass_color(style.get('backgroundColor', '#000000'))
        
        srt_path_fixed = srt_path.replace('\\', '/').replace(':', '\\:')
        border_style = style.get('borderStyle', '1')
        
        force_style = (
            f"Fontname={font_name},FontSize={font_size},"
            f"PrimaryColour={ass_primary},OutlineColour={ass_outline},BackColour={back_color},"
            f"BorderStyle={border_style},Alignment={alignment},"
            f"Spacing={letter_spacing},Blur={shadow_intensity},Outline=2,Shadow=2"
        )

        vf = f"subtitles='{srt_path_fixed}':force_style='{force_style}'"

        logger.info(f"Burning with style: {force_style}")

        cmd = [
            'ffmpeg', '-i', video_path, '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'copy', '-y', output_path
        ]
        
        # Check if font exists by attempting render and falling back
        # FFmpeg usually doesn't fail if font missing, it just falls back.
        # But we catch stderr for other issues.
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg Error: {result.stderr}")
            # Fallback to Arial Black if something went wrong with the specialty font
            if "font" in result.stderr.lower() or "subtitles" in result.stderr.lower():
                logger.warning("Rendering failed or font missing, falling back to Arial Black")
                force_style = force_style.replace(f"Fontname={font_name}", "Fontname=Arial Black")
                vf = f"subtitles='{srt_path_fixed}':force_style='{force_style}'"
                cmd[4] = vf
                subprocess.run(cmd, check=True)
            else:
                raise Exception(f"FFmpeg failed: {result.stderr}")

        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return True
    except Exception as e:
        logger.error(f"Burn failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise
