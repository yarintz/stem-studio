import os
import re
import glob
import tempfile
import shutil
import subprocess
from typing import Dict, Tuple, Optional, List
import sys
import numpy as np
from pydub import AudioSegment
import gradio as gr
import yt_dlp
import uuid
import time
from config import *

def cleanup_temp_files():
    """Remove temp trimmed file and downloads."""
    try:
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)
    except Exception:
        pass

    try:
        if os.path.exists("downloads"):
            shutil.rmtree("downloads")
            os.makedirs("downloads", exist_ok=True)
    except Exception:
        pass

def new_song(prev_choices: List[str]):
        cleanup_temp_files()
        edit_outputs_values = populate_edit_ui({}, {}, False)
        return None, None, None, gr.update(visible=False, value= None), None, {}, None, None, None, False, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False),  *edit_outputs_values

def update_trimmed_audio(audio_file):
    """
    Automatically saves the currently trimmed version into TEMP_FILE.
    """
    if audio_file is None:
        return None

    # audio_file is a string path when type="filepath"
    if os.path.exists(audio_file):
        shutil.copy(audio_file, TEMP_FILE)
        return None
    return None

def load_mock_stems(mock_folder: str):
    """
    Load stems and the pre-made mixed file from mock_folder.
    Expects filenames:
      - vocals.wav, guitar.wav, piano.wav, drums.wav, bass.wav, other.wav
      - song_mixed.wav  (optional — the full mix)
    Returns: (stems_dict: Dict[name->AudioSegment], mix_path_or_None: str|None)
    """
    stems = {}
    for name in STEM_ORDER:
        fn = os.path.join(mock_folder, f"{name}.wav")
        if os.path.exists(fn):
            stems[name] = AudioSegment.from_file(fn).set_frame_rate(DEFAULT_SR)
    mixed = None
    possible_mix = os.path.join(mock_folder, "song_mixed.wav")
    if os.path.exists(possible_mix):
        mixed = possible_mix
    return stems, mixed

def download_from_youtube(url):

    os.makedirs("downloads", exist_ok=True)
    unique_id = str(uuid.uuid4())[:8]
    output_path = f"downloads/song_{unique_id}.%(ext)s"

    ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': output_path ,
    'noplaylist': True,  # <--- prevents downloading entire playlists
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        time.sleep(1)
        final_path = f"downloads/song_{unique_id}.mp3"
    return final_path

def handle_input(file, url):
    if file is not None:
        return gr.update(visible=True, value=file), file, file, False
    elif url:
        if url == "manual-test-100":
            return gr.update(visible=True), None, None, True
        else:
            downloaded = download_from_youtube(url)
        return gr.update(visible=True, value=downloaded), downloaded, downloaded, False
    else:
        return None, None, None, False
        
def parse_time_mmss(txt: str) -> Optional[int]:
    """'mm:ss' -> milliseconds int. Accepts 'm:ss', 'ss', or empty (None)."""
    if txt is None:
        return None
    t = str(txt).strip()
    if t == "":
        return None
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        m, s = t.split(":")
        return (int(m) * 60 + int(s)) * 1000
    if re.fullmatch(r"\d{1,4}", t):
        return int(t) * 1000
    raise ValueError(f"Invalid time '{txt}'. Use mm:ss or seconds.")

def seg_to_np(seg: AudioSegment) -> Tuple[int, np.ndarray]:
    samples = np.array(seg.get_array_of_samples())
    ch = seg.channels
    if ch > 1:
        samples = samples.reshape((-1, ch))
    else:
        samples = samples.reshape((-1, 1))
    max_val = float(1 << (8 * seg.sample_width - 1))
    data = (samples / max_val).astype(np.float32)
    return seg.frame_rate, data

def export_temp_wav(seg: AudioSegment, prefix="mix_") -> str:
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".wav")
    os.close(fd)
    seg.export(path, format="wav")
    return path

