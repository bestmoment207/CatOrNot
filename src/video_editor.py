"""
video_editor.py — Builds a ranking-style YouTube Shorts video from cat clips.

Format (matching viral cat ranking channels):
  • NO intro card — jumps straight into clip #N
  • Bold title at the very top of every frame
  • Left-side numbered list showing all ranks simultaneously:
      - Current clip highlighted in gold (large number)
      - Already-shown clips dimmed
      - Upcoming clips show "?" (suspense)
  • Clips play full-screen behind the overlay
  • Moving @CatCentral watermark in corners
"""
import json
import logging
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
TARGET_W = 1080
TARGET_H = 1920
FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "128k"
VIDEO_CRF = "18"


def _ffmpeg(*args, check=True) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    logger.debug("ffmpeg: " + " ".join(str(a) for a in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    return result


def _escape_drawtext(text: str) -> str:
    """Escape special chars for ffmpeg drawtext filter."""
    for ch in ("\\", ":", "'", "[", "]", "%"):
        text = text.replace(ch, "\\" + ch)
    return text


def _clean_title(title: str) -> str:
    """Strip hashtags and extra whitespace for clean on-screen display."""
    title = re.sub(r"\s*#\w+", "", title).strip()
    title = re.sub(r"\s{2,}", " ", title)
    return title.upper()


def _find_font(bubbly: bool = False) -> str:
    """Return a font path ffmpeg can use for drawtext."""
    if bubbly:
        candidates = [
            str(Path(__file__).parent.parent / "assets" / "fonts" / "Fredoka.ttf"),
            "C:/Windows/Fonts/comicbd.ttf",
        ]
        for p in candidates:
            if Path(p).exists():
                return p
    standard = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for p in standard:
        if Path(p).exists():
            return p
    return ""


FONT_BUBBLY = _find_font(bubbly=True)
FONT_PLAIN  = _find_font(bubbly=False)
_FONT_B = f":fontfile={FONT_BUBBLY}" if FONT_BUBBLY else ""
_FONT_P = f":fontfile={FONT_PLAIN}"  if FONT_PLAIN  else ""


# ── Sound effects ─────────────────────────────────────────────────────────────

_WOOSH_PATH = Path(__file__).parent.parent / "assets" / "sfx" / "woosh.mp3"


_WOOSH_VERSION = 2   # bump to force regeneration when synthesis changes


def _get_woosh() -> Path | None:
    """Return path to the woosh sound, generating it with ffmpeg if needed."""
    ver_file = _WOOSH_PATH.with_suffix(".ver")
    needs_regen = (
        not _WOOSH_PATH.exists()
        or not ver_file.exists()
        or ver_file.read_text().strip() != str(_WOOSH_VERSION)
    )
    if not needs_regen:
        return _WOOSH_PATH
    try:
        _WOOSH_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Airy whoosh: pink noise band-passed to the 500–3500 Hz "wind" range,
        # amplitude-shaped with a sharp attack and a long tail.
        # The two-stage bandpass removes the harsh high end and the rumbling low
        # end, leaving the breezy mid-range characteristic of a real whoosh SFX.
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi",
                "-i", "anoisesrc=color=pink:duration=0.7:seed=7",
                "-af", (
                    "highpass=f=500,"
                    "lowpass=f=3500,"
                    "afade=t=in:d=0.04,"
                    "afade=t=out:st=0.50:d=0.20,"
                    "volume=5.0"
                ),
                "-ar", "44100",
                "-ac", "2",
                str(_WOOSH_PATH),
            ],
            check=True,
            capture_output=True,
        )
        ver_file.write_text(str(_WOOSH_VERSION))
        logger.info(f"Generated woosh SFX (v{_WOOSH_VERSION}) → {_WOOSH_PATH}")
        return _WOOSH_PATH
    except Exception as e:
        logger.warning(f"Could not generate woosh sound: {e}")
        return None


