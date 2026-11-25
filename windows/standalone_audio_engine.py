#!/usr/bin/env python3
"""
P61x Console (Windows & Linux Standalone) - Unified Low-Latency 4-Zone Synth,
5-Layer Continuous Worship Pad & 4-Slot Stereo Drum Pad Audio Engine
(standalone_audio_engine.py — v1.3.3)
"""

from __future__ import annotations

import copy
import ctypes
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from typing import Dict, List, Optional, Tuple

import numpy as np

from standalone_timbre_catalog import CONFIG_DIR, TimbreCatalog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_RIG_DIR = os.path.dirname(BASE_DIR)

DSP_DIR = os.path.join(BASE_DIR, "dsp")
DSP_C_PATH = os.path.join(DSP_DIR, "stagerig_dsp.c")
DSP_SO_NAME = (
    "stagerig_dsp.dll"
    if sys.platform == "win32"
    else ("libstagerig_dsp.dylib" if sys.platform == "darwin" else "libstagerig_dsp.so")
)
DSP_SO_PATH = os.path.join(DSP_DIR, DSP_SO_NAME)
AUDIO_CONFIG_FILE = os.path.join(CONFIG_DIR, "audio_config.json")
DRUM_PADS_STATE_FILE = os.path.join(CONFIG_DIR, "drum_pads_state.json")

PAD_LOOPS_DIR = os.path.join(BASE_DIR, "pad_loops")
DRUM_PADS_DIR = os.path.join(BASE_DIR, "drum_pads")
CUSTOM_DRUMS_DIR = os.path.join(CONFIG_DIR, "custom_drums")
LOCAL_PAD_CACHE_DIR = (
    os.path.join(BASE_DIR, "cache", "pad_cache")
    if (os.access(BASE_DIR, os.W_OK) and not BASE_DIR.startswith("/opt/"))
    else os.path.expanduser(
        "~/AppData/Local/P61xConsole/pad_cache"
        if sys.platform == "win32"
        else (
            "~/Library/Caches/P61xConsole/pad_cache"
            if sys.platform == "darwin"
            else "~/.cache/P61xConsole/pad_cache"
        )
    )
)

SAMPLE_RATE = 44100
DEFAULT_BLOCK_SIZE = 256  # 5.80 ms real-time low-latency block size

MUSICAL_KEYS: List[dict] = [
    {"id": 0,  "major": "C",  "minor": "Am",  "label": "C / Am",   "semitones": 0},
    {"id": 1,  "major": "C#", "minor": "A#m", "label": "C# / A#m", "semitones": 1},
    {"id": 2,  "major": "D",  "minor": "Bm",  "label": "D / Bm",   "semitones": 2},
    {"id": 3,  "major": "D#", "minor": "Cm",  "label": "D# / Cm",  "semitones": 3},
    {"id": 4,  "major": "E",  "minor": "C#m", "label": "E / C#m",  "semitones": 4},
    {"id": 5,  "major": "F",  "minor": "Dm",  "label": "F / Dm",   "semitones": 5},
    {"id": 6,  "major": "F#", "minor": "D#m", "label": "F# / D#m", "semitones": 6},
    {"id": 7,  "major": "G",  "minor": "Em",  "label": "G / Em",   "semitones": -5},
    {"id": 8,  "major": "G#", "minor": "Fm",  "label": "G# / Fm",  "semitones": -4},
    {"id": 9,  "major": "A",  "minor": "F#m", "label": "A / F#m",  "semitones": -3},
    {"id": 10, "major": "A#", "minor": "Gm",  "label": "A# / Gm",  "semitones": -2},
    {"id": 11, "major": "B",  "minor": "G#m", "label": "B / G#m",  "semitones": -1},
]

PAD_LAYERS_SPEC: List[dict] = [
    {
        "index": 0,
        "id": "pad_base",
        "name": "Warm Pad",
        "ogg_file": "pad_layer_0.ogg",
        "cache_file": "pad_layer_0.npy",
        "default_vol": 100,
        "color": "#a855f7",
    },
    {
        "index": 1,
        "id": "pad_cello",
        "name": "Cello Pad",
        "ogg_file": "pad_layer_1.ogg",
        "cache_file": "pad_layer_1.npy",
        "default_vol": 85,
        "color": "#f43f5e",
    },
    {
        "index": 2,
        "id": "pad_flute",
        "name": "Flute Pad",
        "ogg_file": "pad_layer_2.ogg",
        "cache_file": "pad_layer_2.npy",
        "default_vol": 75,
        "color": "#14b8a6",
    },
    {
        "index": 3,
        "id": "pad_ambient",
        "name": "Ambient Pad",
        "ogg_file": "pad_layer_3.ogg",
        "cache_file": "pad_layer_3.npy",
        "default_vol": 80,
        "color": "#3b82f6",
    },
]

DRUM_COLORS = ["#f59e0b", "#ec4899", "#06b6d4", "#22c55e"]


class _SF_INFO(ctypes.Structure):
    _fields_ = [
        ("frames", ctypes.c_int64),
        ("samplerate", ctypes.c_int),
        ("channels", ctypes.c_int),
        ("format", ctypes.c_int),
        ("sections", ctypes.c_int),
        ("seekable", ctypes.c_int),
    ]


_SNDFILE_LIB = None


def _get_sndfile_lib():
    global _SNDFILE_LIB
    if _SNDFILE_LIB is not None:
        return _SNDFILE_LIB
    candidates = [
        os.path.join(DSP_DIR, "sndfile.dll"),
        "libsndfile.so.1",
        "libsndfile.so",
        "/opt/homebrew/lib/libsndfile.dylib",
        "/usr/local/lib/libsndfile.dylib",
        "libsndfile.dylib",
    ]
    for c in candidates:
        try:
            lib = ctypes.CDLL(c)
            lib.sf_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_SF_INFO)]
            lib.sf_open.restype = ctypes.c_void_p
            try:
                lib.sf_wchar_open.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(_SF_INFO)]
                lib.sf_wchar_open.restype = ctypes.c_void_p
            except AttributeError:
                pass
            lib.sf_readf_float.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
            lib.sf_readf_float.restype = ctypes.c_int64
            lib.sf_close.argtypes = [ctypes.c_void_p]
            lib.sf_close.restype = ctypes.c_int
            _SNDFILE_LIB = lib
            return lib
        except Exception:
            pass
    _SNDFILE_LIB = False
    return False


