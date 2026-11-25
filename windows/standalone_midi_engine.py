#!/usr/bin/env python3
"""
P61x Console (Windows & Linux Standalone) - Real-Time MIDI Router & 4-Zone Synth Controller
(standalone_midi_engine.py — v1.3.4)
"""

from __future__ import annotations

import copy
import ctypes
import json
import os
import re
import shutil
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

try:
    import rtmidi
    HAS_RTMIDI = True
except ImportError:
    rtmidi = None
    HAS_RTMIDI = False


class _NullMidiIn:
    def __init__(self, name: str = "") -> None:
        self._open = False

    def get_ports(self) -> List[str]:
        return []

    def open_port(self, idx: int) -> None:
        raise RuntimeError("MIDI backend indisponível")

    def open_virtual_port(self, name: str) -> None:
        pass

    def close_port(self) -> None:
        self._open = False

    def is_port_open(self) -> bool:
        return self._open

    def ignore_types(self, sysex: bool = False, timing: bool = True, active_sense: bool = True) -> None:
        pass

    def set_callback(self, cb, data=None) -> None:
        pass


class _NullMidiOut:
    def __init__(self, name: str = "") -> None:
        self._open = False

    def get_ports(self) -> List[str]:
        return []

    def open_port(self, idx: int) -> None:
        pass

    def open_virtual_port(self, name: str) -> None:
        pass

    def close_port(self) -> None:
        self._open = False

    def is_port_open(self) -> bool:
        return False

    def send_message(self, msg: List[int]) -> None:
        pass


_WINMM_C_LIB = None


class _CWinMMMidiIn:
    """Thread-safe polled WinMM MIDI Input backed by stagerig_dsp.dll's C ring buffer."""

    def __init__(self, lib, name: str = "") -> None:
        self._lib = lib
        self._open = False
        self._stop_poll = False
        self._callback = None
        self._cb_data = None
        self._poll_thread: Optional[threading.Thread] = None
        self._ignore_timing = True
        self._ignore_active_sense = True

    def get_ports(self) -> List[str]:
        ports: List[str] = []
        try:
            count = int(self._lib.stagerig_winmm_in_count())
            buf = ctypes.create_string_buffer(256)
            for idx in range(max(0, count)):
                rc = int(self._lib.stagerig_winmm_in_name_utf8(idx, buf, 256))
                if rc >= 0:
                    nm = buf.value.decode("utf-8", errors="replace").strip()
                else:
                    nm = ""
                ports.append(nm or f"MIDI In {idx}")
        except Exception:
            pass
        return ports

    def open_port(self, idx: int) -> None:
        self.close_port()
        rc = int(self._lib.stagerig_winmm_in_open(int(idx)))
        if rc != 0:
            raise RuntimeError(f"WinMM C midiInOpen({idx}) falhou: mmresult={rc}")
        self._open = True
        self._stop_poll = False
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="P61x-WinMM-Poll",
            daemon=True,
        )
        self._poll_thread.start()

    def open_virtual_port(self, name: str) -> None:
        pass

    def close_port(self) -> None:
        was_open = self._open
        self._stop_poll = True
        self._open = False
        th = self._poll_thread
        self._poll_thread = None
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=0.35)
        if was_open:
            try:
                self._lib.stagerig_winmm_in_close()
            except Exception:
                pass

    def is_port_open(self) -> bool:
        if not self._open:
            return False
        try:
            return bool(self._lib.stagerig_winmm_in_is_open())
        except Exception:
            return self._open

    def ignore_types(self, sysex: bool = False, timing: bool = True, active_sense: bool = True) -> None:
        self._ignore_timing = bool(timing)
        self._ignore_active_sense = bool(active_sense)

    def set_callback(self, cb, data=None) -> None:
        self._callback = cb
        self._cb_data = data

    def _poll_loop(self) -> None:
        buf = (ctypes.c_uint32 * 64)()
        while self._open and not self._stop_poll:
            try:
                n = int(self._lib.stagerig_winmm_in_poll(buf, 64))
            except Exception:
                n = 0
            if n > 0:
                cb = self._callback
                cb_data = self._cb_data
                for i in range(n):
                    raw = int(buf[i])
                    status = raw & 0xFF
                    if self._ignore_timing and status == 0xF8:
                        continue
                    if self._ignore_active_sense and status == 0xFE:
                        continue
                    d1 = (raw >> 8) & 0xFF
                    d2 = (raw >> 16) & 0xFF
                    cmd = status & 0xF0
                    if cmd in (0xC0, 0xD0) or status in (0xF1, 0xF3):
                        msg = [status, d1]
                    elif status in (0xF0, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xFA, 0xFB, 0xFC, 0xFE, 0xFF):
                        msg = [status]
                    else:
                        msg = [status, d1, d2]
                    if cb is not None:
                        try:
                            cb((msg, 0.0), cb_data)
                        except Exception:
                            pass
            else:
                time.sleep(0.002)