def _has_audio(video_path: Path) -> bool:
    """Return True if the video file has at least one audio stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "audio"


def _add_woosh_to_clip(
    video_path: Path,
    woosh_path: Path,
    output_path: Path,
) -> Path:
    """
    Mix a woosh sound effect at the very start of a clip.
    Handles clips that have no original audio track.
    """
    if _has_audio(video_path):
        audio_fc = (
            "[0:a]volume=1.0[orig];"
            "[1:a]volume=2.0[w];"
            "[orig][w]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio_fc = "[1:a]volume=2.0[a]"

    _ffmpeg(
        "-i", str(video_path),
        "-i", str(woosh_path),
        "-filter_complex", audio_fc,
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-ar", "44100",
        "-ac", "2",
        str(output_path),
    )
    return output_path


# ── Ranking overlay ───────────────────────────────────────────────────────────

def _make_short_label(title: str) -> str:
    """Turn a clip title into a 2-word ALL-CAPS sidebar label."""
    # Strip hashtags, URLs, numbers at the start, and punctuation
    label = re.sub(r"#\w+", "", title).strip()
    label = re.sub(r"https?://\S+", "", label).strip()
    label = re.sub(r"^\W+", "", label).strip()
    # Skip filler words so we surface meaningful content words
    FILLER = {
        "the","a","an","of","in","on","at","to","and","or","but","is","it",
        "this","that","my","your","his","her","cat","cats","kitten","funny",
        "video","clip","short","shorts","when","how","why","what","who",
    }
    words = [w for w in label.split() if w.lower() not in FILLER]
    if not words:
        words = label.split()   # fallback: use any words
    # Two words max
    chosen = " ".join(words[:2])
    return chosen[:14].upper() or "CAT CLIP"


def _build_ranking_overlay(
    all_labels: list[str],
    current_idx: int,
    n: int,
    title: str,
) -> str:
    """
    Build the ffmpeg drawtext/drawbox filter chain for the ranking overlay.

    Layout:
      [Black bar at top — contains the video title]
      [Black panel on left — contains numbered list of all clips]
         Clips already shown: dimmed white
         Current clip: gold + large
         Clips still coming: white @ low opacity + "?"
    """
    parts: list[str] = []

    # ── Title bar ─────────────────────────────────────────────────────────────
    title_text = _escape_drawtext(_clean_title(title))
    title_fontsize = 52
    if len(title_text) > 22:
        title_fontsize = 44
    if len(title_text) > 30:
        title_fontsize = 36

    parts.append("drawbox=x=0:y=0:w=iw:h=118:color=black@0.78:t=fill")
    parts.append(
        f"drawtext=text='{title_text}'{_FONT_B}"
        f":fontsize={title_fontsize}:fontcolor=white"
        ":borderw=4:bordercolor=black@0.95"
        ":x=(w-tw)/2:y=38"
    )

    # ── Left panel ────────────────────────────────────────────────────────────

    # Item positions — spread evenly between y=155 and y=1820
    y_start  = 165
    y_end    = 1820
    spacing  = (y_end - y_start) // n

    for i in range(n):
        rank = n - i           # n → 1
        y    = y_start + i * spacing
        is_current = (i == current_idx)
        is_past    = (i < current_idx)

        if is_current:
            num_color = "#FFD700"
            num_size  = 112          # was 84
            lbl_color = "#FFFFFF"
            lbl_size  = 56           # was 40
        elif is_past:
            num_color = "white@0.55"
            num_size  = 76           # was 54
            lbl_color = "white@0.55"
            lbl_size  = 40           # was 28
        else:
            num_color = "white@0.28"
            num_size  = 76           # was 54
            lbl_color = "white@0.28"
            lbl_size  = 40           # was 28

        # Rank number
        num_str = _escape_drawtext(f"{rank}.")
        parts.append(
            f"drawtext=text='{num_str}'{_FONT_B}"
            f":fontsize={num_size}:fontcolor={num_color}"
            f":borderw=5:bordercolor=black@0.95"   # was borderw=3
            f":x=16:y={y}"
        )

        # Label: revealed for current + past; "?" for future
        if is_current or is_past:
            raw_lbl = _make_short_label(all_labels[i] if i < len(all_labels) else "")
            lbl_str = _escape_drawtext(raw_lbl)
        else:
            lbl_str = "\\?"

        lbl_y = y + max(0, (num_size - lbl_size) // 2 + 4)
        parts.append(
            f"drawtext=text='{lbl_str}'{_FONT_B}"
            f":fontsize={lbl_size}:fontcolor={lbl_color}"
            f":borderw=4:bordercolor=black@0.9"    # was borderw=2
            f":x=108:y={lbl_y}"
        )

    return ",".join(parts)


# ── Process one clip ──────────────────────────────────────────────────────────

def _process_clip(
    input_path: Path,
    output_path: Path,
    rank: int,
    clip_duration: int,
    title: str,
    all_labels: list[str] | None = None,
    current_idx: int = 0,
    n: int = 5,
) -> Path:
    """Scale/crop clip to 1080×1920, trim, and burn in the ranking overlay."""
    # Normalise SAR first (some downloads carry non-square pixel ratios),
    # then scale so the video COVERS the full 1080×1920 canvas without black
    # bars (force_original_aspect_ratio=increase), then centre-crop to exact size.
    scale_crop = (
        f"setsar=1,"
        f"scale={TARGET_W}:{TARGET_H}"
        f":force_original_aspect_ratio=increase"
        f":flags=lanczos,"
        f"crop={TARGET_W}:{TARGET_H}"
    )
    overlay = _build_ranking_overlay(
        all_labels=all_labels or [""] * n,
        current_idx=current_idx,
        n=n,
        title=title,
    )
    vf = f"{scale_crop},fps={FPS},{overlay}"

    _ffmpeg(
        "-i", str(input_path),
        "-t", str(clip_duration),
        "-vf", vf,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", "fast",
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    )
    return output_path


# ── Duration helper ───────────────────────────────────────────────────────────

def _get_duration(path: Path) -> float:
    """Return duration of any audio/video file in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 3.0


