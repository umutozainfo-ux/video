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

        # Professional standard font mapping for Windows environments
        # We try to use the requested font name directly first.
        # This mapping is used as a fallback or hint for common viral fonts.
        font_map = {
            'Bebas Neue': 'Impact',
            'Anton': 'Arial Black',
            'Luckiest Guy': 'Arial Black',
            'Bangers': 'Impact',
            'Roboto': 'Roboto Black', 
            'Archivo Black': 'Arial Black',
            'Oswald': 'Verdana',
            'Titan One': 'Impact',
            'Permanent Marker': 'Comic Sans MS',
            'Fredoka One': 'Arial Black'
        }
        
        # Determine the target font for FFmpeg
        # We'll try the requested font name first as it might be installed
        # but we also provide the mapped version as a secondary attempt if needed.
        target_font = font_name
        system_fallback = font_map.get(font_name, 'Arial Black')

        def to_ass_color(hex_color):
            if not hex_color: return "&H00FFFFFF"
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
        
        if alignment == '10': alignment = '8' # Top Center
        
        outline_val = 2 if border_style == '1' else 0
        shadow_val = 2 if border_style == '1' else 0

        # Create the style string
        def create_vf(font):
            force_style = (
                f"Fontname={font},FontSize={font_size},"
                f"PrimaryColour={ass_primary},OutlineColour={ass_outline},BackColour={back_color},"
                f"BorderStyle={border_style},Alignment={alignment},"
                f"Spacing={letter_spacing},Blur={shadow_intensity},"
                f"Outline={outline_val},Shadow={shadow_val}"
            )
            return f"subtitles='{srt_path_fixed}':force_style='{force_style}'"

        vf = create_vf(target_font)
        logger.info(f"Burning with font: {target_font}")

        cmd = [
            'ffmpeg', '-i', video_path, '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'copy', '-y', output_path
        ]
        
        # FFmpeg usually doesn't fail if a font is missing (it just logs a warning and falls back)
        # However, we'll check if the command succeeded and also check stderr for clues.
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg Error: {result.stderr}")
            # If it failed and we suspect font/subtitles, try the fallback
            if any(x in result.stderr.lower() for x in ["font", "subtitles", "filter", "ass"]):
                logger.warning(f"Font '{target_font}' failed, trying system fallback '{system_fallback}'")
                vf_fallback = create_vf(system_fallback)
                cmd[4] = vf_fallback
                subprocess.run(cmd, check=True)
            else:
                raise Exception(f"FFmpeg failed: {result.stderr}")
        
        # Check if FFmpeg output contains font warning - if it does, the font likely wasn't used
        # but the task completed. We logging it for debugging.
        if "font select" in result.stderr.lower() or "find font" in result.stderr.lower():
             logger.warning(f"FFmpeg mentioned font selection issues. Requested: {target_font}")

        thread_safe_status_update(status_key, {'status': 'completed', 'progress': 100})
        return True
    except Exception as e:
        logger.error(f"Burn failed: {str(e)}")
        thread_safe_status_update(status_key, {'status': 'error', 'error': str(e)})
        raise