def overlay_many(segments: List[AudioSegment]) -> AudioSegment:
    if not segments:
        return AudioSegment.silent(duration=1000, frame_rate=DEFAULT_SR)
    max_len = max(len(s) for s in segments)
    mix = AudioSegment.silent(duration=max_len, frame_rate=segments[0].frame_rate)
    for s in segments:
        mix = mix.overlay(s)
    return mix

def silence_range(seg: AudioSegment, start_ms: Optional[int], end_ms: Optional[int]) -> AudioSegment:
    n = len(seg)
    s = max(0, start_ms or 0)
    e = n if end_ms is None else min(n, end_ms)
    if s >= e:
        return seg
    return seg[:s] + AudioSegment.silent(duration=(e - s), frame_rate=seg.frame_rate) + seg[e:]

# ----------------------------
# Demucs separation (in-memory)
# ----------------------------
def separate_stems_in_memory(audio_path: str, model: str = DEFAULT_MODEL) -> Dict[str, AudioSegment]:
    temp_root = tempfile.mkdtemp(prefix="demucs_")
    safe_in = os.path.join(temp_root, "input.wav")
    try:
        src_seg = AudioSegment.from_file(audio_path).set_frame_rate(DEFAULT_SR)
        src_seg.export(safe_in, format="wav")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "UTF-8"

        out_dir = temp_root
        cmd = [sys.executable, "-m", "demucs.separate", "-n", model, "--out", out_dir, safe_in]
        proc = subprocess.run(cmd, check=False, capture_output=True, env=env)

        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore")
            raise RuntimeError(f"Demucs failed (code {proc.returncode}).\n\n{err}")

        model_dir = os.path.join(out_dir, model)
        subdirs = glob.glob(os.path.join(model_dir, "*"))
        if not subdirs:
            raise RuntimeError("Demucs finished but no output folder was created.")
        track_dir = subdirs[0]

        stems: Dict[str, AudioSegment] = {}
        for name in STEM_ORDER:
            fn = os.path.join(track_dir, f"{name}.wav")
            if os.path.exists(fn):
                seg = AudioSegment.from_file(fn).set_frame_rate(DEFAULT_SR)
                stems[name] = seg

        if not stems:
            raise RuntimeError("Demucs produced no stems.")
        return stems
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

def build_mix_from_stems(stems: Dict[str, AudioSegment], include: List[str],
                         add_stick: bool,
                         ) -> AudioSegment:
    # custom_stick_file sometimes arrives as dict (from gr.File) — handle it
    selected = [stems[n] for n in include if n in stems]
    mix = overlay_many(selected)
    if add_stick:
        stick_seg = None
        if os.path.exists(DEFAULT_STICK_PATH):
            stick_seg = AudioSegment.from_file(DEFAULT_STICK_PATH)
        if stick_seg is not None:
            stick_seg = stick_seg.set_frame_rate(mix.frame_rate)
            mix = stick_seg + mix
    return mix

def do_separate_and_mix(path, includes, addstick, mock_flag):
        # Prefer trimmed file if it exists
        final_input = TEMP_FILE if os.path.exists(TEMP_FILE) else path
        # path = uploaded file path (used only in real mode)
        # mock_flag = boolean -> when True we use load_mock_stems()
        if mock_flag:
            # Load mock stems immediately from MOCK_FOLDER
            stems, mix_path = load_mock_stems(MOCK_FOLDER)
            if not stems:
                return gr.update(value=None), None, None, gr.update(visible=False, value=None), "❌ MOCK folder empty or missing files."
            # If you have a pre-made mixed file, return it for `result_audio`, otherwise build mix from stems:
            if mix_path:
                # return the full mix file path for preview; also keep stems in memory
                return mix_path, stems, None, gr.update(visible=True, value=mix_path), "✅ Loaded mock stems and mixed file."
            else:
                mix = build_mix_from_stems(stems, includes, addstick)
                temp_wav = export_temp_wav(mix, prefix="mix_")
                return temp_wav, stems, mix, gr.update(visible=True, value=temp_wav), "✅ Loaded mock stems and built mix."
        else:
            # REAL mode — run Demucs
            if not path or not os.path.exists(final_input):
                return gr.update(value=None), None, None, gr.update(visible=False, value=None), "❌ Upload a file first."
            try:
                stems = separate_stems_in_memory(final_input, model=DEFAULT_MODEL)
                mix = build_mix_from_stems(stems, includes, addstick)
                temp_wav = export_temp_wav(mix, prefix="mix_")
                return temp_wav, stems, mix,  gr.update(visible=True, value=temp_wav), "✅ Mix created."
            except Exception as e:
                return gr.update(value=None), None, None, gr.update(visible=False, value=None), f"❌ Error: {e}"
            