# ── Rank TTS overlay ──────────────────────────────────────────────────────────

def _add_rank_tts(video_path: Path, tts_path: Path, output_path: Path) -> Path:
    """
    Mix TTS rank narration (e.g. "Coming in at number 5…") into the start
    of the clip's audio track.  The TTS is louder than the original audio
    so it's clearly audible.
    """
    if _has_audio(video_path):
        audio_fc = (
            "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[orig];"
            "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.8[tts];"
            "[orig][tts]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio_fc = (
            "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            "volume=1.8[a]"
        )

    _ffmpeg(
        "-i", str(video_path),
        "-i", str(tts_path),
        "-filter_complex", audio_fc,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
        "-ar", "44100", "-ac", "2",
        str(output_path),
    )
    return output_path


# ── Hook intro (freeze-frame title card) ──────────────────────────────────────

def _make_hook_intro(
    source_clip: Path,
    title: str,
    n: int,
    tts_path: Path | None,
    output_path: Path,
) -> Path:
    """
    Build a freeze-frame hook intro card that acts as the video's "thumbnail moment":

      • Background : first frame of source_clip, scaled/cropped to 1080×1920
      • Dark centre panel for readability
      • "TOP N"  — gold, 150 px, centred
      • Video title — white, centred below
      • Audio : TTS intro narration (or silence if TTS unavailable)
      • Duration : TTS duration + 0.4 s padding  (minimum 2.5 s)

    After this card, the first ranked clip begins (which already carries a
    whoosh at its start, providing a natural transition).
    """
    has_tts = bool(tts_path and tts_path.exists() and tts_path.stat().st_size > 256)
    duration = (_get_duration(tts_path) + 0.4) if has_tts else 3.0
    duration = max(duration, 2.5)

    # Extract a frame slightly into the clip (skip any black fade-in)
    frame_jpg = output_path.parent / "_hook_frame.jpg"
    _ffmpeg("-ss", "0.3", "-i", str(source_clip), "-vframes", "1", str(frame_jpg))

    top_n_str   = _escape_drawtext(f"TOP {n}")
    title_str   = _escape_drawtext(_clean_title(title))
    title_fsize = 54 if len(title_str) <= 24 else (44 if len(title_str) <= 34 else 36)

    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={FPS},"
        # Semi-transparent panel in centre of frame
        f"drawbox=x=50:y=670:w={TARGET_W - 100}:h=650:color=black@0.72:t=fill,"
        # "TOP N" — large gold text
        f"drawtext=text='{top_n_str}'{_FONT_B}"
        f":fontsize=150:fontcolor=#FFD700"
        f":borderw=6:bordercolor=black@0.9"
        f":x=(w-tw)/2:y=725,"
        # Video title — white subtitle
        f"drawtext=text='{title_str}'{_FONT_B}"
        f":fontsize={title_fsize}:fontcolor=white"
        f":borderw=4:bordercolor=black@0.85"
        f":x=(w-tw)/2:y=935"
    )

    # Build ffmpeg command — audio source differs based on TTS availability
    if has_tts:
        _ffmpeg(
            "-loop", "1", "-framerate", str(FPS), "-i", str(frame_jpg),
            "-i", str(tts_path),
            "-t", str(duration),
            "-vf", vf,
            "-map", "0:v", "-map", "1:a",
            "-c:v", VIDEO_CODEC, "-crf", VIDEO_CRF, "-preset", "fast",
            "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
            str(output_path),
        )
    else:
        # Silent freeze frame (anullsrc generates the required audio stream)
        _ffmpeg(
            "-loop", "1", "-framerate", str(FPS), "-i", str(frame_jpg),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-vf", vf,
            "-map", "0:v", "-map", "1:a",
            "-c:v", VIDEO_CODEC, "-crf", VIDEO_CRF, "-preset", "fast",
            "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
            str(output_path),
        )

    frame_jpg.unlink(missing_ok=True)
    return output_path