def decode_audio_file_stereo_f32(file_path: str) -> Optional[np.ndarray]:
    """
    Decodes .ogg, .wav, or .flac into a stereo float32 (N, 2) numpy array at 44100 Hz.
    Uses bundled dsp/sndfile.dll (libsndfile) first, with Python wave and ffmpeg fallbacks.
    """
    if not os.path.isfile(file_path):
        return None

    # 1. Fast native decode via libsndfile (dsp/sndfile.dll on Windows / libsndfile.so.1 on Linux)
    sflib = _get_sndfile_lib()
    if sflib:
        try:
            info = _SF_INFO()
            sf = None
            if sys.platform == "win32" and hasattr(sflib, "sf_wchar_open"):
                try:
                    sf = sflib.sf_wchar_open(file_path, 0x10, ctypes.byref(info))
                except Exception:
                    sf = None
            if not sf:
                enc = "mbcs" if sys.platform == "win32" else "utf-8"
                sf = sflib.sf_open(file_path.encode(enc, errors="replace"), 0x10, ctypes.byref(info))  # SFM_READ = 0x10
            if sf and info.frames > 0 and info.channels > 0:
                total_frames = int(info.frames)
                ch = int(info.channels)
                buf = np.zeros((total_frames, ch), dtype=np.float32)
                read_frames = int(sflib.sf_readf_float(sf, buf.ctypes.data, total_frames))
                sflib.sf_close(sf)
                if read_frames > 0:
                    buf = buf[:read_frames]
                    if ch == 1:
                        buf = np.column_stack([buf[:, 0], buf[:, 0]])
                    elif ch > 2:
                        buf = buf[:, :2]
                    return np.ascontiguousarray(buf, dtype=np.float32)
        except Exception:
            pass

    # 2. Pure Python wave module fallback for .wav files
    if file_path.lower().endswith(".wav"):
        try:
            with wave.open(file_path, "rb") as wf:
                ch = wf.getnchannels()
                sw = wf.getsampwidth()
                nframes = wf.getnframes()
                raw = wf.readframes(nframes)
            if sw == 2:
                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif sw == 4:
                pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            pcm = pcm.reshape(-1, ch)
            if ch == 1:
                pcm = np.column_stack([pcm[:, 0], pcm[:, 0]])
            elif ch > 2:
                pcm = pcm[:, :2]
            return np.ascontiguousarray(pcm, dtype=np.float32)
        except Exception:
            pass

    # 3. ffmpeg fallback
    try:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            file_path,
            "-f",
            "f32le",
            "-ac",
            "2",
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ]
        kw = {"timeout": 20}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        raw = subprocess.check_output(cmd, **kw)
        pcm = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()
        return np.ascontiguousarray(pcm, dtype=np.float32)
    except Exception as e:
        print(f"[StandaloneAudio] Erro ao decodificar {file_path}: {e}")
        return None