if sys.platform == "win32":
    class _MIDIINCAPSW(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("wMid", ctypes.c_uint16),
            ("wPid", ctypes.c_uint16),
            ("vDriverVersion", ctypes.c_uint32),
            ("szPname", ctypes.c_wchar * 32),
            ("dwSupport", ctypes.c_uint32),
        ]

    class _MIDIOUTCAPSW(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("wMid", ctypes.c_uint16),
            ("wPid", ctypes.c_uint16),
            ("vDriverVersion", ctypes.c_uint32),
            ("szPname", ctypes.c_wchar * 32),
            ("wTechnology", ctypes.c_uint16),
            ("wVoices", ctypes.c_uint16),
            ("wNotes", ctypes.c_uint16),
            ("wChannelMask", ctypes.c_uint16),
            ("dwSupport", ctypes.c_uint32),
        ]

    _WINMM = ctypes.windll.winmm
    _MIDIINPROC = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )
    _WINMM.midiInGetNumDevs.restype = ctypes.c_uint
    _WINMM.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(_MIDIINCAPSW), ctypes.c_uint]
    _WINMM.midiInGetDevCapsW.restype = ctypes.c_uint
    _WINMM.midiInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
    ]
    _WINMM.midiInOpen.restype = ctypes.c_uint
    _WINMM.midiInStart.argtypes = [ctypes.c_void_p]
    _WINMM.midiInStop.argtypes = [ctypes.c_void_p]
    _WINMM.midiInReset.argtypes = [ctypes.c_void_p]
    _WINMM.midiInClose.argtypes = [ctypes.c_void_p]
    _WINMM.midiOutGetNumDevs.restype = ctypes.c_uint
    _WINMM.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(_MIDIOUTCAPSW), ctypes.c_uint]
    _WINMM.midiOutGetDevCapsW.restype = ctypes.c_uint
    _WINMM.midiOutOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint32,
    ]
    _WINMM.midiOutOpen.restype = ctypes.c_uint
    _WINMM.midiOutShortMsg.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _WINMM.midiOutClose.argtypes = [ctypes.c_void_p]

    class _WinMMMidiIn:
        def __init__(self, name: str = "") -> None:
            self._handle: Optional[ctypes.c_void_p] = None
            self._callback = None
            self._cb_data = None
            self._ignore_timing = True
            self._ignore_active_sense = True
            self._closing = False
            self._lock = threading.RLock()

            def _proc(hmi, wmsg, dw_inst, dw_p1, dw_p2):
                if self._closing or wmsg != 0x3C3 or not self._callback:  # MIM_DATA
                    return
                status = dw_p1 & 0xFF
                if status == 0xF8 and self._ignore_timing:
                    return
                if status == 0xFE and self._ignore_active_sense:
                    return
                d1 = (dw_p1 >> 8) & 0xFF
                d2 = (dw_p1 >> 16) & 0xFF
                hi = status & 0xF0
                if hi in (0xC0, 0xD0) or status in (0xF1, 0xF3):
                    msg = [status, d1]
                elif status >= 0xF4:
                    msg = [status]
                else:
                    msg = [status, d1, d2]
                try:
                    cb = self._callback
                    if cb and not self._closing:
                        cb((msg, 0.0), self._cb_data)
                except Exception:
                    pass

            self._cb_ref = _MIDIINPROC(_proc)

        def get_ports(self) -> List[str]:
            n = int(_WINMM.midiInGetNumDevs())
            ports: List[str] = []
            for idx in range(n):
                caps = _MIDIINCAPSW()
                rc = _WINMM.midiInGetDevCapsW(idx, ctypes.byref(caps), ctypes.sizeof(caps))
                if rc == 0:
                    ports.append(caps.szPname or f"MIDI In {idx}")
                else:
                    ports.append(f"MIDI In {idx}")
            return ports

        def open_port(self, idx: int) -> None:
            with self._lock:
                self.close_port()
                self._closing = False
                handle = ctypes.c_void_p()
                rc = _WINMM.midiInOpen(
                    ctypes.byref(handle),
                    int(idx),
                    ctypes.cast(self._cb_ref, ctypes.c_void_p),
                    0,
                    0x30000,  # CALLBACK_FUNCTION
                )
                if rc != 0 or not handle.value:
                    raise RuntimeError(f"WinMM midiInOpen({idx}) erro {rc}")
                self._handle = handle
                _WINMM.midiInStart(handle)

        def open_virtual_port(self, name: str) -> None:
            pass

        def close_port(self) -> None:
            with self._lock:
                self._closing = True
                h = self._handle
                self._handle = None
            if h is not None:
                try:
                    _WINMM.midiInStop(h)
                except Exception:
                    pass
                try:
                    _WINMM.midiInReset(h)
                except Exception:
                    pass
                try:
                    _WINMM.midiInClose(h)
                except Exception:
                    pass

        def is_port_open(self) -> bool:
            with self._lock:
                return self._handle is not None and not self._closing

        def ignore_types(self, sysex: bool = False, timing: bool = True, active_sense: bool = True) -> None:
            self._ignore_timing = bool(timing)
            self._ignore_active_sense = bool(active_sense)

        def set_callback(self, cb, data=None) -> None:
            self._callback = cb
            self._cb_data = data

    class _WinMMMidiOut(_NullMidiOut):
        def __init__(self, name: str = "") -> None:
            super().__init__(name)
            self._handle: Optional[ctypes.c_void_p] = None

        def get_ports(self) -> List[str]:
            n = int(_WINMM.midiOutGetNumDevs())
            ports: List[str] = []
            for idx in range(n):
                caps = _MIDIOUTCAPSW()
                if _WINMM.midiOutGetDevCapsW(idx, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                    ports.append(caps.szPname or f"MIDI Out {idx}")
                else:
                    ports.append(f"MIDI Out {idx}")
            return ports

        def open_port(self, idx: int) -> None:
            self.close_port()
            handle = ctypes.c_void_p()
            if _WINMM.midiOutOpen(ctypes.byref(handle), int(idx), 0, 0, 0) == 0 and handle.value:
                self._handle = handle
                self._open = True

        def close_port(self) -> None:
            h = self._handle
            self._handle = None
            self._open = False
            if h is not None:
                try:
                    _WINMM.midiOutClose(h)
                except Exception:
                    pass

        def send_message(self, msg: List[int]) -> None:
            if not self._handle or not msg:
                return
            b0 = msg[0] & 0xFF
            b1 = (msg[1] & 0xFF) if len(msg) > 1 else 0
            b2 = (msg[2] & 0xFF) if len(msg) > 2 else 0
            packed = b0 | (b1 << 8) | (b2 << 16)
            _WINMM.midiOutShortMsg(self._handle, packed)


def _create_midi_in(name: str = "", audio_lib=None):
    global _WINMM_C_LIB
    if audio_lib is not None:
        _WINMM_C_LIB = audio_lib
    if sys.platform == "win32" and os.environ.get("P61X_USE_RTMIDI") != "1":
        c_lib = audio_lib or _WINMM_C_LIB
        if c_lib is not None and hasattr(c_lib, "stagerig_winmm_in_poll"):
            return _CWinMMMidiIn(c_lib, name=name)
        return _WinMMMidiIn(name=name)
    if HAS_RTMIDI and rtmidi is not None:
        return rtmidi.MidiIn(name=name)
    if sys.platform == "win32":
        c_lib = audio_lib or _WINMM_C_LIB
        if c_lib is not None and hasattr(c_lib, "stagerig_winmm_in_poll"):
            return _CWinMMMidiIn(c_lib, name=name)
        return _WinMMMidiIn(name=name)
    return _NullMidiIn(name=name)


def _create_midi_out(name: str):
    if sys.platform == "win32" and os.environ.get("P61X_USE_RTMIDI") != "1":
        return _WinMMMidiOut(name=name)
    if HAS_RTMIDI and rtmidi is not None:
        return rtmidi.MidiOut(name=name)
    if sys.platform == "win32":
        return _WinMMMidiOut(name=name)
    return _NullMidiOut(name=name)

from standalone_audio_engine import StandaloneAudioEngine
from standalone_timbre_catalog import (
    CONFIG_DIR,
    LIVE_RIG_BANK_NAME,
    LOCAL_SOUNDFONTS_DIR,
    SoundPackManager,
    TimbreCatalog,
    load_all_standalone_banks,
    save_standalone_banks,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAPPINGS_FILE = os.path.join(CONFIG_DIR, "midi_mappings.json")
UI_MAPPINGS_FILE = os.path.join(CONFIG_DIR, "ui_mappings.json")
CONTROLLER_PROFILES_DIR = os.path.join(CONFIG_DIR, "controller_profiles")
CONTROLLER_STATE_FILE = os.path.join(CONFIG_DIR, "controller_state.json")

VIRTUAL_CLIENT_NAME = "P61x Console"
VIRTUAL_IN_PORT_NAME = "P61x Console In"
VIRTUAL_OUT_PORT_NAME = "P61x Console Thru Out"

HW_INPUT_KEYWORDS = [
    "amw",
    "p61x",
    "origin",
    "midiplus",
    "keystation",
    "oxygen",
    "arturia",
    "launchkey",
    "komplete",
    "roland",
    "yamaha",
    "korg",
    "casio",
    "nord",
    "studiologic",
    "numa",
    "m-vave",
    "widi",
    "usb",
]


class StandaloneMidiEngine:
    """
    Core Standalone P61x Console Engine (v1.3.3):
    Manages TimbreCatalog (98 timbres), SoundPackManager (18 packs), StandaloneAudioEngine,
    Setlist Banks, 4-Zone State, 5-Layer Worship Pad, 4-Slot Drum Pads, Controller Profiles,
    and Windows/ALSA MIDI I/O.
    """

    def __init__(self, event_callback: Optional[Callable[[dict], None]] = None) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(CONTROLLER_PROFILES_DIR, exist_ok=True)

        self.event_callback = event_callback
        self._lock = threading.RLock()
        self._running = True

        self.active_controller_profile: str = ""
        self.ui_theme: str = "modern"
        self._load_controller_state()

        # 1. Initialize Timbre Catalog (98 timbres), Banks & Modular SoundPack Manager
        self.catalog = TimbreCatalog()
        self.banks: Dict[str, List[dict]] = load_all_standalone_banks(self.catalog)
        self.current_bank_name: str = (
            LIVE_RIG_BANK_NAME if LIVE_RIG_BANK_NAME in self.banks else next(iter(self.banks))
        )
        self.current_preset_index: int = 0
        self.soundpacks = SoundPackManager(
            self.catalog,
            emit_callback=self._emit_event,
            on_pack_installed=self._on_soundpack_installed,
        )

        # 2. Initialize Unified Standalone Audio Engine
        self.audio = StandaloneAudioEngine(self.catalog)

        # 3. Load persistent MIDI mappings
        self.mappings: Dict[str, dict] = self._load_mappings()
        self.ui_mappings: Dict[str, dict] = self._load_ui_mappings()

        # 4. Initialize current 4-Zone state & apply active preset to DSP
        self.zone_state = {
            "libs": [
                "1 - A_PIANO/1 - Model D 1983",
                "2 - E_PIANO/1 - EP-Mark I",
                "Fantasia Bells.sf2/FantasiaBells - TIMB",
                "Nord Red Ambient Pad.sf2/Red Ambient Pad",
            ],
            "zone_names": ["Acoustic Piano", "Electric Piano", "Keys / Bells", "Nord Ambient Pad"],
            "zone_models": ["Model D 1983", "EP-Mark I Vintage", "Fantasia Bells", "Nord Red Ambient Pad"],
            "volumes": [105, 70, 45, 95],
            "mutes": [False, False, False, False],
            "solos": [False, False, False, False],
            "rev": [65, 70, 80, 90],
            "dly": [40, 35, 75, 50],
            "chorus": [0, 0, 0, 0],
            "attacks": [0, 0, 0, 0],
            "releases": [64, 64, 64, 64],
            "transposes": [0, 0, 0, 0],
            "key_lows": [21, 21, 21, 21],
            "key_his": [108, 108, 108, 108],
            "pans": [64, 64, 64, 64],
            "cutoffs": [127, 127, 127, 127],
            "resonances": [0, 0, 0, 0],
            "tones": [64, 64, 64, 64],
            "eqs": [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)],
            "sustain_enables": [True, True, True, True],
        }
        initial_preset = self.get_current_preset()
        self._apply_preset_dict_to_zone_state(initial_preset)
        self.audio.apply_preset(initial_preset)
        self.audio.prewarm_presets_background(self.banks.get(self.current_bank_name, []))

        # 5. Setup Windows WinMM / Linux ALSA MIDI Input & Output
        self.virtual_out = _create_midi_out(name=VIRTUAL_CLIENT_NAME)
        if sys.platform != "win32":
            try:
                self.virtual_out.open_virtual_port(VIRTUAL_OUT_PORT_NAME)
            except Exception:
                pass
        self.selected_output_port: str = "internal:Standalone C DSP Engine"

        self.hw_in = _create_midi_in(
            name=VIRTUAL_CLIENT_NAME,
            audio_lib=getattr(self.audio, "_lib", None),
        )
        self.hw_in.ignore_types(sysex=False, timing=True, active_sense=True)
        self.hw_in.set_callback(self._on_midi_in_callback, data="hw")
        self.selected_input_port: str = "auto"
        self.connected_input_name: str = "Nenhum"

        self.virtual_in = _create_midi_in(
            name=VIRTUAL_CLIENT_NAME,
            audio_lib=getattr(self.audio, "_lib", None),
        )
        self.virtual_in.ignore_types(sysex=False, timing=True, active_sense=True)
        if sys.platform != "win32":
            try:
                self.virtual_in.open_virtual_port(VIRTUAL_IN_PORT_NAME)
                self.virtual_in.set_callback(self._on_midi_in_callback, data="virtual")
            except Exception:
                pass

        self.auto_connect_input()

        # 6. Background watchdog for USB MIDI hot-plug and audio stream health
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _on_soundpack_installed(self, pack_id: str) -> None:
        """Re-applies current preset when a pack finishes downloading so locked zones activate live."""
        try:
            preset = copy.deepcopy(self.get_current_preset())
            seq = self.audio.bump_preset_generation()
            self.audio.apply_preset(preset, target_seq=seq)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Configuration, Controller Profiles, Theme & Mappings Persistence
    # -------------------------------------------------------------------------
    def _load_controller_state(self) -> None:
        if os.path.isfile(CONTROLLER_STATE_FILE):
            try:
                with open(CONTROLLER_STATE_FILE, "r", encoding="utf-8") as f:
                    st = json.load(f)
                if isinstance(st, dict):
                    self.active_controller_profile = str(st.get("active_profile", ""))
                    theme = str(st.get("theme", "modern"))
                    if theme in ("modern", "retro", "studio", "midnight"):
                        self.ui_theme = theme
            except Exception:
                pass

    def _save_controller_state(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONTROLLER_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "active_profile": self.active_controller_profile,
                        "theme": self.ui_theme,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            pass

    def set_ui_theme(self, theme: str) -> str:
        if theme in ("modern", "retro", "studio", "midnight"):
            self.ui_theme = theme
            self._save_controller_state()
        return self.ui_theme

    def _load_mappings(self) -> Dict[str, dict]:
        if os.path.isfile(MAPPINGS_FILE):
            try:
                with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {}

    def _load_ui_mappings(self) -> Dict[str, dict]:
        if os.path.isfile(UI_MAPPINGS_FILE):
            try:
                with open(UI_MAPPINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {}

    def _save_mappings_dict(self, data: Dict[str, dict]) -> bool:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def save_mappings(self, new_mappings: Dict[str, dict], ui_maps: Optional[Dict[str, dict]] = None) -> bool:
        with self._lock:
            self.mappings = new_mappings
            if ui_maps is not None:
                self.ui_mappings = dict(ui_maps)
                try:
                    os.makedirs(CONFIG_DIR, exist_ok=True)
                    with open(UI_MAPPINGS_FILE, "w", encoding="utf-8") as f:
                        json.dump(self.ui_mappings, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
            return self._save_mappings_dict(self.mappings)

    def _profile_slug(self, name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_")
        return slug or "controller"

    def list_controller_profiles(self) -> List[dict]:
        os.makedirs(CONTROLLER_PROFILES_DIR, exist_ok=True)
        profiles: List[dict] = []
        for fname in sorted(os.listdir(CONTROLLER_PROFILES_DIR)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(CONTROLLER_PROFILES_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ui_maps = data.get("ui_mappings", {})
                profiles.append(
                    {
                        "name": str(data.get("name", os.path.splitext(fname)[0])),
                        "slug": os.path.splitext(fname)[0],
                        "count": len(ui_maps) if isinstance(ui_maps, dict) else 0,
                        "updated_at": data.get("updated_at", ""),
                    }
                )
            except Exception:
                pass
        return profiles

    def save_controller_profile(self, profile_name: str, ui_mappings: dict) -> dict:
        clean_name = (profile_name or "").strip() or "Meu Controlador"
        slug = self._profile_slug(clean_name)
        os.makedirs(CONTROLLER_PROFILES_DIR, exist_ok=True)
        fpath = os.path.join(CONTROLLER_PROFILES_DIR, f"{slug}.json")
        payload = {
            "name": clean_name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ui_mappings": ui_mappings if isinstance(ui_mappings, dict) else {},
        }
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        with self._lock:
            self.active_controller_profile = clean_name
            self.ui_mappings = dict(payload["ui_mappings"])
            self._save_controller_state()

        return {
            "ok": True,
            "active_profile": self.active_controller_profile,
            "profiles": self.list_controller_profiles(),
        }

    def load_controller_profile(self, profile_name: str) -> dict:
        os.makedirs(CONTROLLER_PROFILES_DIR, exist_ok=True)
        target_data = None
        for fname in os.listdir(CONTROLLER_PROFILES_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(CONTROLLER_PROFILES_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("name") == profile_name or os.path.splitext(fname)[0] == profile_name:
                    target_data = d
                    break
            except Exception:
                pass
        if not target_data:
            return {"ok": False, "ui_mappings": {}, "active_profile": self.active_controller_profile}

        ui_maps = target_data.get("ui_mappings", {})
        if not isinstance(ui_maps, dict):
            ui_maps = {}
        with open(UI_MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(ui_maps, f, indent=2, ensure_ascii=False)

        with self._lock:
            self.active_controller_profile = str(target_data.get("name", profile_name))
            self.ui_mappings = dict(ui_maps)
            self._save_controller_state()

        return {
            "ok": True,
            "active_profile": self.active_controller_profile,
            "ui_mappings": ui_maps,
            "profiles": self.list_controller_profiles(),
        }

    def delete_controller_profile(self, profile_name: str) -> dict:
        os.makedirs(CONTROLLER_PROFILES_DIR, exist_ok=True)
        for fname in list(os.listdir(CONTROLLER_PROFILES_DIR)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(CONTROLLER_PROFILES_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("name") == profile_name or os.path.splitext(fname)[0] == profile_name:
                    os.remove(fpath)
                    break
            except Exception:
                pass
        if self.active_controller_profile == profile_name:
            self.active_controller_profile = ""
            self._save_controller_state()
        return {
            "ok": True,
            "active_profile": self.active_controller_profile,
            "profiles": self.list_controller_profiles(),
        }

    def clear_all_mappings(self) -> dict:
        with self._lock:
            self.mappings = {}
            self.ui_mappings = {}
            self._save_mappings_dict({})
            with open(UI_MAPPINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
            self.active_controller_profile = ""
            self._save_controller_state()
        return {"ok": True, "active_profile": "", "ui_mappings": {}, "profiles": self.list_controller_profiles()}

    # -------------------------------------------------------------------------
    # MIDI Port Discovery, Hotplug & Rescan
    # -------------------------------------------------------------------------
    def list_input_ports(self) -> List[dict]:
        ports: List[dict] = []
        try:
            with self._lock:
                raw_ports = self.hw_in.get_ports()
            for idx, name in enumerate(raw_ports):
                low = name.lower()
                if VIRTUAL_CLIENT_NAME.lower() in low or "numa standalone" in low or "numa live rig" in low:
                    continue
                if "midi through" in low:
                    continue
                is_hw = any(k in low for k in HW_INPUT_KEYWORDS)
                is_ble = any(k in low for k in ("ble", "bluetooth", "widi", "m-vave"))
                ports.append(
                    {
                        "index": idx,
                        "id": name,
                        "name": name,
                        "is_hardware": is_hw,
                        "connected": True,
                        "transport": "ble" if is_ble else "usb",
                    }
                )
        except Exception:
            pass
        return ports

    def list_output_ports(self) -> List[dict]:
        return [
            {
                "index": -1,
                "id": "internal:Standalone C DSP Engine",
                "name": f"Interno: Standalone 4-Zone C FluidSynth + Reverb + Delay + Pad ({self.audio.reported_latency_ms}ms)",
                "is_virtual": True,
            }
        ]

    def auto_connect_input(self) -> str:
        ports = self.list_input_ports()
        if not ports:
            self.connected_input_name = "Virtual / Teclado 61 Teclas"
            return self.connected_input_name

        best_port = ports[0]
        best_score = -1
        for p in ports:
            low = p["name"].lower()
            score = 0
            if "p61x" in low or "amw" in low:
                score = 100
            elif "origin" in low:
                score = 90
            elif any(k in low for k in HW_INPUT_KEYWORDS):
                score = 70
            else:
                score = 40
            if score > best_score:
                best_score = score
                best_port = p

        return self.select_input_port(best_port["id"])

    def select_input_port(self, port_id: str) -> str:
        with self._lock:
            try:
                if self.hw_in.is_port_open():
                    self.hw_in.close_port()
            except Exception:
                pass

            if not port_id or port_id in ("none", "virtual-p61x"):
                self.selected_input_port = port_id or "virtual-p61x"
                self.connected_input_name = "Virtual / Teclado 61 Teclas"
                self._emit_port_status(reason="selected")
                return self.connected_input_name

            if port_id == "auto":
                self.selected_input_port = "auto"
                ports = self.list_input_ports()
                if not ports:
                    self.connected_input_name = "Virtual / Teclado 61 Teclas"
                    self._emit_port_status(reason="selected")
                    return self.connected_input_name
                port_id = ports[0]["id"]

            raw_ports = self.hw_in.get_ports()
            target_idx = -1
            for idx, name in enumerate(raw_ports):
                if name == port_id or port_id in name:
                    target_idx = idx
                    break

            if target_idx >= 0:
                try:
                    self.hw_in.open_port(target_idx)
                    self.connected_input_name = raw_ports[target_idx]
                    self._emit_port_status(reason="connected")
                    return self.connected_input_name
                except Exception:
                    pass

            self.connected_input_name = "Virtual / Teclado 61 Teclas"
            self._emit_port_status(reason="disconnected")
            return self.connected_input_name

    def _emit_port_status(self, reason: str = "status") -> None:
        ports = self.list_input_ports()
        self._emit_event(
            {
                "event": "port_status",
                "reason": reason,
                "ports": ports,
                "input_port": self.connected_input_name,
                "selected_port_id": self.selected_input_port,
                "connected_count": len(ports),
                "output_port": self.selected_output_port,
            }
        )

    def rescan_midi_devices(self) -> dict:
        ports = self.list_input_ports()
        if ports and (not self.hw_in.is_port_open() or self.connected_input_name.startswith("Virtual")):
            self.auto_connect_input()
            ports = self.list_input_ports()
        elif not ports:
            self.connected_input_name = "Virtual / Teclado 61 Teclas"
        return {
            "ok": True,
            "ports": ports,
            "active_port": self.connected_input_name if ports else "",
            "selected_port_id": self.selected_input_port,
            "connected_count": len(ports),
        }

    # -------------------------------------------------------------------------
    # Engine Status & Telemetry
    # -------------------------------------------------------------------------
    def get_engine_status(self) -> dict:
        tel = self.audio.get_telemetry()
        return {
            "running": tel["stream_active"],
            "standalone": True,
            "pipewire_latency": f"{tel['block_size']}/{tel['sample_rate']} ({tel['latency_ms']}ms)",
            "latency_ms": tel["latency_ms"],
            "active_voices": tel["active_voices"],
            "loaded_soundfonts": tel["loaded_soundfonts"],
            "total_timbres": len(self.catalog.timbres_list),
            "input_port": self.connected_input_name,
            "output_port": self.selected_output_port,
        }

    def restart_audio_engine(self) -> dict:
        self.audio.restart_audio_stream()
        seq = self.audio.bump_preset_generation()
        self.audio.apply_preset(self.get_current_preset(), target_seq=seq)
        st = self.get_engine_status()
        self._emit_event({"event": "numa_status", **st})
        return st

    # -------------------------------------------------------------------------
    # Setlist, Banks & 4-Zone Mixer / Timbre Control
    # -------------------------------------------------------------------------
    def get_banks_metadata(self) -> Dict[str, List[dict]]:
        return self.banks

    def get_current_preset(self) -> dict:
        plist = self.banks.get(self.current_bank_name, [])
        if not plist:
            plist = next(iter(self.banks.values()))
        idx = max(0, min(len(plist) - 1, self.current_preset_index))
        return plist[idx]

    def _apply_preset_dict_to_zone_state(self, preset: dict) -> None:
        self.zone_state["libs"] = list(
            preset.get(
                "libs",
                [
                    "1 - A_PIANO/1 - Model D 1983",
                    "2 - E_PIANO/1 - EP-Mark I",
                    "Fantasia Bells.sf2/FantasiaBells - TIMB",
                    "Nord Red Ambient Pad.sf2/Red Ambient Pad",
                ],
            )[:4]
        )
        self.zone_state["zone_names"] = list(
            preset.get("zone_names", ["Zone 1", "Zone 2", "Zone 3", "Zone 4"])[:4]
        )
        self.zone_state["zone_models"] = list(
            preset.get("zone_models", ["Piano", "EP", "Keys", "Pad"])[:4]
        )
        self.zone_state["volumes"] = list(preset.get("volumes", [100, 80, 50, 80])[:4])
        self.zone_state["mutes"] = list(preset.get("mutes", [False, False, False, False])[:4])
        self.zone_state["solos"] = [False, False, False, False]
        self.zone_state["rev"] = list(preset.get("rev", [60, 60, 60, 80])[:4])
        self.zone_state["dly"] = list(preset.get("dly", [35, 35, 35, 45])[:4])
        self.zone_state["chorus"] = list(preset.get("chorus", [0, 0, 0, 0])[:4])
        self.zone_state["attacks"] = list(preset.get("attacks", [0, 0, 0, 0])[:4])
        self.zone_state["releases"] = list(preset.get("releases", [64, 64, 64, 64])[:4])
        self.zone_state["transposes"] = list(preset.get("transposes", [0, 0, 0, 0])[:4])
        self.zone_state["key_lows"] = list(preset.get("key_lows", [21, 21, 21, 21])[:4])
        self.zone_state["key_his"] = list(preset.get("key_his", [108, 108, 108, 108])[:4])
        self.zone_state["pans"] = list(preset.get("pans", [64, 64, 64, 64])[:4])
        self.zone_state["cutoffs"] = list(preset.get("cutoffs", [127, 127, 127, 127])[:4])
        self.zone_state["resonances"] = list(preset.get("resonances", [0, 0, 0, 0])[:4])
        self.zone_state["tones"] = list(preset.get("tones", [64, 64, 64, 64])[:4])
        self.zone_state["eqs"] = [list(e[:5]) for e in preset.get("eqs", [[0.0] * 5 for _ in range(4)])[:4]]
        self.zone_state["sustain_enables"] = list(preset.get("sustain_enables", [True, True, True, True])[:4])

    def select_bank_and_preset(self, bank_name: str, preset_index: int) -> dict:
        with self._lock:
            bank_changed = False
            if bank_name in self.banks and bank_name != self.current_bank_name:
                self.current_bank_name = bank_name
                bank_changed = True
            plist = self.banks.get(self.current_bank_name, [])
            self.current_preset_index = max(0, min(len(plist) - 1, int(preset_index)))
            preset = plist[self.current_preset_index]
            self._apply_preset_dict_to_zone_state(preset)

        seq = self.audio.bump_preset_generation()
        threading.Thread(
            target=self.audio.apply_preset,
            args=(copy.deepcopy(preset), seq),
            daemon=True,
        ).start()
        if bank_changed:
            self.audio.prewarm_presets_background(plist)
        return preset

    def set_zone_timbre(self, zone_idx: int, lib_id: str) -> Optional[dict]:
        z = max(0, min(3, int(zone_idx)))
        info = self.audio.set_zone_timbre(z, lib_id)
        if not info:
            return None
        with self._lock:
            self.zone_state["libs"][z] = info["lib_id"]
            self.zone_state["zone_names"][z] = info.get("zone_title", info["category_name"])
            self.zone_state["zone_models"][z] = info["model_name"]
            preset = self.get_current_preset()
            if "libs" in preset and z < len(preset["libs"]):
                preset["libs"][z] = info["lib_id"]
            if "zone_names" in preset and z < len(preset["zone_names"]):
                preset["zone_names"][z] = info.get("zone_title", info["category_name"])
            if "zone_models" in preset and z < len(preset["zone_models"]):
                preset["zone_models"][z] = info["model_name"]
            active_models = [
                m for m, mu in zip(self.zone_state["zone_models"], self.zone_state["mutes"]) if not mu
            ]
            if active_models:
                preset["tag"] = " + ".join(active_models[:3])
        return {
            "zone_idx": z,
            "lib_id": info["lib_id"],
            "zone_title": info.get("zone_title", info["category_name"]),
            "model_name": info["model_name"],
            "tag": preset.get("tag", ""),
        }

    def set_zone_params(
        self,
        zone_idx: int,
        semitones: int,
        key_low: int,
        key_hi: int,
        pan: int = 64,
        cutoff: int = 127,
        resonance: int = 0,
        tone: int = 64,
        sustain_enable: bool = True,
    ) -> dict:
        z = max(0, min(3, int(zone_idx)))
        semi = max(-24, min(24, int(semitones)))
        kl = max(0, min(127, int(key_low)))
        kh = max(kl, min(127, int(key_hi)))
        pan_v = max(0, min(127, int(pan)))
        cut_v = max(0, min(127, int(cutoff)))
        res_v = max(0, min(127, int(resonance)))
        tone_v = max(0, min(127, int(tone)))
        sus = bool(sustain_enable)

        with self._lock:
            self.zone_state["transposes"][z] = semi
            self.zone_state["key_lows"][z] = kl
            self.zone_state["key_his"][z] = kh
            self.zone_state["pans"][z] = pan_v
            self.zone_state["cutoffs"][z] = cut_v
            self.zone_state["resonances"][z] = res_v
            self.zone_state["tones"][z] = tone_v
            self.zone_state["sustain_enables"][z] = sus

            preset = self.get_current_preset()
            for field, default_val in (
                ("transposes", 0),
                ("key_lows", 21),
                ("key_his", 108),
                ("pans", 64),
                ("cutoffs", 127),
                ("resonances", 0),
                ("tones", 64),
                ("sustain_enables", True),
            ):
                if field not in preset or len(preset[field]) < 4:
                    preset[field] = [default_val] * 4
            preset["transposes"][z] = semi
            preset["key_lows"][z] = kl
            preset["key_his"][z] = kh
            preset["pans"][z] = pan_v
            preset["cutoffs"][z] = cut_v
            preset["resonances"][z] = res_v
            preset["tones"][z] = tone_v
            preset["sustain_enables"][z] = sus

        self.audio.set_zone_params(z, semi, kl, kh, sus)
        self.audio.set_zone_pan(z, pan_v)
        self.audio.set_zone_filter(z, cut_v, res_v, tone_v)
        return {
            "zone_idx": z,
            "transpose": semi,
            "key_low": kl,
            "key_hi": kh,
            "pan": pan_v,
            "cutoff": cut_v,
            "resonance": res_v,
            "tone": tone_v,
            "sustain_enable": sus,
        }

    def set_global_transpose(self, semitones: int) -> int:
        gt = max(-12, min(12, int(semitones)))
        with self._lock:
            self.audio.global_transpose = gt
            self.audio._save_audio_config()
            for z in range(4):
                self.audio.set_zone_params(
                    z,
                    self.zone_state["transposes"][z],
                    self.zone_state["key_lows"][z],
                    self.zone_state["key_his"][z],
                    self.zone_state["sustain_enables"][z],
                )
        return gt

    def get_global_transpose(self) -> int:
        return int(self.audio.global_transpose)

    def set_zone_eq(
        self,
        zone_idx: int,
        low_db: float,
        low_mid_db: float,
        mid_db: float,
        high_mid_db: float,
        high_db: float,
    ) -> List[float]:
        z = max(0, min(3, int(zone_idx)))
        bands = [
            max(-12.0, min(12.0, round(float(v), 1)))
            for v in (low_db, low_mid_db, mid_db, high_mid_db, high_db)
        ]
        with self._lock:
            self.zone_state["eqs"][z] = bands
            preset = self.get_current_preset()
            if "eqs" not in preset or len(preset["eqs"]) < 4:
                preset["eqs"] = [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)]
            preset["eqs"][z] = list(bands)
        self.audio.set_zone_eq(z, bands[0], bands[1], bands[2], bands[3], bands[4])
        return bands

    def set_bpm(self, bpm: float) -> int:
        bpm_i = max(30, min(260, int(round(float(bpm)))))
        with self._lock:
            preset = self.get_current_preset()
            preset["bpm"] = bpm_i
        self.audio.set_bpm(float(bpm_i))
        return bpm_i

    def set_zone_volume(self, zone_idx: int, value: int) -> None:
        z = max(0, min(3, int(zone_idx)))
        val = max(0, min(127, int(value)))
        with self._lock:
            self.zone_state["volumes"][z] = val
            preset = self.get_current_preset()
            if "volumes" in preset and z < len(preset["volumes"]):
                preset["volumes"][z] = val
        self.audio.set_zone_volume(z, val)

    def set_zone_mute(self, zone_idx: int, muted: bool) -> None:
        z = max(0, min(3, int(zone_idx)))
        m = bool(muted)
        with self._lock:
            self.zone_state["mutes"][z] = m
            preset = self.get_current_preset()
            if "mutes" in preset and z < len(preset["mutes"]):
                preset["mutes"][z] = m
        self.audio.set_zone_mute(z, m)

    def set_zone_solo(self, zone_idx: int, soloed: bool) -> None:
        z = max(0, min(3, int(zone_idx)))
        s = bool(soloed)
        with self._lock:
            self.zone_state["solos"][z] = s
        self.audio.set_zone_solo(z, s)

    def set_zone_fx(self, zone_idx: int, fx_type: str, value: int) -> None:
        z = max(0, min(3, int(zone_idx)))
        val = max(0, min(127, int(value)))
        with self._lock:
            preset = self.get_current_preset()
            if fx_type == "rev":
                self.zone_state["rev"][z] = val
                if "rev" in preset and z < len(preset["rev"]):
                    preset["rev"][z] = val
            elif fx_type == "dly":
                self.zone_state["dly"][z] = val
                if "dly" in preset and z < len(preset["dly"]):
                    preset["dly"][z] = val
            elif fx_type == "chorus":
                self.zone_state["chorus"][z] = val
                if "chorus" not in preset or len(preset["chorus"]) < 4:
                    preset["chorus"] = [0, 0, 0, 0]
                preset["chorus"][z] = val
        self.audio.set_zone_fx(z, fx_type, val)

    def set_zone_chorus(self, zone_idx: int, value: int) -> None:
        self.set_zone_fx(zone_idx, "chorus", value)

    def set_zone_envelope(self, zone_idx: int, attack: int, release: int) -> None:
        z = max(0, min(3, int(zone_idx)))
        atk = max(0, min(127, int(attack)))
        rel = max(0, min(127, int(release)))
        with self._lock:
            self.zone_state["attacks"][z] = atk
            self.zone_state["releases"][z] = rel
            preset = self.get_current_preset()
            if "attacks" not in preset or len(preset["attacks"]) < 4:
                preset["attacks"] = [0, 0, 0, 0]
            if "releases" not in preset or len(preset["releases"]) < 4:
                preset["releases"] = [64, 64, 64, 64]
            preset["attacks"][z] = atk
            preset["releases"][z] = rel
        self.audio.set_zone_envelope(z, atk, rel)

    def import_custom_soundfont(self, src_path: str) -> dict:
        if not os.path.isfile(src_path):
            return {"imported": False}
        os.makedirs(LOCAL_SOUNDFONTS_DIR, exist_ok=True)
        fname = os.path.basename(src_path)
        dest = os.path.join(LOCAL_SOUNDFONTS_DIR, fname)
        if os.path.abspath(src_path) != os.path.abspath(dest):
            shutil.copy2(src_path, dest)
        cat = self.catalog.reload()
        return {"imported": True, "filename": fname, "catalog": cat}

    def save_current_preset(self, custom_name: Optional[str] = None) -> dict:
        with self._lock:
            preset = self.get_current_preset()
            if custom_name and custom_name.strip():
                preset["name"] = custom_name.strip()
            for k in (
                "libs",
                "zone_names",
                "zone_models",
                "volumes",
                "mutes",
                "rev",
                "dly",
                "chorus",
                "attacks",
                "releases",
                "transposes",
                "key_lows",
                "key_his",
                "pans",
                "cutoffs",
                "resonances",
                "tones",
                "sustain_enables",
            ):
                preset[k] = list(self.zone_state[k])
            preset["eqs"] = [list(e) for e in self.zone_state["eqs"]]
            active_models = [
                m for m, mu in zip(self.zone_state["zone_models"], self.zone_state["mutes"]) if not mu
            ]
            if active_models:
                preset["tag"] = " + ".join(active_models[:3])
            save_standalone_banks(self.banks)
            return copy.deepcopy(preset)

    def create_new_preset(self, name: str, bank_name: Optional[str] = None) -> dict:
        with self._lock:
            target_bank = bank_name if (bank_name and bank_name in self.banks) else self.current_bank_name
            plist = self.banks.setdefault(target_bank, [])
            new_idx = len(plist)
            base = copy.deepcopy(self.get_current_preset())
            base["id"] = new_idx
            base["pc"] = min(127, new_idx)
            base["code"] = f"{new_idx + 1:02d}"
            base["bank_name"] = target_bank
            base["name"] = name.strip() or f"Custom Patch {new_idx + 1:02d}"
            for k in (
                "libs",
                "zone_names",
                "zone_models",
                "volumes",
                "mutes",
                "rev",
                "dly",
                "chorus",
                "attacks",
                "releases",
                "transposes",
                "key_lows",
                "key_his",
                "pans",
                "cutoffs",
                "resonances",
                "tones",
                "sustain_enables",
            ):
                base[k] = list(self.zone_state[k])
            base["eqs"] = [list(e) for e in self.zone_state["eqs"]]
            plist.append(base)
            self.current_bank_name = target_bank
            self.current_preset_index = new_idx
            save_standalone_banks(self.banks)
            return copy.deepcopy(base)

    # -------------------------------------------------------------------------
    # Direct Note / Performance Triggering & Master Controls
    # -------------------------------------------------------------------------
    def send_note_on(self, note: int, velocity: int = 100, channel: int = 1) -> None:
        self.audio.note_on(int(note), int(velocity))

    def send_note_off(self, note: int, channel: int = 1) -> None:
        self.audio.note_off(int(note))

    def send_raw_midi(self, message: List[int]) -> None:
        if not message:
            return
        status = message[0]
        cmd = status & 0xF0
        d1 = message[1] if len(message) > 1 else 0
        d2 = message[2] if len(message) > 2 else 0
        if cmd == 0x90:
            if d2 > 0:
                self.audio.note_on(d1, d2)
            else:
                self.audio.note_off(d1)
        elif cmd == 0x80:
            self.audio.note_off(d1)
        elif cmd == 0xB0 and d1 in (1, 11, 64, 66, 67, 74):
            self.audio.send_performance_cc(d1, d2)
        elif cmd == 0xE0:
            bend = (d2 << 7) | d1
            self.audio.pitch_bend(bend)
        try:
            self.virtual_out.send_message(message)
        except Exception:
            pass

    def reload_timbre_catalog(self) -> List[dict]:
        return self.catalog.reload()

    def trigger_panic(self) -> None:
        self.audio.check_stream_health()
        self.audio.trigger_panic()

    def set_master_volume(self, value: int, target: str = "all") -> None:
        self.audio.set_master_volume(int(value), str(target))

    def set_master_mute(self, muted: bool, target: str = "all") -> None:
        self.audio.set_master_mute(bool(muted), str(target))

    # -------------------------------------------------------------------------
    # Hardware MIDI Input Callback (< 0.1ms Direct to C DSP Core)
    # -------------------------------------------------------------------------
    def _find_mapped_drum_pad(self, msg_type: str, number: int, channel: int) -> int:
        with self._lock:
            for ctrl_id, entry in self.ui_mappings.items():
                if not ctrl_id.startswith("drum_pad_") or not isinstance(entry, dict):
                    continue
                if str(entry.get("type", "")).lower() == msg_type and int(entry.get("number", -1)) == number:
                    ch_cfg = entry.get("channel", "all")
                    if ch_cfg in (0, "0", "all", channel, str(channel)):
                        try:
                            return int(ctrl_id.replace("drum_pad_", ""))
                        except Exception:
                            pass
        if channel == 10 and msg_type == "note":
            default_ch10_map = {36: 0, 40: 0, 37: 1, 38: 1, 41: 1, 39: 2, 42: 2, 43: 3, 46: 3, 49: 3}
            return default_ch10_map.get(number, -1)
        return -1

    def _is_mapped_trigger_note(self, note: int, channel: int) -> bool:
        if channel == 10:
            return True
        with self._lock:
            for entry in self.mappings.values():
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("type", "")).lower() == "note" and int(entry.get("number", -1)) == note:
                    ch_cfg = entry.get("channel", 0)
                    if ch_cfg in (0, "0", "all", channel, str(channel)):
                        return True
        return False

    def _on_midi_in_callback(self, event: Tuple[List[int], float], data: str = "hw") -> None:
        message, _ = event
        if not message:
            return

        status = message[0]

        if status == 0xF0:
            if len(message) >= 6 and message[1] == 0x7F and message[3] == 0x06:
                mmc_cmd = message[4]
                cc_num = 113 + (mmc_cmd % 12)
                self._emit_event(
                    {
                        "event": "midi_in",
                        "source": data,
                        "raw": [0xB0, cc_num, 127],
                        "type": "cc",
                        "channel": 1,
                        "number": cc_num,
                        "value": 127,
                    }
                )
            return

        cmd = status & 0xF0
        channel = (status & 0x0F) + 1
        d1 = message[1] if len(message) > 1 else 0
        d2 = message[2] if len(message) > 2 else 0

        dispatched_drum = -1
        if cmd == 0x90 and d2 > 0:
            d_idx = self._find_mapped_drum_pad("note", d1, channel)
            if 0 <= d_idx <= 3:
                self.audio.trigger_drum_pad(d_idx, d2)
                dispatched_drum = d_idx

        if channel != 10:
            if cmd == 0x90:
                if dispatched_drum < 0 and not self._is_mapped_trigger_note(d1, channel):
                    if d2 > 0:
                        self.audio.note_on(d1, d2)
                    else:
                        self.audio.note_off(d1)
            elif cmd == 0x80:
                if not self._is_mapped_trigger_note(d1, channel):
                    self.audio.note_off(d1)
            elif cmd == 0xE0:
                bend = (d2 << 7) | d1
                self.audio.pitch_bend(bend)
            elif cmd == 0xB0 and d1 in (1, 11, 64, 66, 67):
                self.audio.send_performance_cc(d1, d2)
            elif cmd == 0xB0 and d1 == 121:
                self.audio.send_performance_cc(11, 127)
                self.audio.send_performance_cc(64, 0)
                self.audio.send_performance_cc(1, 0)

        msg_type = "other"
        if cmd == 0xB0:
            msg_type = "cc"
        elif cmd == 0xC0:
            msg_type = "pc"
        elif cmd == 0x90 and d2 > 0:
            msg_type = "note"
        elif cmd == 0x80 or (cmd == 0x90 and d2 == 0):
            msg_type = "note_off"
        elif cmd == 0xE0:
            msg_type = "pitchbend"

        ev_payload = {
            "event": "midi_in",
            "source": data,
            "raw": message,
            "type": msg_type,
            "channel": channel,
            "number": d1,
            "value": d2,
        }
        if dispatched_drum >= 0:
            ev_payload["dispatched_drum_pad"] = dispatched_drum
        self._emit_event(ev_payload)

    def _emit_event(self, payload: dict) -> None:
        if self.event_callback is not None:
            try:
                self.event_callback(payload)
            except Exception:
                pass

    def _watchdog_loop(self) -> None:
        while self._running:
            time.sleep(1.5)
            try:
                self.audio.check_stream_health()
                hw_ports = self.list_input_ports()
                active_names = [p["name"] for p in hw_ports]
                port_closed = False
                try:
                    port_closed = len(hw_ports) > 0 and not self.hw_in.is_port_open()
                except Exception:
                    port_closed = True
                if self.selected_input_port != "virtual-p61x" and (
                    port_closed or self.connected_input_name not in active_names
                ):
                    if hw_ports:
                        time.sleep(0.4)
                        if not self._running:
                            break
                        if self.list_input_ports():
                            self.auto_connect_input()
                    elif not self.connected_input_name.startswith("Virtual"):
                        self.connected_input_name = "Virtual / Teclado 61 Teclas"
                        self._emit_port_status(reason="disconnected")
            except Exception:
                pass

    def shutdown(self) -> None:
        self._running = False
        try:
            self.hw_in.close_port()
            self.virtual_in.close_port()
            self.virtual_out.close_port()
        except Exception:
            pass
        try:
            self.audio.shutdown()
        except Exception:
            pass