# ── Background music with sidechain ducking ────────────────────────────────────

def _mix_bgm(
    input_path: Path,
    output_path: Path,
    bgm_dir: Path,
    volume: float = 0.25,
    duck_enabled: bool = True,
    duck_ratio: float = 6.0,
    duck_threshold: float = 0.025,
) -> Path:
    """
    Mix a random track from bgm_dir under the finished video.

    When duck_enabled=True, a sidechain compressor automatically lowers the
    BGM whenever the video's speech/SFX is loud enough to cross duck_threshold.

    Parameters
    ----------
    volume          Master BGM level (0.0 – 1.0).  0.25 is a gentle underscore.
    duck_enabled    Enable sidechain ducking.
    duck_ratio      Compression ratio when ducking (2–10; higher = more ducking).
    duck_threshold  Speech amplitude that triggers ducking (0.0 – 1.0).
    """
    bgm_files: list[Path] = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.ogg", "*.flac"):
        bgm_files.extend(bgm_dir.glob(ext))

    if not bgm_files:
        logger.info("No BGM files found in assets/bgmusic — skipping BGM")
        shutil.copy2(input_path, output_path)
        return output_path

    bgm = random.choice(bgm_files)
    logger.info(f"BGM: {bgm.name}  vol={volume}  duck={duck_enabled}")

    total_dur = _get_duration(input_path)
    has_orig  = _has_audio(input_path)

    if has_orig and duck_enabled:
        # Split original audio: one copy for mixing, one as sidechain trigger
        fc = (
            f"[0:a]asplit=2[speech1][speech2];"
            f"[1:a]atrim=duration={total_dur},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={volume}[bgm];"
            # BGM is compressed (ducked) whenever speech2 crosses the threshold
            f"[bgm][speech2]sidechaincompress="
            f"threshold={duck_threshold}:ratio={duck_ratio}"
            f":attack=150:release=800[bgm_ducked];"
            # Mix the un-modified speech with the ducked BGM
            f"[speech1][bgm_ducked]amix=inputs=2:normalize=0[out]"
        )
    elif has_orig:
        fc = (
            f"[1:a]atrim=duration={total_dur},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={volume}[bgm];"
            f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[speech];"
            f"[speech][bgm]amix=inputs=2:normalize=0[out]"
        )
    else:
        # Video has no audio — just use BGM
        fc = (
            f"[1:a]atrim=duration={total_dur},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={volume}[out]"
        )

    _ffmpeg(
        "-i", str(input_path),
        "-stream_loop", "-1", "-i", str(bgm),
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[out]",
        "-c:v", "copy",
        "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
        "-t", str(total_dur),
        str(output_path),
    )
    return output_path


# ── Concatenate ───────────────────────────────────────────────────────────────

def _concat_clips(clip_paths: list[Path], output_path: Path) -> Path:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in clip_paths:
            f.write(f"file '{str(p).replace(chr(92), '/')}'\n")
        list_file = Path(f.name)
    _ffmpeg(
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_path),
    )
    list_file.unlink(missing_ok=True)
    return output_path


# ── Watermark + popups ────────────────────────────────────────────────────────