def _ensure_dsp_library_compiled() -> str:
    """Compiles dsp/stagerig_dsp.c into dsp/libstagerig_dsp.so on Linux or verifies stagerig_dsp.dll on Windows."""
    if os.path.isfile(DSP_SO_PATH):
        if sys.platform == "win32":
            return DSP_SO_PATH
        if os.path.isfile(DSP_C_PATH) and os.path.getmtime(DSP_C_PATH) <= os.path.getmtime(DSP_SO_PATH):
            return DSP_SO_PATH

    if sys.platform == "win32":
        return DSP_SO_PATH

    os.makedirs(DSP_DIR, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(
            [
                "clang",
                "-O3",
                "-fno-math-errno",
                "-dynamiclib",
                "-fPIC",
                "-I/opt/homebrew/include",
                "-I/usr/local/include",
                DSP_C_PATH,
                "-o",
                DSP_SO_PATH,
                "-L/opt/homebrew/lib",
                "-L/usr/local/lib",
                "-lfluidsynth",
                "-lportaudio",
                "-lpthread",
                "-lm",
                "-Wl,-rpath,/opt/homebrew/lib",
                "-Wl,-rpath,/usr/local/lib",
            ],
            check=True,
        )
        return DSP_SO_PATH
    subprocess.run(
        [
            "gcc",
            "-O3",
            "-march=native",
            "-fno-math-errno",
            "-shared",
            "-fPIC",
            DSP_C_PATH,
            "-o",
            DSP_SO_PATH,
            "-lfluidsynth",
            "-lportaudio",
            "-lpthread",
            "-lm",
        ],
        check=True,
    )
    return DSP_SO_PATH


def _load_or_build_pad_cache(spec: dict) -> Optional[np.ndarray]:
    os.makedirs(LOCAL_PAD_CACHE_DIR, exist_ok=True)
    local_path = os.path.join(LOCAL_PAD_CACHE_DIR, spec["cache_file"])
    if os.path.isfile(local_path):
        try:
            arr = np.load(local_path, mmap_mode="r")
            if arr.ndim == 2 and arr.shape[1] == 2 and arr.shape[0] > SAMPLE_RATE * 2:
                return arr
        except Exception:
            pass

    ogg_path = os.path.join(PAD_LOOPS_DIR, spec["ogg_file"])
    pcm = decode_audio_file_stereo_f32(ogg_path)
    if pcm is not None and pcm.shape[0] > 1024:
        try:
            np.save(local_path, pcm)
            return np.load(local_path, mmap_mode="r")
        except Exception:
            return pcm
    return None


class StandaloneAudioEngine:
    """
    Unified Real-Time 4-Zone Synthesizer, 5-Layer Worship Pad & 4-Slot Drum Pad Engine.
    """

    def __init__(self, catalog: TimbreCatalog) -> None:
        self._lock = threading.RLock()
        self._stream_lifecycle_lock = threading.Lock()
        self._sf_lock = threading.Lock()
        self._preset_lock = threading.Lock()
        self._preset_apply_seq = 0
        self._shutting_down = False
        self.stream_recoveries: int = 0
        self.catalog = catalog

        self.block_size: int = DEFAULT_BLOCK_SIZE
        self.output_device: str = "default"
        self.global_transpose: int = 0
        self.master_fx: dict = {
            "rev_room": 0.84,
            "rev_damp": 0.28,
            "rev_level": 1.10,
            "dly_feedback": 0.36,
            "dly_level": 0.52,
        }
        self._load_audio_config()

        if sys.platform == "win32":
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(DSP_DIR)
                except Exception:
                    pass
            os.environ["PATH"] = DSP_DIR + os.pathsep + os.environ.get("PATH", "")

        so_path = _ensure_dsp_library_compiled()
        self._lib = ctypes.CDLL(so_path)
        self._bind_c_signatures()
        if sys.platform == "win32":
            self.install_crash_handler()
        self._dsp = self._lib.stagerig_create(float(SAMPLE_RATE))
        self.set_master_fx(**self.master_fx)

        self._loaded_sfids: Dict[str, int] = {}

        # Independent Dual Masters (Synth Master & Pad Master)
        self.synth_master_vol: int = 110
        self.synth_master_muted: bool = False
        self.pad_master_vol: int = 110
        self.pad_master_muted: bool = False
        self.master_volume: int = 110
        self.master_muted: bool = False
        self.master_target: str = "all"

        # 4-Layer Continuous Worship Pad State
        self.pad_ready: bool = False
        self.pad_playing: bool = False
        self.pad_key_id: int = 0
        self.pad_octave: int = 0
        self.pad_filter_cc: int = 110
        self.pad_volumes: List[int] = [s["default_vol"] for s in PAD_LAYERS_SPEC]
        self.pad_mutes: List[bool] = [False] * len(PAD_LAYERS_SPEC)
        self.pad_peaks: List[float] = [0.0] * len(PAD_LAYERS_SPEC)

        # 4-Slot Stereo Drum Pads State
        self.drum_catalog: List[dict] = []
        self.drum_pads: List[dict] = []
        self.drum_peaks: List[float] = [0.0] * 4
        self._init_drum_pads_metadata()

        # Real-time telemetry state
        self.last_synth_master_peak: float = 0.0
        self.last_pad_master_peak: float = 0.0
        self.last_master_peak: float = 0.0
        self.stream_active: bool = False
        self.reported_latency_ms: float = round((self.block_size / SAMPLE_RATE) * 1000.0, 2)

        self._sync_masters_to_dsp()
        self._sync_pad_to_dsp()

        threading.Thread(target=self._init_pad_and_drum_buffers, daemon=True).start()
        self.start_audio_stream()

    def install_crash_handler(self, rearm_only: bool = False) -> None:
        if sys.platform != "win32":
            return
        try:
            fn = getattr(self._lib, "stagerig_install_crash_handler", None)
            if fn is None:
                return
            if rearm_only:
                fn(None)
                return
            log_path = os.environ.get("P61X_RUNTIME_LOG", "")
            if not log_path:
                local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
                log_dir = os.path.join(local_app, "P61x Console", "logs")
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, "p61x_runtime.log")
            fn(log_path.encode("utf-8"))
        except Exception:
            pass

    def _bind_c_signatures(self) -> None:
        L = self._lib
        if sys.platform == "win32":
            for _sym in (
                "stagerig_install_crash_handler",
                "stagerig_winmm_in_count",
                "stagerig_winmm_in_name_utf8",
                "stagerig_winmm_in_open",
                "stagerig_winmm_in_close",
                "stagerig_winmm_in_is_open",
                "stagerig_winmm_in_poll",
            ):
                if not hasattr(L, _sym):
                    break
            else:
                L.stagerig_install_crash_handler.argtypes = [ctypes.c_char_p]
                L.stagerig_install_crash_handler.restype = None
                L.stagerig_winmm_in_count.argtypes = []
                L.stagerig_winmm_in_count.restype = ctypes.c_int
                L.stagerig_winmm_in_name_utf8.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
                L.stagerig_winmm_in_name_utf8.restype = ctypes.c_int
                L.stagerig_winmm_in_open.argtypes = [ctypes.c_int]
                L.stagerig_winmm_in_open.restype = ctypes.c_int
                L.stagerig_winmm_in_close.argtypes = []
                L.stagerig_winmm_in_close.restype = None
                L.stagerig_winmm_in_is_open.argtypes = []
                L.stagerig_winmm_in_is_open.restype = ctypes.c_int
                L.stagerig_winmm_in_poll.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_int]
                L.stagerig_winmm_in_poll.restype = ctypes.c_int
        L.stagerig_create.argtypes = [ctypes.c_float]
        L.stagerig_create.restype = ctypes.c_void_p
        L.stagerig_destroy.argtypes = [ctypes.c_void_p]
        L.stagerig_load_soundfont.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.stagerig_load_soundfont.restype = ctypes.c_int
        L.stagerig_unload_soundfont.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.stagerig_unload_soundfont.restype = ctypes.c_int
        L.stagerig_set_zone_program.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        L.stagerig_set_zone_program.restype = ctypes.c_int
        L.stagerig_set_zone_volume.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_mute.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_solo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_fx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_chorus.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_envelope.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_pan.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_tone.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_filter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.stagerig_set_zone_eq.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        L.stagerig_set_zone_params.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        L.stagerig_set_bpm.argtypes = [ctypes.c_void_p, ctypes.c_float]
        L.stagerig_set_master_fx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        L.stagerig_note_on.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_note_off.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.stagerig_send_performance_cc.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.stagerig_pitch_bend.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.stagerig_panic.argtypes = [ctypes.c_void_p]
        L.stagerig_get_telemetry_v2.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_int),
        ]
        L.stagerig_set_pad_layer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        L.stagerig_set_pad_layers_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        L.stagerig_set_masters_state.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        L.stagerig_set_drum_pad_sample.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        L.stagerig_set_drum_pad_params.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        L.stagerig_trigger_drum_pad.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        L.stagerig_pa_device_count.argtypes = []
        L.stagerig_pa_device_count.restype = ctypes.c_int
        L.stagerig_pa_get_device_info.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
        ]
        L.stagerig_pa_get_device_info.restype = ctypes.c_int
        L.stagerig_start_stream.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_double),
        ]
        L.stagerig_start_stream.restype = ctypes.c_int
        L.stagerig_stop_stream.argtypes = [ctypes.c_void_p]
        L.stagerig_get_stream_stats.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        L.stagerig_simulate_stream_abort.argtypes = [ctypes.c_void_p]
        L.stagerig_render_block.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]

    def _load_audio_config(self) -> None:
        if os.path.isfile(AUDIO_CONFIG_FILE):
            try:
                with open(AUDIO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                bsz = int(cfg.get("block_size", DEFAULT_BLOCK_SIZE))
                if bsz in (128, 256, 512, 1024):
                    self.block_size = bsz
                dev = str(cfg.get("output_device", "default")).strip()
                if dev:
                    self.output_device = dev
                self.global_transpose = max(-12, min(12, int(cfg.get("global_transpose", 0))))
                if isinstance(cfg.get("master_fx"), dict):
                    self.master_fx.update(cfg["master_fx"])
            except Exception:
                pass

    def _save_audio_config(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(AUDIO_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "block_size": self.block_size,
                        "output_device": self.output_device,
                        "global_transpose": self.global_transpose,
                        "master_fx": self.master_fx,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            pass

    def _init_drum_pads_metadata(self) -> None:
        os.makedirs(CUSTOM_DRUMS_DIR, exist_ok=True)
        cat_path = os.path.join(DRUM_PADS_DIR, "catalog.json")
        defaults = [
            "01_Worship_Arena_Kick",
            "06_Worship_Arena_Snare",
            "11_Worship_Shimmer_Ride",
            "17_Worship_Dark_Crash",
        ]
        if os.path.isfile(cat_path):
            try:
                with open(cat_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                self.drum_catalog = list(cdata.get("samples", []))
                if isinstance(cdata.get("defaults"), list) and len(cdata["defaults"]) >= 4:
                    defaults = cdata["defaults"][:4]
            except Exception:
                pass

        # Scan custom drums
        for wav_path in sorted(glob.glob(os.path.join(CUSTOM_DRUMS_DIR, "*.*"))):
            fname = os.path.basename(wav_path)
            sid = "custom_" + os.path.splitext(fname)[0]
            if not any(s.get("id") == sid for s in self.drum_catalog):
                self.drum_catalog.append(
                    {
                        "id": sid,
                        "filename": fname,
                        "custom_path": wav_path,
                        "name": os.path.splitext(fname)[0],
                        "category": "Custom",
                        "style": "User",
                    }
                )

        if os.path.isfile(DRUM_PADS_STATE_FILE):
            try:
                with open(DRUM_PADS_STATE_FILE, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                if isinstance(sdata.get("pads"), list) and len(sdata["pads"]) >= 4:
                    self.drum_pads = sdata["pads"][:4]
            except Exception:
                pass

        if len(self.drum_pads) < 4:
            self.drum_pads = []
            for idx in range(4):
                sid = defaults[idx] if idx < len(defaults) else ""
                samp = next((s for s in self.drum_catalog if s.get("id") == sid), None)
                self.drum_pads.append(
                    {
                        "index": idx,
                        "sample_id": sid,
                        "name": samp["name"] if samp else f"Pad {idx + 1}",
                        "category": samp.get("category", "Drum") if samp else "Drum",
                        "style": samp.get("style", "Worship") if samp else "Worship",
                        "volume": 112,
                        "muted": False,
                        "loop": False,
                        "color": DRUM_COLORS[idx % len(DRUM_COLORS)],
                    }
                )

    def _save_drum_pads_state(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(DRUM_PADS_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"pads": self.drum_pads}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _load_drum_slot_into_dsp(self, pad_idx: int) -> None:
        if self._shutting_down or not self._dsp or pad_idx < 0 or pad_idx >= len(self.drum_pads):
            return
        pad = self.drum_pads[pad_idx]
        sid = pad.get("sample_id", "")
        samp = next((s for s in self.drum_catalog if s.get("id") == sid), None)
        wav_path = None
        if samp:
            if samp.get("custom_path") and os.path.isfile(samp["custom_path"]):
                wav_path = samp["custom_path"]
            elif samp.get("filename"):
                cand = os.path.join(DRUM_PADS_DIR, samp["filename"])
                if os.path.isfile(cand):
                    wav_path = cand
                else:
                    cand_c = os.path.join(CUSTOM_DRUMS_DIR, samp["filename"])
                    if os.path.isfile(cand_c):
                        wav_path = cand_c

        if wav_path:
            pcm = decode_audio_file_stereo_f32(wav_path)
            if pcm is not None and not self._shutting_down and self._dsp:
                self._lib.stagerig_set_drum_pad_sample(self._dsp, pad_idx, pcm.ctypes.data, int(pcm.shape[0]))
        self._lib.stagerig_set_drum_pad_params(
            self._dsp,
            pad_idx,
            int(pad.get("volume", 112)),
            1 if pad.get("muted") else 0,
            1 if pad.get("loop") else 0,
        )

    def _init_pad_and_drum_buffers(self) -> None:
        any_loaded = False
        for idx, spec in enumerate(PAD_LAYERS_SPEC):
            arr = _load_or_build_pad_cache(spec)
            if arr is not None and not self._shutting_down and self._dsp:
                try:
                    ram_arr = np.ascontiguousarray(arr, dtype=np.float32)
                    self._lib.stagerig_set_pad_layer(
                        self._dsp, idx, ram_arr.ctypes.data, int(ram_arr.shape[0])
                    )
                    any_loaded = True
                except Exception as e:
                    print(f"[StandaloneAudio] Pad layer {idx} load failed: {e}")
        with self._lock:
            self.pad_ready = any_loaded
        self._sync_pad_to_dsp()

        for d in range(4):
            if self._shutting_down:
                return
            self._load_drum_slot_into_dsp(d)

    # -------------------------------------------------------------------------
    # Audio Output Device & Native C Zero-GIL PortAudio Stream Lifecycle
    # -------------------------------------------------------------------------
    def list_audio_output_devices(self) -> List[dict]:
        devices: List[dict] = []
        try:
            count = int(self._lib.stagerig_pa_device_count())
            name_buf = ctypes.create_string_buffer(256)
            max_out = ctypes.c_int()
            def_sr = ctypes.c_double()
            low_lat = ctypes.c_double()
            is_def = ctypes.c_int()
            for idx in range(count):
                rc = self._lib.stagerig_pa_get_device_info(
                    idx,
                    name_buf,
                    256,
                    ctypes.byref(max_out),
                    ctypes.byref(def_sr),
                    ctypes.byref(low_lat),
                    ctypes.byref(is_def),
                )
                if rc != 0 or int(max_out.value) < 2:
                    continue
                name = name_buf.value.decode("utf-8", errors="replace") or f"Device {idx}"
                low_name = name.lower()
                is_usb = any(k in low_name for k in ("usb", "asio", "focusrite", "scarlett", "behringer", "umc", "steinberg"))
                devices.append(
                    {
                        "index": idx,
                        "id": name,
                        "name": name,
                        "channels": int(max_out.value),
                        "is_default": bool(is_def.value),
                        "category": "usb" if is_usb else "system",
                    }
                )
        except Exception:
            pass
        return devices

    def set_audio_config(self, output_device: str, block_size: int) -> dict:
        bsz = int(block_size) if int(block_size) in (128, 256, 512, 1024) else DEFAULT_BLOCK_SIZE
        dev = str(output_device or "default").strip()
        with self._lock:
            self.output_device = dev
            self.block_size = bsz
            self._save_audio_config()
        self.restart_audio_stream()
        return self.get_audio_config()

    def get_audio_config(self) -> dict:
        return {
            "output_device": self.output_device,
            "block_size": self.block_size,
            "sample_rate": SAMPLE_RATE,
            "latency_ms": self.reported_latency_ms,
            "devices": self.list_audio_output_devices(),
            "master_fx": dict(self.master_fx),
        }

    def get_audio_route_status(self) -> dict:
        devs = self.list_audio_output_devices()
        active_dev = next((d for d in devs if d["id"] == self.output_device), None)
        if not active_dev:
            active_dev = next((d for d in devs if d.get("is_default")), devs[0] if devs else None)
        dev_name = active_dev["name"] if active_dev else "Saída Padrão do Sistema"
        is_usb = bool(active_dev and active_dev.get("category") == "usb")
        if sys.platform == "win32":
            route_label = "WASAPI / PortAudio"
        elif sys.platform == "darwin":
            route_label = "CoreAudio / PortAudio"
        else:
            route_label = "PipeWire / ALSA"
        return {
            "deviceName": dev_name,
            "routeLabel": route_label,
            "routeType": "usb" if is_usb else "speaker",
            "isUsbAudio": is_usb,
            "blockSize": self.block_size,
            "sampleRate": SAMPLE_RATE,
            "latencyMs": self.reported_latency_ms,
            "devices": devs,
        }

    def start_audio_stream(self) -> bool:
        with self._stream_lifecycle_lock:
            if self._shutting_down or not self._dsp:
                return False
            out_lat_ms = ctypes.c_double(round((self.block_size / SAMPLE_RATE) * 1000.0, 2))
            dev_bytes = str(self.output_device or "default").encode("utf-8", errors="replace")
            rc = int(
                self._lib.stagerig_start_stream(
                    self._dsp,
                    dev_bytes,
                    float(SAMPLE_RATE),
                    int(self.block_size),
                    ctypes.byref(out_lat_ms),
                )
            )
            if rc == 0:
                self.stream_active = True
                self.reported_latency_ms = round(float(out_lat_ms.value), 2)
                return True
            self.stream_active = False
            return False

    def stop_audio_stream(self) -> None:
        with self._stream_lifecycle_lock:
            if self._dsp:
                self._lib.stagerig_stop_stream(self._dsp)
            self.stream_active = False

    def restart_audio_stream(self) -> bool:
        self.stop_audio_stream()
        return self.start_audio_stream()

    def _get_c_stream_stats(self) -> Tuple[bool, bool, int, int, int]:
        if not self._dsp:
            return False, False, 0, 0, 0
        active = ctypes.c_int()
        aborted = ctypes.c_int()
        cb_cnt = ctypes.c_uint64()
        xruns = ctypes.c_uint64()
        ago_ms = ctypes.c_uint64()
        self._lib.stagerig_get_stream_stats(
            self._dsp,
            ctypes.byref(active),
            ctypes.byref(aborted),
            ctypes.byref(cb_cnt),
            ctypes.byref(xruns),
            ctypes.byref(ago_ms),
        )
        return (
            bool(active.value),
            bool(aborted.value),
            int(cb_cnt.value),
            int(xruns.value),
            int(ago_ms.value),
        )

    def check_stream_health(self) -> bool:
        if self._shutting_down or not self._dsp:
            return False
        active, aborted, _, _, ago_ms = self._get_c_stream_stats()
        is_dead = (not active) or aborted or (ago_ms > 1500)
        if is_dead:
            ok = self.restart_audio_stream()
            if ok:
                self.stream_recoveries += 1
            return ok
        self.stream_active = True
        return True

    # -------------------------------------------------------------------------
    # SoundFont & 4-Zone Preset Loading
    # -------------------------------------------------------------------------
    def get_or_load_sfid(self, sf2_path: str) -> int:
        with self._sf_lock:
            if self._shutting_down or not self._dsp:
                return -1
            if sf2_path in self._loaded_sfids:
                return self._loaded_sfids[sf2_path]
            sfid = int(self._lib.stagerig_load_soundfont(self._dsp, sf2_path.encode("utf-8")))
            if sfid > 0:
                self._loaded_sfids[sf2_path] = sfid
            return sfid

    def set_zone_timbre(self, zone_idx: int, lib_id: str) -> Optional[dict]:
        if self._shutting_down or not self._dsp:
            return None
        z = max(0, min(3, int(zone_idx)))
        info = self.catalog.resolve_timbre(lib_id)
        if not info:
            return None
        sfid = self.get_or_load_sfid(info["sf2_path"])
        if sfid > 0 and not self._shutting_down and self._dsp:
            self._lib.stagerig_set_zone_program(
                self._dsp, z, sfid, int(info["bank"]), int(info["prog"])
            )
        return info

    def bump_preset_generation(self) -> int:
        with self._lock:
            self._preset_apply_seq += 1
            return self._preset_apply_seq

    def apply_preset(self, preset: dict, target_seq: Optional[int] = None) -> None:
        with self._preset_lock:
            if self._shutting_down or not self._dsp:
                return
            if target_seq is not None and target_seq != self._preset_apply_seq:
                return

            bpm = float(preset.get("bpm", 120.0))
            self._lib.stagerig_set_bpm(self._dsp, bpm)

            libs = preset.get("libs", [])
            vols = preset.get("volumes", [100, 80, 50, 80])
            mutes = preset.get("mutes", [False, False, False, False])
            revs = preset.get("rev", [60, 60, 60, 80])
            dlys = preset.get("dly", [35, 35, 35, 45])
            choruses = preset.get("chorus", [0, 0, 0, 0])
            attacks = preset.get("attacks", [0, 0, 0, 0])
            releases = preset.get("releases", [64, 64, 64, 64])
            transposes = preset.get("transposes", [0, 0, 0, 0])
            key_lows = preset.get("key_lows", [21, 21, 21, 21])
            key_his = preset.get("key_his", [108, 108, 108, 108])
            pans = preset.get("pans", [64, 64, 64, 64])
            cutoffs = preset.get("cutoffs", [127, 127, 127, 127])
            resonances = preset.get("resonances", [0, 0, 0, 0])
            tones = preset.get("tones", [64, 64, 64, 64])
            eqs = preset.get("eqs", [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)])
            sustains = preset.get("sustain_enables", [True, True, True, True])

            for z in range(4):
                self._lib.stagerig_set_zone_volume(self._dsp, z, int(vols[z]) if z < len(vols) else 100)
                self._lib.stagerig_set_zone_mute(self._dsp, z, 1 if (z < len(mutes) and mutes[z]) else 0)
                self._lib.stagerig_set_zone_solo(self._dsp, z, 0)
                self._lib.stagerig_set_zone_fx(self._dsp, z, 0, int(revs[z]) if z < len(revs) else 50)
                self._lib.stagerig_set_zone_fx(self._dsp, z, 1, int(dlys[z]) if z < len(dlys) else 35)
                self._lib.stagerig_set_zone_chorus(self._dsp, z, int(choruses[z]) if z < len(choruses) else 0)
                self._lib.stagerig_set_zone_envelope(
                    self._dsp,
                    z,
                    int(attacks[z]) if z < len(attacks) else 0,
                    int(releases[z]) if z < len(releases) else 64,
                )
                self._lib.stagerig_set_zone_pan(self._dsp, z, int(pans[z]) if z < len(pans) else 64)
                cut_v = int(cutoffs[z]) if z < len(cutoffs) else 127
                res_v = int(resonances[z]) if z < len(resonances) else 0
                tone_v = int(tones[z]) if z < len(tones) else 64
                self._lib.stagerig_set_zone_filter(self._dsp, z, cut_v, res_v, tone_v)
                eq_z = eqs[z] if (z < len(eqs) and isinstance(eqs[z], (list, tuple)) and len(eqs[z]) >= 5) else [0.0] * 5
                self._lib.stagerig_set_zone_eq(
                    self._dsp, z, float(eq_z[0]), float(eq_z[1]), float(eq_z[2]), float(eq_z[3]), float(eq_z[4])
                )
                tr = (int(transposes[z]) if z < len(transposes) else 0) + self.global_transpose
                kl = int(key_lows[z]) if z < len(key_lows) else 21
                kh = int(key_his[z]) if z < len(key_his) else 108
                sus = 1 if (z >= len(sustains) or sustains[z]) else 0
                self._lib.stagerig_set_zone_params(self._dsp, z, tr, kl, kh, 0, 127, sus, 1)

            for z in range(4):
                if self._shutting_down or (target_seq is not None and target_seq != self._preset_apply_seq):
                    return
                if z < len(libs) and libs[z]:
                    self.set_zone_timbre(z, libs[z])

            self._lib.stagerig_send_performance_cc(self._dsp, 11, 127)
            self._lib.stagerig_send_performance_cc(self._dsp, 64, 0)
            self._lib.stagerig_send_performance_cc(self._dsp, 1, 0)
            self._lib.stagerig_pitch_bend(self._dsp, 8192)

    def prewarm_presets_background(self, presets: List[dict]) -> None:
        base_seq = self._preset_apply_seq

        def _worker() -> None:
            time.sleep(1.5)
            seen_paths = set()
            loaded_count = 0
            for p in presets[:5]:
                if self._shutting_down or base_seq != self._preset_apply_seq:
                    return
                for lid in p.get("libs", []):
                    if self._shutting_down or base_seq != self._preset_apply_seq:
                        return
                    try:
                        info = self.catalog.resolve_timbre(lid)
                        sf2_path = info.get("sf2_path") if info else None
                        if sf2_path and sf2_path not in seen_paths and sf2_path not in self._loaded_sfids:
                            seen_paths.add(sf2_path)
                            self.get_or_load_sfid(sf2_path)
                            loaded_count += 1
                            time.sleep(0.15)
                            if loaded_count >= 5:
                                return
                    except Exception:
                        pass

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # Real-Time 4-Zone Performance & Mixer Controls
    # -------------------------------------------------------------------------
    def note_on(self, note: int, velocity: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_note_on(self._dsp, int(note), int(velocity))

    def note_off(self, note: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_note_off(self._dsp, int(note))

    def send_performance_cc(self, cc: int, value: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_send_performance_cc(self._dsp, int(cc), int(value))

    def pitch_bend(self, bend_14bit: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_pitch_bend(self._dsp, int(bend_14bit))

    def set_zone_volume(self, zone_idx: int, value: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_volume(self._dsp, int(zone_idx), int(value))

    def set_zone_mute(self, zone_idx: int, muted: bool) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_mute(self._dsp, int(zone_idx), 1 if muted else 0)

    def set_zone_solo(self, zone_idx: int, soloed: bool) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_solo(self._dsp, int(zone_idx), 1 if soloed else 0)

    def set_zone_fx(self, zone_idx: int, fx_type: str, value: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        if fx_type == "chorus":
            self._lib.stagerig_set_zone_chorus(self._dsp, int(zone_idx), int(value))
            return
        is_dly = 1 if fx_type == "dly" else 0
        self._lib.stagerig_set_zone_fx(self._dsp, int(zone_idx), is_dly, int(value))

    def set_zone_chorus(self, zone_idx: int, value: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_chorus(self._dsp, int(zone_idx), int(value))

    def set_zone_envelope(self, zone_idx: int, attack: int, release: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_envelope(self._dsp, int(zone_idx), int(attack), int(release))

    def set_zone_pan(self, zone_idx: int, pan_cc: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_pan(self._dsp, int(zone_idx), int(pan_cc))

    def set_zone_tone(self, zone_idx: int, cutoff_cc: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_tone(self._dsp, int(zone_idx), int(cutoff_cc))

    def set_zone_filter(self, zone_idx: int, cutoff_cc: int, resonance_cc: int, tone_cc: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_filter(
            self._dsp, int(zone_idx), int(cutoff_cc), int(resonance_cc), int(tone_cc)
        )

    def set_zone_eq(
        self,
        zone_idx: int,
        low_db: float,
        low_mid_db: float,
        mid_db: float,
        high_mid_db: float,
        high_db: float,
    ) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_zone_eq(
            self._dsp,
            int(zone_idx),
            float(low_db),
            float(low_mid_db),
            float(mid_db),
            float(high_mid_db),
            float(high_db),
        )

    def set_zone_params(
        self,
        zone_idx: int,
        semitones: int,
        key_low: int = 21,
        key_hi: int = 108,
        sustain_enable: bool = True,
    ) -> None:
        if self._shutting_down or not self._dsp:
            return
        eff_tr = int(semitones) + self.global_transpose
        self._lib.stagerig_set_zone_params(
            self._dsp,
            int(zone_idx),
            eff_tr,
            int(key_low),
            int(key_hi),
            0,
            127,
            1 if sustain_enable else 0,
            1,
        )

    def set_bpm(self, bpm: float) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_bpm(self._dsp, float(bpm))

    def set_master_fx(
        self,
        rev_room: float = 0.84,
        rev_damp: float = 0.28,
        rev_level: float = 1.10,
        dly_feedback: float = 0.36,
        dly_level: float = 0.52,
        save: bool = False,
    ) -> dict:
        self.master_fx = {
            "rev_room": max(0.1, min(0.96, float(rev_room))),
            "rev_damp": max(0.0, min(0.95, float(rev_damp))),
            "rev_level": max(0.0, min(2.2, float(rev_level))),
            "dly_feedback": max(0.0, min(0.85, float(dly_feedback))),
            "dly_level": max(0.0, min(1.5, float(dly_level))),
        }
        if not self._shutting_down and self._dsp:
            self._lib.stagerig_set_master_fx(
                self._dsp,
                float(self.master_fx["rev_room"]),
                float(self.master_fx["rev_damp"]),
                float(self.master_fx["rev_level"]),
                float(self.master_fx["dly_feedback"]),
                float(self.master_fx["dly_level"]),
            )
        if save:
            self._save_audio_config()
        return dict(self.master_fx)

    def trigger_panic(self) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_panic(self._dsp)

    def _sync_masters_to_dsp(self) -> None:
        if self._shutting_down or not self._dsp:
            return
        self._lib.stagerig_set_masters_state(
            self._dsp,
            int(self.synth_master_vol),
            1 if self.synth_master_muted else 0,
            int(self.pad_master_vol),
            1 if self.pad_master_muted else 0,
        )

    def set_synth_master_volume(self, value: int) -> None:
        with self._lock:
            self.synth_master_vol = max(0, min(127, int(value)))
            self.master_volume = self.synth_master_vol
        self._sync_masters_to_dsp()

    def set_synth_master_mute(self, muted: bool) -> None:
        with self._lock:
            self.synth_master_muted = bool(muted)
            self.master_muted = self.synth_master_muted
        self._sync_masters_to_dsp()

    def set_pad_master_volume(self, value: int) -> None:
        with self._lock:
            self.pad_master_vol = max(0, min(127, int(value)))
        self._sync_masters_to_dsp()

    def set_pad_master_mute(self, muted: bool) -> None:
        with self._lock:
            self.pad_master_muted = bool(muted)
        self._sync_masters_to_dsp()

    def set_master_volume(self, value: int, target: str = "all") -> None:
        v = max(0, min(127, int(value)))
        with self._lock:
            self.master_volume = v
            if target == "numa":
                self.synth_master_vol = v
            elif target == "pad":
                self.pad_master_vol = v
            else:
                self.synth_master_vol = v
                self.pad_master_vol = v
        self._sync_masters_to_dsp()

    def set_master_mute(self, muted: bool, target: str = "all") -> None:
        m = bool(muted)
        with self._lock:
            self.master_muted = m
            if target == "numa":
                self.synth_master_muted = m
            elif target == "pad":
                self.pad_master_muted = m
            else:
                self.synth_master_muted = m
                self.pad_master_muted = m
        self._sync_masters_to_dsp()

    def get_masters_state(self) -> dict:
        return {
            "synth": {"volume": self.synth_master_vol, "muted": self.synth_master_muted},
            "pad": {"volume": self.pad_master_vol, "muted": self.pad_master_muted},
        }

    # -------------------------------------------------------------------------
    # Continuous 5-Layer Worship Pad Controls
    # -------------------------------------------------------------------------
    def _compute_pitch_rate(self, key_id: int, octave: int) -> float:
        key_info = MUSICAL_KEYS[key_id % 12]
        total_semitones = key_info["semitones"] + (int(octave) * 12)
        return float(2.0 ** (total_semitones / 12.0))

    def _sync_pad_to_dsp(self) -> None:
        if self._shutting_down or not self._dsp:
            return
        rate = self._compute_pitch_rate(self.pad_key_id, self.pad_octave)
        vols = [int(self.pad_volumes[i]) if i < len(self.pad_volumes) else 0 for i in range(4)] + [0]
        mutes = [1 if (i < len(self.pad_mutes) and self.pad_mutes[i]) else 0 for i in range(4)] + [1]
        vols_c = (ctypes.c_int * 5)(*vols)
        mutes_c = (ctypes.c_int * 5)(*mutes)
        self._lib.stagerig_set_pad_layers_ex(
            self._dsp,
            1 if self.pad_playing else 0,
            float(rate),
            vols_c,
            mutes_c,
            5,
        )

    def set_pad_playing(self, play: bool) -> dict:
        with self._lock:
            self.pad_playing = bool(play)
        self._sync_pad_to_dsp()
        self.check_stream_health()
        return self.get_pad_state()

    def toggle_pad_playing(self) -> dict:
        return self.set_pad_playing(not self.pad_playing)

    def set_pad_key(self, key_id: int) -> dict:
        k = max(0, min(11, int(key_id)))
        with self._lock:
            self.pad_key_id = k
        self._sync_pad_to_dsp()
        return self.get_pad_state()

    def set_pad_octave(self, octave: int) -> dict:
        oct_val = max(-1, min(1, int(octave)))
        with self._lock:
            self.pad_octave = oct_val
        self._sync_pad_to_dsp()
        return self.get_pad_state()

    def set_pad_layer_volume(self, layer_idx: int, value: int) -> None:
        idx = int(layer_idx)
        if idx < 0 or idx >= len(self.pad_volumes):
            return
        val = max(0, min(127, int(value)))
        with self._lock:
            self.pad_volumes[idx] = val
        self._sync_pad_to_dsp()

    def set_pad_layer_mute(self, layer_idx: int, muted: bool) -> None:
        idx = int(layer_idx)
        if idx < 0 or idx >= len(self.pad_mutes):
            return
        with self._lock:
            self.pad_mutes[idx] = bool(muted)
        self._sync_pad_to_dsp()

    def get_pad_state(self) -> dict:
        with self._lock:
            key_info = MUSICAL_KEYS[self.pad_key_id]
            return {
                "ready": self.pad_ready,
                "playing": self.pad_playing,
                "key_id": self.pad_key_id,
                "key_label": key_info["label"],
                "key_major": key_info["major"],
                "key_minor": key_info["minor"],
                "semitones": key_info["semitones"] + (self.pad_octave * 12),
                "octave": self.pad_octave,
                "filter_cc": self.pad_filter_cc,
                "volumes": list(self.pad_volumes),
                "mutes": list(self.pad_mutes),
                "master_volume": self.pad_master_vol,
                "master_muted": self.pad_master_muted,
                "keys": MUSICAL_KEYS,
                "layers": PAD_LAYERS_SPEC,
            }

    # -------------------------------------------------------------------------
    # 4-Slot Stereo Drum Pads Controls
    # -------------------------------------------------------------------------
    def get_drum_pads_state(self) -> dict:
        return {
            "pads": copy.deepcopy(self.drum_pads) if "copy" in globals() else list(self.drum_pads),
            "catalog": list(self.drum_catalog),
        }

    def trigger_drum_pad(self, pad_idx: int, velocity: int = 115) -> None:
        if self._shutting_down or not self._dsp:
            return
        idx = max(0, min(3, int(pad_idx)))
        vel = max(1, min(127, int(velocity)))
        self._lib.stagerig_trigger_drum_pad(self._dsp, idx, vel, 0)

    def stop_drum_pad(self, pad_idx: int) -> None:
        if self._shutting_down or not self._dsp:
            return
        idx = max(0, min(3, int(pad_idx)))
        self._lib.stagerig_trigger_drum_pad(self._dsp, idx, 0, 1)

    def set_drum_pad_volume(self, pad_idx: int, volume: int) -> None:
        idx = max(0, min(3, int(pad_idx)))
        v = max(0, min(127, int(volume)))
        with self._lock:
            self.drum_pads[idx]["volume"] = v
            self._save_drum_pads_state()
            pad = self.drum_pads[idx]
        if not self._shutting_down and self._dsp:
            self._lib.stagerig_set_drum_pad_params(
                self._dsp, idx, v, 1 if pad.get("muted") else 0, 1 if pad.get("loop") else 0
            )

    def set_drum_pad_mute(self, pad_idx: int, muted: bool) -> None:
        idx = max(0, min(3, int(pad_idx)))
        m = bool(muted)
        with self._lock:
            self.drum_pads[idx]["muted"] = m
            self._save_drum_pads_state()
            pad = self.drum_pads[idx]
        if not self._shutting_down and self._dsp:
            self._lib.stagerig_set_drum_pad_params(
                self._dsp, idx, int(pad.get("volume", 112)), 1 if m else 0, 1 if pad.get("loop") else 0
            )
            if m:
                self.stop_drum_pad(idx)

    def set_drum_pad_loop(self, pad_idx: int, loop: bool) -> None:
        idx = max(0, min(3, int(pad_idx)))
        lp = bool(loop)
        with self._lock:
            self.drum_pads[idx]["loop"] = lp
            self._save_drum_pads_state()
            pad = self.drum_pads[idx]
        if not self._shutting_down and self._dsp:
            self._lib.stagerig_set_drum_pad_params(
                self._dsp, idx, int(pad.get("volume", 112)), 1 if pad.get("muted") else 0, 1 if lp else 0
            )

    def set_drum_pad_sample(self, pad_idx: int, sample_id: str) -> dict:
        idx = max(0, min(3, int(pad_idx)))
        sid = str(sample_id or "").strip()
        samp = next((s for s in self.drum_catalog if s.get("id") == sid), None)
        if samp:
            with self._lock:
                self.drum_pads[idx]["sample_id"] = sid
                self.drum_pads[idx]["name"] = samp.get("name", sid)
                self.drum_pads[idx]["category"] = samp.get("category", "Drum")
                self.drum_pads[idx]["style"] = samp.get("style", "Worship")
                self._save_drum_pads_state()
            self._load_drum_slot_into_dsp(idx)
        return self.get_drum_pads_state()

    def import_custom_drum_sample(self, pad_idx: int, src_file: str) -> dict:
        idx = max(0, min(3, int(pad_idx)))
        if not os.path.isfile(src_file):
            return {"imported": False, "drum_pads": self.get_drum_pads_state()}
        os.makedirs(CUSTOM_DRUMS_DIR, exist_ok=True)
        fname = os.path.basename(src_file)
        dest = os.path.join(CUSTOM_DRUMS_DIR, fname)
        if os.path.abspath(src_file) != os.path.abspath(dest):
            shutil.copy2(src_file, dest)
        sid = "custom_" + os.path.splitext(fname)[0]
        entry = {
            "id": sid,
            "filename": fname,
            "custom_path": dest,
            "name": os.path.splitext(fname)[0],
            "category": "Custom",
            "style": "User",
        }
        self.drum_catalog = [s for s in self.drum_catalog if s.get("id") != sid] + [entry]
        self.set_drum_pad_sample(idx, sid)
        return {"imported": True, "filename": fname, "drum_pads": self.get_drum_pads_state()}

    # -------------------------------------------------------------------------
    # Telemetry & Lifecycle
    # -------------------------------------------------------------------------
    def get_telemetry(self) -> dict:
        z_peaks = (ctypes.c_float * 4)()
        p_peaks_c = (ctypes.c_float * 5)()
        d_peaks_c = (ctypes.c_float * 4)()
        sm_peak_c = ctypes.c_float()
        pm_peak_c = ctypes.c_float()
        m_peak_c = ctypes.c_float()
        voices = ctypes.c_int()
        if not self._shutting_down and self._dsp:
            self._lib.stagerig_get_telemetry_v2(
                self._dsp,
                z_peaks,
                p_peaks_c,
                d_peaks_c,
                ctypes.byref(sm_peak_c),
                ctypes.byref(pm_peak_c),
                ctypes.byref(m_peak_c),
                ctypes.byref(voices),
            )
        with self._lock:
            n_pad = min(5, len(self.pad_peaks))
            for i in range(n_pad):
                self.pad_peaks[i] = max(float(p_peaks_c[i]), self.pad_peaks[i] * 0.72)
            for d in range(4):
                self.drum_peaks[d] = max(float(d_peaks_c[d]), self.drum_peaks[d] * 0.72)
            self.last_synth_master_peak = max(float(sm_peak_c.value), self.last_synth_master_peak * 0.72)
            self.last_pad_master_peak = max(float(pm_peak_c.value), self.last_pad_master_peak * 0.72)
            self.last_master_peak = max(float(m_peak_c.value), self.last_master_peak * 0.72)
            p_peaks = [round(float(x), 3) for x in self.pad_peaks]
            d_peaks = [round(float(x), 3) for x in self.drum_peaks]
            sm_peak = round(float(self.last_synth_master_peak), 3)
            pm_peak = round(float(self.last_pad_master_peak), 3)
            m_peak = round(float(self.last_master_peak), 3)

        active, aborted, cb_count, xruns, _ = self._get_c_stream_stats()
        self.stream_active = bool(active and not aborted)
        return {
            "zone_vu": [round(float(z_peaks[i]), 3) for i in range(4)],
            "pad_vu": p_peaks,
            "drum_vu": d_peaks,
            "synth_master_vu": sm_peak,
            "pad_master_vu": pm_peak,
            "master_vu": m_peak,
            "active_voices": int(voices.value),
            "sample_rate": SAMPLE_RATE,
            "block_size": self.block_size,
            "latency_ms": self.reported_latency_ms,
            "loaded_soundfonts": len(self._loaded_sfids),
            "stream_active": self.stream_active,
            "stream_recoveries": self.stream_recoveries,
            "xruns": xruns,
            "callback_count": cb_count,
        }

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info=None, status=0) -> None:
        if self._shutting_down or not self._dsp:
            outdata.fill(0.0)
            return
        self._lib.stagerig_render_block(self._dsp, outdata.ctypes.data, int(frames))

    def shutdown(self) -> None:
        self._shutting_down = True
        self.bump_preset_generation()
        self.pad_playing = False
        self.stop_audio_stream()
        with self._preset_lock:
            with self._sf_lock:
                with self._lock:
                    try:
                        if self._dsp:
                            self._lib.stagerig_destroy(self._dsp)
                            self._dsp = None
                    except Exception:
                        pass