def reset_stem(stems: Dict[str, AudioSegment], original_stems: Dict[str, AudioSegment], stem_name: str):
    start_val = ""
    end_val = ""
    gain_val = 0
    orig_seg = original_stems[stem_name]
    stems[stem_name] = orig_seg
    tmp = export_temp_wav(orig_seg, prefix=f"stem_{stem_name}_")
    include_val = (stem_name in DEFAULT_INCLUDE)
    msg = f"Reset {stem_name} to original."

    return include_val, start_val, end_val, gain_val, tmp, msg           
    

# When user clicks Edit (from main UI), populate players and include checkboxes and show panel
def populate_edit_ui(stems: Dict[str, AudioSegment], prev_choices: List[str], visible: bool):
    outputs = [gr.update(visible=visible)]
    # For each stem we must return: player path (or None), include checkbox state (value), start text default, end text default, gain default (still unused)
    for s in STEM_ORDER:
        if stems and s in stems:
            tmp = export_temp_wav(stems[s], prefix=f"stem_{s}_")
            include_val = (s in prev_choices) if prev_choices is not None else (s in DEFAULT_INCLUDE)
            outputs.extend([tmp, include_val, "", "", 0])
        else:
            outputs.extend([gr.update(value=None), gr.update(value=(s in DEFAULT_INCLUDE)), "", "", 0])
    return (*outputs, dict(stems))

# Apply silence function
def apply_silence_for_stem(stems, stem_name, start_txt, end_txt):
    if not stems or stem_name not in stems:
        return stems, gr.update(value=None), "No such stem to silence."
    try:
        start_ms = parse_time_mmss(start_txt) if start_txt else None
        end_ms = parse_time_mmss(end_txt) if end_txt else None
    except ValueError as e:
        return stems, gr.update(value=None), f"Invalid time format: {e}"
    seg = stems[stem_name]
    new_seg = silence_range(seg, start_ms, end_ms)
    stems = dict(stems)
    stems[stem_name] = new_seg
    tmp = export_temp_wav(new_seg, prefix=f"stem_{stem_name}_")
    msg = f"Silenced {stem_name} from {start_txt or 'start'} to {end_txt or 'end'}."
    return stems, tmp, msg

# Apply gain function
def apply_gain_for_stem(stems, stem_name, gain_db):
    if not stems or stem_name not in stems:
        return stems, gr.update(value=None), "No such stem to apply gain."
    new_seg = stems[stem_name].apply_gain(gain_db)
    stems = dict(stems)
    stems[stem_name] = new_seg
    tmp = export_temp_wav(new_seg, prefix=f"stem_{stem_name}_")
    msg = f"Applied {gain_db} dB to {stem_name}."
    return stems, tmp, msg

# Rebuild mix from edited stems using per-stem include checkboxes
def rebuild_from_edited(stems,
                        inc_vocals, inc_guitar, inc_piano, inc_drums, inc_bass, inc_other,
                        addstick):
    if not stems:
        return gr.update(value=None), gr.update(value=None)
    include_map = {
        "vocals": inc_vocals, "guitar": inc_guitar, "piano": inc_piano,
        "drums": inc_drums, "bass": inc_bass, "other": inc_other
    }
    included = [k for k, v in include_map.items() if v]
    mix = build_mix_from_stems(stems, included, addstick)
    outp = export_temp_wav(mix, prefix="editedmix_")
    return outp, gr.update(visible=True, value=outp)