def _add_watermark(input_path: Path, output_path: Path, watermark_text: str) -> Path:
    """
    Burn a moving @CatCentral watermark AND a like/subscribe popup into
    the video in a single ffmpeg pass.

    Like & Subscribe badge:
      • Red pill-shaped box, centred near the bottom
      • Appears 3–6 seconds in (during the first clip)
      • Short enough to be non-annoying, long enough to register
    """
    wm  = _escape_drawtext(watermark_text)
    pad = 55

    # Moving watermark
    x_expr = (
        f"if(eq(mod(floor(t/12),4),0),{pad},"
        f"if(eq(mod(floor(t/12),4),1),w-tw-{pad},"
        f"if(eq(mod(floor(t/12),4),2),{pad},"
        f"w-tw-{pad})))"
    )
    y_expr = (
        f"if(eq(mod(floor(t/12),4),0),{pad+20},"
        f"if(eq(mod(floor(t/12),4),1),{pad+20},"
        f"if(eq(mod(floor(t/12),4),2),h-th-{pad},"
        f"h-th-{pad})))"
    )
    wm_filter = (
        f"drawtext=text='{wm}'{_FONT_P}"
        ":fontsize=34:fontcolor=white@0.75"
        ":borderw=2:bordercolor=black@0.6"
        f":x='{x_expr}':y='{y_expr}'"
    )

    # Like & subscribe popup badge — shows at t=3..6
    # Use fixed pixel coords (1080×1920 frame) — drawbox doesn't support iw/ih expressions in all ffmpeg builds
    # x=280 = (1080-520)/2, y=1710 = 1920-210
    popup_box = (
        "drawbox=x=280:y=1710:w=520:h=88"
        ":color=#EE1111@0.88:t=fill"
        ":enable='between(t,3,6)'"
    )
    popup_text = (
        f"drawtext=text='LIKE \\& SUBSCRIBE'{_FONT_B}"
        ":fontsize=40:fontcolor=white"
        ":borderw=3:bordercolor=black@0.8"
        ":x=(w-tw)/2:y=1728"
        ":enable='between(t,3,6)'"
    )
    popup_hint = (
        f"drawtext=text='for more cat videos'{_FONT_P}"
        ":fontsize=24:fontcolor=white@0.8"
        ":borderw=2:bordercolor=black@0.6"
        ":x=(w-tw)/2:y=1768"
        ":enable='between(t,3,6)'"
    )

    vf = f"{wm_filter},{popup_box},{popup_text},{popup_hint}"

    _ffmpeg(
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", VIDEO_CODEC, "-crf", VIDEO_CRF, "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    )
    return output_path


# ── Platform watermark blur ───────────────────────────────────────────────────

_PLATFORM_BLUR_REGIONS: dict[str, list[tuple]] = {
    "youtube":   [],
    "instagram": [],
    "tiktok": [
        ("iw-180", "ih-180", 180, 180),
        ("0",      "ih-100", 300, 100),
    ],
    "unknown": [
        ("0",        "0",      180, 100),
        ("iw-180",   "0",      180, 100),
        ("0",        "ih-100", 180, 100),
        ("iw-180",   "ih-100", 180, 100),
        ("iw/2-200", "ih-80",  400,  80),
    ],
}
_BLUR_STRENGTH = 18
_WATERMARK_STDDEV_THRESHOLD   = 22.0
_WATERMARK_TEMPORAL_THRESHOLD = 20.0


def _get_video_size(video_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        parts = result.stdout.strip().split(",")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        logger.debug(f"Could not parse video size for {video_path.name}; using defaults")
        return 1920, 1080


def _resolve_region(region: tuple, vw: int, vh: int) -> tuple[int, int, int, int]:
    cx_expr, cy_expr, bw, bh = region
    cx = int(eval(cx_expr.replace("iw", str(vw)).replace("ih", str(vh))))  # noqa: S307
    cy = int(eval(cy_expr.replace("iw", str(vw)).replace("ih", str(vh))))  # noqa: S307
    cx = max(0, min(cx, vw - bw))
    cy = max(0, min(cy, vh - bh))
    return cx, cy, bw, bh


def _get_region_pixels(video_path: Path, x: int, y: int, w: int, h: int, seek: float) -> bytes | None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", str(seek), "-i", str(video_path),
         "-vframes", "1", "-vf", f"crop={w}:{h}:{x}:{y}",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True,
    )
    if result.returncode != 0 or len(result.stdout) < w * h // 2:
        return None
    return result.stdout[: w * h]


def _region_has_watermark(video_path: Path, x: int, y: int, w: int, h: int) -> bool:
    px1 = _get_region_pixels(video_path, x, y, w, h, seek=1.0)
    if px1 is None:
        return True
    n   = len(px1)
    m1  = sum(px1) / n
    std = (sum((p - m1) ** 2 for p in px1) / n) ** 0.5
    if std < _WATERMARK_STDDEV_THRESHOLD:
        return False
    px2 = _get_region_pixels(video_path, x, y, w, h, seek=3.0)
    if px2 is not None and len(px2) == n:
        diff = sum(abs(a - b) for a, b in zip(px1, px2)) / n
        return diff < _WATERMARK_TEMPORAL_THRESHOLD
    return True


def _blur_source_watermarks(input_path: Path, output_path: Path, platform: str = "unknown") -> Path:
    candidate_regions = _PLATFORM_BLUR_REGIONS.get(platform, _PLATFORM_BLUR_REGIONS["unknown"])
    if not candidate_regions:
        shutil.copy2(input_path, output_path)
        return output_path
    try:
        vw, vh = _get_video_size(input_path)
    except Exception:
        vw, vh = 1920, 1080
    regions_to_blur = []
    for region in candidate_regions:
        x, y, bw, bh = _resolve_region(region, vw, vh)
        if _region_has_watermark(input_path, x, y, bw, bh):
            regions_to_blur.append(region)
    if not regions_to_blur:
        shutil.copy2(input_path, output_path)
        return output_path
    n = len(regions_to_blur)
    split_labels = "".join(f"[c{i}]" for i in range(n))
    fc_parts = [f"[0:v]split={n + 1}[base]{split_labels}"]
    for i, (cx, cy, bw, bh) in enumerate(regions_to_blur):
        fc_parts.append(f"[c{i}]crop={bw}:{bh}:{cx}:{cy},gblur=sigma={_BLUR_STRENGTH}[b{i}]")
    prev = "base"
    for i, (cx, cy, bw, bh) in enumerate(regions_to_blur):
        ox  = cx.replace("iw", "W")
        oy  = cy.replace("ih", "H")
        nxt = "out" if i == n - 1 else f"o{i}"
        fc_parts.append(f"[{prev}][b{i}]overlay={ox}:{oy}[{nxt}]")
        prev = nxt
    try:
        _ffmpeg(
            "-i", str(input_path),
            "-filter_complex", ";".join(fc_parts),
            "-map", "[out]", "-map", "0:a?",
            "-c:v", VIDEO_CODEC, "-crf", VIDEO_CRF, "-preset", "fast",
            "-c:a", "copy",
            str(output_path),
        )
    except Exception as e:
        logger.warning(f"Watermark blur failed ({platform}): {e}")
        shutil.copy2(input_path, output_path)
    return output_path


# ── Main public function ──────────────────────────────────────────────────────

def create_ranking_video(
    clip_paths: list[Path],
    title: str,
    output_path: Path,
    config,
    clip_platforms: list[str] | None = None,
    on_progress=None,
    tts_audio: dict | None = None,
    clip_labels: list[str] | None = None,
) -> Path:
    """
    Build a ranking-style Shorts video from cat clips.

    Video structure
    ---------------
    1. Freeze-frame hook intro  — "TOP N  <TITLE>" + TTS narration
       (duration = TTS intro length; acts as the thumbnail moment)
    2. Whoosh → Clip rank-N   — TTS "Coming in at number N…" mixed in
    3. Whoosh → Clip rank-N-1 — same pattern
    4. …
    5. Clip rank-1
    6. Optional BGM ducked under all speech/SFX (if enabled in config)
    """
    if len(clip_paths) < 2:
        raise ValueError(f"Need at least 2 clips, got {len(clip_paths)}")

    n         = len(clip_paths)
    platforms = clip_platforms or ["unknown"] * n
    labels    = clip_labels    or [f"CLIP {i + 1}" for i in range(n)]

    # Unpack TTS paths (generated in scheduler; all may be None if TTS disabled)
    rank_tts: list[Path | None] = []
    hook_tts: Path | None = None
    if tts_audio:
        hook_tts  = tts_audio.get("intro")
        rank_tts  = list(tts_audio.get("ranks", []))  # index 0 = rank-n (first shown)

    # Pad rank_tts so we can safely index it
    while len(rank_tts) < n:
        rank_tts.append(None)

    def _step(msg: str) -> None:
        logger.debug(msg)
        if on_progress:
            on_progress(msg)

    clip_duration = config.clip_duration

    with tempfile.TemporaryDirectory(prefix="catcentral_") as tmpdir:
        tmp = Path(tmpdir)
        processed: list[Path] = []

        # Pre-load woosh sound (generated once, reused for every transition)
        woosh = _get_woosh()
        if woosh:
            _step("Woosh SFX ready…")

        # ── 1. Process each clip ─────────────────────────────────────────────
        for idx, src in enumerate(clip_paths):
            rank     = n - idx   # n=5,idx=0 → rank 5 first; idx=4 → rank 1 last
            step1    = tmp / f"rank{rank}.mp4"
            platform = platforms[idx]

            blur_regions = _PLATFORM_BLUR_REGIONS.get(
                platform, _PLATFORM_BLUR_REGIONS["unknown"]
            )
            if blur_regions:
                _step(f"Removing {platform} watermark — clip {idx + 1}/{n}…")
                blurred = tmp / f"blur_rank{rank}.mp4"
                _blur_source_watermarks(src, blurred, platform)
                source = blurred
            else:
                source = src

            _step(f"Processing clip {idx + 1}/{n}  (rank #{rank})…")
            _process_clip(
                source, step1, rank, clip_duration, title,
                all_labels=labels,
                current_idx=idx,
                n=n,
            )
            current = step1

            # ── 1a. Overlay rank TTS onto the clip's audio ───────────────────
            tts_for_rank = rank_tts[idx] if idx < len(rank_tts) else None
            if tts_for_rank and tts_for_rank.exists():
                tts_out = tmp / f"tts_rank{rank}.mp4"
                try:
                    _step(f"Mixing rank-{rank} TTS narration…")
                    _add_rank_tts(current, tts_for_rank, tts_out)
                    current = tts_out
                except Exception as e:
                    logger.warning(f"Rank TTS mix failed for rank {rank}: {e}")

            # ── 1b. Add whoosh at the very start of the clip ─────────────────
            if woosh:
                woosh_out = tmp / f"woosh_rank{rank}.mp4"
                try:
                    _add_woosh_to_clip(current, woosh, woosh_out)
                    processed.append(woosh_out)
                except Exception as e:
                    logger.warning(f"Woosh mix failed for rank {rank}: {e}")
                    processed.append(current)
            else:
                processed.append(current)

        # ── 2. Create freeze-frame hook intro ────────────────────────────────
        intro_clip: Path | None = None
        try:
            _step("Creating hook intro card…")
            intro_out = tmp / "hook_intro.mp4"
            # Use the raw source of the first clip shown (rank-n) as background
            _make_hook_intro(clip_paths[0], title, n, hook_tts, intro_out)
            intro_clip = intro_out
        except Exception as e:
            logger.warning(f"Hook intro creation failed (non-fatal): {e}")

        # ── 3. Concatenate: [hook intro] + [clip-n … clip-1] ─────────────────
        _step("Concatenating all clips…")
        all_clips = ([intro_clip] if intro_clip else []) + processed
        joined    = tmp / "joined.mp4"
        _concat_clips(all_clips, joined)

        # ── 4. Add watermark + like/subscribe popup ───────────────────────────
        _step(f"Adding {config.watermark_text} watermark…")
        watermarked = tmp / "watermarked.mp4"
        _add_watermark(joined, watermarked, config.watermark_text)

        # ── 5. Mix background music (optional) ───────────────────────────────
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bgm_enabled = getattr(config, "bgm_enabled", False)
        bgm_dir     = getattr(config, "bgm_dir", Path(__file__).parent.parent / "assets" / "bgmusic")

        if bgm_enabled and bgm_dir.exists():
            _step("Mixing background music…")
            try:
                _mix_bgm(
                    watermarked,
                    output_path,
                    bgm_dir,
                    volume       = getattr(config, "bgm_volume",         0.25),
                    duck_enabled = getattr(config, "bgm_duck_enabled",   True),
                    duck_ratio   = getattr(config, "bgm_duck_ratio",     6.0),
                    duck_threshold = getattr(config, "bgm_duck_threshold", 0.025),
                )
            except Exception as e:
                logger.warning(f"BGM mix failed (non-fatal): {e}")
                shutil.copy2(watermarked, output_path)
        else:
            shutil.copy2(watermarked, output_path)

    logger.info(f"Ranking video created: {output_path}")
    return output_path


# ── CLI helper ────────────────────────────────────────────────────────────────

def check_ffmpeg():
    """Raise RuntimeError if ffmpeg or ffprobe is not installed."""
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(
                f"{tool} is not installed or not on PATH.\n"
                "Install: sudo apt install ffmpeg"
            )
