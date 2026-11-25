#!/usr/bin/env python3
"""
P61x Console - Independent Real-Time Stage Piano, Synth, 5-Layer Worship Pad & Drum Pad Workstation
(main.py — v1.3.3 Windows & Linux Standalone)

Powered by PySide6 + QWebEngineView + QWebChannel with an integrated Native C 4-Zone FluidSynth +
5-Band EQ + Stereo Chorus + Cathedral Reverb + BPM Ping-Pong Delay + 5-Layer Continuous Worship Pad +
4-Slot Stereo Drum Pad audio engine.
"""

from __future__ import annotations

import argparse
import collections
import faulthandler
import json
import os
import signal
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from typing import Optional

if sys.platform == "win32":
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-features=WebMidi,WebHid,WebUSB,HardwareMediaKeyHandling",
    )

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from standalone_midi_engine import StandaloneMidiEngine, UI_MAPPINGS_FILE
from standalone_timbre_catalog import CONFIG_DIR

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
_LOCAL_UI = os.path.join(BASE_DIR, "ui", "index.html")
UI_HTML_PATH = _LOCAL_UI if os.path.isfile(_LOCAL_UI) else os.path.join(PARENT_DIR, "ui", "index.html")
VERSION_JSON_PATH = os.path.join(BASE_DIR, "version.json") if os.path.isfile(os.path.join(BASE_DIR, "version.json")) else os.path.join(PARENT_DIR, "version.json")
_NEW_ICON = next(
    (p for p in (
        os.path.join(BASE_DIR, "ui", "p61x-keyboard.png"),
        os.path.join(BASE_DIR, "ui_assets", "p61x-keyboard.png"),
    ) if os.path.isfile(p)),
    os.path.join(BASE_DIR, "ui", "standalone-rig.png"),
)
APP_ICON_PATH = _NEW_ICON if os.path.isfile(_NEW_ICON) else os.path.join(BASE_DIR, "ui_assets", "standalone-rig.png")
STUDIO_OPTIMIZER_SCRIPT = "/home/marconi/otimiza_estudio.sh"
_PARENT_BIN_DIR = os.path.join(PARENT_DIR, "bin")
LOCAL_BIN_DIR = _PARENT_BIN_DIR if os.path.isdir(_PARENT_BIN_DIR) else "/home/marconi/Documentos/ControladorNumaPlayer/bin"

def _load_local_version() -> tuple[str, int]:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "version.json"), os.path.join(os.path.dirname(here), "version.json")):
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return str(data.get("versionName", "1.3.6")), int(data.get("versionCode", 12))
            except Exception:
                pass
    return "1.3.6", 12


APP_VERSION_NAME, APP_VERSION_CODE = _load_local_version()
GITHUB_REPO = "vmarconivieira/MIDIControl"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_VERSION_JSON_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"


def run_studio_optimizer(profile: int) -> bool:
    """
    On Windows, activates Windows High Performance or Balanced power scheme.
    On Linux, executes otimiza_estudio.sh if present.
    """
    if sys.platform == "win32":
        try:
            cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if int(profile) == 1:
                subprocess.run(
                    ["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"],
                    capture_output=True,
                    creationflags=cflags,
                )
            else:
                subprocess.run(
                    ["powercfg", "/setactive", "381b4222-f694-41f0-9685-ff5bb260df2e"],
                    capture_output=True,
                    creationflags=cflags,
                )
            return True
        except Exception:
            return True

    if sys.platform == "darwin":
        return True

    if not os.path.isfile(STUDIO_OPTIMIZER_SCRIPT):
        return False

    choice = "1" if int(profile) == 1 else "2"
    env = os.environ.copy()
    if os.path.isdir(LOCAL_BIN_DIR):
        env["PATH"] = f"{LOCAL_BIN_DIR}:{env.get('PATH', '')}"
        env["SUDO_ASKPASS"] = os.path.join(LOCAL_BIN_DIR, "askpass_gui.sh")

    try:
        res = subprocess.run(
            ["/bin/bash", STUDIO_OPTIMIZER_SCRIPT],
            input=f"{choice}\n",
            text=True,
            capture_output=True,
            env=env,
            timeout=30.0,
        )
        return res.returncode == 0
    except Exception as e:
        print(f"[StudioOptimizer] Erro ao executar perfil {choice}: {e}")
        return False


class StandaloneBackend(QObject):
    """QWebChannel bridge exposing P61x Console v1.3.5 4-Zone Synth, 98-Timbre Catalog, SoundPacks, Pads, Drums & MIDI to the UI."""

    bridgeEvent = Signal(str)

    def __init__(self, midi_engine: StandaloneMidiEngine, main_window: Optional[QMainWindow] = None) -> None:
        super().__init__()
        self.engine = midi_engine
        self.main_window = main_window
        self._event_queue = collections.deque(maxlen=2048)
        self.engine.event_callback = self._on_bridge_event

    def _on_bridge_event(self, payload: dict) -> None:
        try:
            self._event_queue.append(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def flush_pending_events(self) -> None:
        """Must run exclusively on Qt main GUI thread."""
        n = min(128, len(self._event_queue))
        for _ in range(n):
            try:
                msg = self._event_queue.popleft()
            except IndexError:
                break
            try:
                self.bridgeEvent.emit(msg)
            except Exception:
                pass

    @Slot(result=str)
    def getInitialState(self) -> str:
        ui_maps = {}
        if os.path.isfile(UI_MAPPINGS_FILE):
            try:
                with open(UI_MAPPINGS_FILE, "r", encoding="utf-8") as f:
                    ui_maps = json.load(f)
            except Exception:
                ui_maps = {}

        state = {
            "banks": self.engine.get_banks_metadata(),
            "current_bank": self.engine.current_bank_name,
            "current_preset_index": self.engine.current_preset_index,
            "timbre_catalog": self.engine.catalog.get_catalog_for_ui(),
            "favorites": self.engine.catalog.favorites,
            "input_ports": self.engine.list_input_ports(),
            "output_ports": self.engine.list_output_ports(),
            "connected_input": self.engine.connected_input_name,
            "selected_output": self.engine.selected_output_port,
            "numa_status": self.engine.get_engine_status(),
            "audio_config": self.engine.audio.get_audio_config(),
            "pad_state": self.engine.audio.get_pad_state(),
            "drum_pads": self.engine.audio.get_drum_pads_state(),
            "masters_state": self.engine.audio.get_masters_state(),
            "master_state": {
                "volume": self.engine.audio.synth_master_vol,
                "muted": self.engine.audio.synth_master_muted,
                "target": self.engine.audio.master_target,
            },
            "ui_mappings": ui_maps,
            "active_controller_profile": self.engine.active_controller_profile,
            "controller_profiles": self.engine.list_controller_profiles(),
            "ui_theme": self.engine.ui_theme,
        }
        return json.dumps(state, ensure_ascii=False)

    @Slot(str, int)
    def selectBankAndPreset(self, bank_name: str, preset_index: int) -> None:
        self.engine.select_bank_and_preset(bank_name, int(preset_index))

    @Slot(result=str)
    def reloadTimbreCatalog(self) -> str:
        items = self.engine.reload_timbre_catalog()
        return json.dumps(items, ensure_ascii=False)

    @Slot(int, str, result=str)
    def setZoneTimbre(self, zone_idx: int, lib_id: str) -> str:
        res = self.engine.set_zone_timbre(int(zone_idx), str(lib_id))
        return json.dumps(res or {}, ensure_ascii=False)

    @Slot(str, result=str)
    def toggleFavoriteTimbre(self, lib_id: str) -> str:
        favs = self.engine.catalog.toggle_favorite(str(lib_id))
        return json.dumps(favs, ensure_ascii=False)

    @Slot(int, int, int, int, int, int, int, int, bool, result=str)
    def setZoneParams(
        self,
        zone_idx: int,
        transpose: int,
        key_low: int,
        key_hi: int,
        pan: int,
        cutoff: int,
        resonance: int,
        tone: int,
        sustain_enable: bool,
    ) -> str:
        res = self.engine.set_zone_params(
            int(zone_idx),
            int(transpose),
            int(key_low),
            int(key_hi),
            int(pan),
            int(cutoff),
            int(resonance),
            int(tone),
            bool(sustain_enable),
        )
        return json.dumps(res, ensure_ascii=False)

    @Slot(int, float, float, float, float, float, result=str)
    def setZoneEq(
        self,
        zone_idx: int,
        low_db: float,
        low_mid_db: float,
        mid_db: float,
        high_mid_db: float,
        high_db: float,
    ) -> str:
        bands = self.engine.set_zone_eq(
            int(zone_idx),
            float(low_db),
            float(low_mid_db),
            float(mid_db),
            float(high_mid_db),
            float(high_db),
        )
        return json.dumps({"zone_idx": int(zone_idx), "eq": bands}, ensure_ascii=False)

    @Slot(int, int)
    def setZoneVolume(self, zone_idx: int, value: int) -> None:
        self.engine.set_zone_volume(int(zone_idx), int(value))

    @Slot(int, bool)
    def setZoneMute(self, zone_idx: int, muted: bool) -> None:
        self.engine.set_zone_mute(int(zone_idx), bool(muted))

    @Slot(int, bool)
    def setZoneSolo(self, zone_idx: int, soloed: bool) -> None:
        self.engine.set_zone_solo(int(zone_idx), bool(soloed))

    @Slot(int, str, int)
    def setZoneFx(self, zone_idx: int, fx_type: str, value: int) -> None:
        self.engine.set_zone_fx(int(zone_idx), str(fx_type), int(value))

    @Slot(int, int)
    def setZoneChorus(self, zone_idx: int, value: int) -> None:
        self.engine.set_zone_chorus(int(zone_idx), int(value))

    @Slot(int, int, int)
    def setZoneEnvelope(self, zone_idx: int, attack: int, release: int) -> None:
        self.engine.set_zone_envelope(int(zone_idx), int(attack), int(release))

    @Slot(int, result=int)
    def setGlobalTranspose(self, semitones: int) -> int:
        return self.engine.set_global_transpose(int(semitones))

    @Slot(result=int)
    def getGlobalTranspose(self) -> int:
        return self.engine.get_global_transpose()

    @Slot(int, result=int)
    def setBpm(self, bpm: int) -> int:
        return self.engine.set_bpm(float(bpm))

    @Slot(float, float, float, float, float, bool, result=str)
    def setMasterFx(
        self,
        rev_room: float,
        rev_damp: float,
        rev_level: float,
        dly_feedback: float,
        dly_level: float,
        save: bool,
    ) -> str:
        res = self.engine.audio.set_master_fx(
            rev_room=float(rev_room),
            rev_damp=float(rev_damp),
            rev_level=float(rev_level),
            dly_feedback=float(dly_feedback),
            dly_level=float(dly_level),
            save=bool(save),
        )
        return json.dumps(res, ensure_ascii=False)

    @Slot(str, result=str)
    def saveCurrentPreset(self, custom_name: str) -> str:
        saved = self.engine.save_current_preset(custom_name)
        return json.dumps(
            {
                "preset": saved,
                "banks": self.engine.get_banks_metadata(),
                "current_bank": self.engine.current_bank_name,
                "current_preset_index": self.engine.current_preset_index,
            },
            ensure_ascii=False,
        )

    @Slot(str, str, result=str)
    def createNewPreset(self, name: str, bank_name: str) -> str:
        created = self.engine.create_new_preset(name, bank_name or None)
        return json.dumps(
            {
                "preset": created,
                "banks": self.engine.get_banks_metadata(),
                "current_bank": self.engine.current_bank_name,
                "current_preset_index": self.engine.current_preset_index,
            },
            ensure_ascii=False,
        )

    @Slot(int, int)
    def sendNoteOn(self, note: int, velocity: int) -> None:
        self.engine.send_note_on(int(note), int(velocity), channel=1)

    @Slot(int)
    def sendNoteOff(self, note: int) -> None:
        self.engine.send_note_off(int(note), channel=1)

    @Slot(str)
    def sendRawMidi(self, json_bytes: str) -> None:
        try:
            data = json.loads(json_bytes)
            if isinstance(data, list):
                self.engine.send_raw_midi([int(b) for b in data])
        except Exception:
            pass

    @Slot()
    def triggerPanic(self) -> None:
        self.engine.trigger_panic()

    # -------------------------------------------------------------------------
    # Continuous 5-Layer Worship Pad & Dual Master Slots
    # -------------------------------------------------------------------------
    @Slot(bool, result=str)
    def setPadPlaying(self, playing: bool) -> str:
        st = self.engine.audio.set_pad_playing(bool(playing))
        return json.dumps(st, ensure_ascii=False)

    @Slot(result=str)
    def togglePadPlaying(self) -> str:
        st = self.engine.audio.toggle_pad_playing()
        return json.dumps(st, ensure_ascii=False)

    @Slot(int, result=str)
    def setPadKey(self, key_id: int) -> str:
        st = self.engine.audio.set_pad_key(int(key_id))
        return json.dumps(st, ensure_ascii=False)

    @Slot(int, result=str)
    def setPadOctave(self, octave: int) -> str:
        st = self.engine.audio.set_pad_octave(int(octave))
        return json.dumps(st, ensure_ascii=False)

    @Slot(int, int)
    def setPadLayerVolume(self, layer_idx: int, value: int) -> None:
        self.engine.audio.set_pad_layer_volume(int(layer_idx), int(value))

    @Slot(int, bool)
    def setPadLayerMute(self, layer_idx: int, muted: bool) -> None:
        self.engine.audio.set_pad_layer_mute(int(layer_idx), bool(muted))

    @Slot(int)
    def setSynthMasterVolume(self, value: int) -> None:
        self.engine.audio.set_synth_master_volume(int(value))

    @Slot(bool)
    def setSynthMasterMute(self, muted: bool) -> None:
        self.engine.audio.set_synth_master_mute(bool(muted))

    @Slot(int)
    def setPadMasterVolume(self, value: int) -> None:
        self.engine.audio.set_pad_master_volume(int(value))

    @Slot(bool)
    def setPadMasterMute(self, muted: bool) -> None:
        self.engine.audio.set_pad_master_mute(bool(muted))

    @Slot(int, str)
    def setMasterVolume(self, value: int, target: str) -> None:
        self.engine.set_master_volume(int(value), str(target))

    @Slot(bool, str)
    def setMasterMute(self, muted: bool, target: str) -> None:
        self.engine.set_master_mute(bool(muted), str(target))

    # -------------------------------------------------------------------------
    # 4-Slot Stereo Drum Pads & File Import Dialogs
    # -------------------------------------------------------------------------
    @Slot(int, int)
    def triggerDrumPad(self, pad_idx: int, velocity: int) -> None:
        self.engine.audio.trigger_drum_pad(int(pad_idx), int(velocity))

    @Slot(int)
    def stopDrumPad(self, pad_idx: int) -> None:
        self.engine.audio.stop_drum_pad(int(pad_idx))

    @Slot(int, int)
    def setDrumPadVolume(self, pad_idx: int, value: int) -> None:
        self.engine.audio.set_drum_pad_volume(int(pad_idx), int(value))

    @Slot(int, bool)
    def setDrumPadMute(self, pad_idx: int, muted: bool) -> None:
        self.engine.audio.set_drum_pad_mute(int(pad_idx), bool(muted))

    @Slot(int, bool)
    def setDrumPadLoop(self, pad_idx: int, loop: bool) -> None:
        self.engine.audio.set_drum_pad_loop(int(pad_idx), bool(loop))

    @Slot(int, str, result=str)
    def setDrumPadSample(self, pad_idx: int, sample_id: str) -> str:
        st = self.engine.audio.set_drum_pad_sample(int(pad_idx), str(sample_id))
        return json.dumps(st, ensure_ascii=False)

    @Slot(int, result=str)
    def importDrumPadSampleDialog(self, pad_idx: int) -> str:
        fpath, _ = QFileDialog.getOpenFileName(
            self.main_window,
            f"Importar Sample para Drum Pad {int(pad_idx) + 1}",
            os.path.expanduser("~"),
            "Audio Samples (*.wav *.ogg *.flac)",
        )
        if not fpath:
            return json.dumps({"imported": False}, ensure_ascii=False)
        res = self.engine.audio.import_custom_drum_sample(int(pad_idx), fpath)
        return json.dumps(res, ensure_ascii=False)

    @Slot(result=str)
    def importSoundfontDialog(self) -> str:
        fpath, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Importar SoundFont (.sf2)",
            os.path.expanduser("~"),
            "SoundFont 2 (*.sf2 *.SF2)",
        )
        if not fpath:
            return json.dumps({"imported": False}, ensure_ascii=False)
        res = self.engine.import_custom_soundfont(fpath)
        return json.dumps(res, ensure_ascii=False)

    # -------------------------------------------------------------------------
    # Modular Sound Packs (18 Packs, 98 Timbres)
    # -------------------------------------------------------------------------
    @Slot(result=str)
    def getSoundPacksStatus(self) -> str:
        return json.dumps(self.engine.soundpacks.get_status_dict(), ensure_ascii=False)

    @Slot(str)
    def downloadSoundPack(self, pack_id: str) -> None:
        self.engine.soundpacks.download_pack(str(pack_id))

    @Slot(str, result=str)
    def removeSoundPack(self, pack_id: str) -> str:
        st = self.engine.soundpacks.remove_pack(str(pack_id))
        return json.dumps(st, ensure_ascii=False)

    # -------------------------------------------------------------------------
    # MIDI Learn Mappings & Controller Profiles
    # -------------------------------------------------------------------------
    def _sync_canonical_mappings(self, ui_maps: dict) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(UI_MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(ui_maps, f, indent=2, ensure_ascii=False)

        key_translation = {
            "vol_z1": "z0_vol",
            "vol_z2": "z1_vol",
            "vol_z3": "z2_vol",
            "vol_z4": "z3_vol",
            "mute_z1": "z0_mute",
            "mute_z2": "z1_mute",
            "mute_z3": "z2_mute",
            "mute_z4": "z3_mute",
            "solo_z1": "z0_solo",
            "solo_z2": "z1_solo",
            "solo_z3": "z2_solo",
            "solo_z4": "z3_solo",
            "rev_z1": "z0_rev",
            "dly_z1": "z0_dly",
            "rev_z2": "z1_rev",
            "dly_z2": "z1_dly",
            "rev_z3": "z2_rev",
            "dly_z3": "z2_dly",
            "rev_z4": "z3_rev",
            "dly_z4": "z3_dly",
            "btn_panic": "master_panic",
            "vol_pad1": "pad0_vol",
            "vol_pad2": "pad1_vol",
            "vol_pad3": "pad2_vol",
            "vol_pad4": "pad3_vol",
            "vol_pad5": "pad4_vol",
            "mute_pad1": "pad0_mute",
            "mute_pad2": "pad1_mute",
            "mute_pad3": "pad2_mute",
            "mute_pad4": "pad3_mute",
            "mute_pad5": "pad4_mute",
            "pad_toggle": "pad_toggle",
            "vol_master": "master_vol",
            "mute_master": "master_mute",
        }
        canonical = {}
        for ui_key, entry in ui_maps.items():
            if not isinstance(entry, dict):
                continue
            target_key = key_translation.get(ui_key, ui_key)
            if ui_key.startswith("patch_"):
                target_key = f"setlist_{ui_key.split('_')[1]}"
            ch_raw = entry.get("channel", "all")
            ch_num = 0 if ch_raw in ("all", 0, "0") else int(ch_raw)
            canonical[target_key] = {
                "type": str(entry.get("type", "cc")).lower(),
                "channel": ch_num,
                "number": int(entry.get("number", 0)),
                "invert": bool(entry.get("invert", False)),
                "label": str(entry.get("label", "")),
            }
        self.engine.save_mappings(canonical, ui_maps=ui_maps)

    @Slot(str)
    def saveUiMappings(self, json_mappings: str) -> None:
        try:
            ui_maps = json.loads(json_mappings)
            if isinstance(ui_maps, dict):
                self._sync_canonical_mappings(ui_maps)
        except Exception:
            pass

    @Slot(str, str, result=str)
    def saveControllerProfile(self, profile_name: str, json_mappings: str) -> str:
        try:
            ui_maps = json.loads(json_mappings)
            if not isinstance(ui_maps, dict):
                ui_maps = {}
            self._sync_canonical_mappings(ui_maps)
            res = self.engine.save_controller_profile(profile_name, ui_maps)
            return json.dumps(res, ensure_ascii=False)
        except Exception:
            return json.dumps({"active_profile": "", "profiles": []})

    @Slot(str, result=str)
    def loadControllerProfile(self, profile_name: str) -> str:
        res = self.engine.load_controller_profile(profile_name)
        if res.get("ok"):
            self._sync_canonical_mappings(res.get("ui_mappings", {}))
        return json.dumps(res, ensure_ascii=False)

    @Slot(str, result=str)
    def deleteControllerProfile(self, profile_name: str) -> str:
        res = self.engine.delete_controller_profile(profile_name)
        return json.dumps(res, ensure_ascii=False)

    @Slot(result=str)
    def clearAllMappings(self) -> str:
        res = self.engine.clear_all_mappings()
        return json.dumps(res, ensure_ascii=False)

    @Slot(str, result=str)
    def setUiTheme(self, theme_name: str) -> str:
        return self.engine.set_ui_theme(str(theme_name))

    # -------------------------------------------------------------------------
    # MIDI Rescan, BLE MIDI & Audio Route Configuration
    # -------------------------------------------------------------------------
    @Slot(str)
    def selectInputPort(self, port_id: str) -> None:
        self.engine.select_input_port(port_id)

    @Slot(result=str)
    def rescanMidiDevices(self) -> str:
        return json.dumps(self.engine.rescan_midi_devices(), ensure_ascii=False)

    @Slot(bool)
    def startBleMidiScan(self, include_all: bool) -> None:
        ports = [p for p in self.engine.list_input_ports() if p.get("transport") == "ble"]
        if sys.platform == "darwin":
            hint = "No macOS, pareie o dispositivo BLE MIDI no app 'Configuração de Áudio e MIDI' (Janela > Mostrar Estúdio MIDI > Bluetooth) e clique em USB para atualizar."
        else:
            hint = "No Windows, pareie o dispositivo BLE MIDI nas Configurações de Bluetooth do Windows e clique em USB para atualizar."
        msg = f"{len(ports)} dispositivo(s) BLE MIDI pareado(s) no sistema." if ports else hint
        self._on_bridge_event(
            {
                "event": "ble_scan_result",
                "scanning": False,
                "devices": [
                    {"name": p["name"], "address": p["id"], "connected": True, "hasMidiUuid": True} for p in ports
                ],
                "message": msg,
            }
        )

    @Slot()
    def stopBleMidiScan(self) -> None:
        self._on_bridge_event({"event": "ble_scan_result", "scanning": False, "devices": []})

    @Slot(str)
    def connectBleMidiDevice(self, address: str) -> None:
        self.engine.select_input_port(address)

    @Slot(str)
    def disconnectBleMidiDevice(self, address: str) -> None:
        self.engine.select_input_port("virtual-p61x")

    @Slot(result=str)
    def getAudioRouteStatus(self) -> str:
        return json.dumps(self.engine.audio.get_audio_route_status(), ensure_ascii=False)

    @Slot(str, int, result=str)
    def selectAudioConfig(self, output_device: str, block_size: int) -> str:
        cfg = self.engine.audio.set_audio_config(str(output_device), int(block_size))
        self._on_bridge_event({"event": "numa_status", **self.engine.get_engine_status()})
        self._on_bridge_event({"event": "audio_route_status", **self.engine.audio.get_audio_route_status()})
        return json.dumps(cfg, ensure_ascii=False)

    @Slot(result=str)
    def restartAudioEngine(self) -> str:
        st = self.engine.restart_audio_engine()
        self._on_bridge_event({"event": "audio_route_status", **self.engine.audio.get_audio_route_status()})
        return json.dumps(st, ensure_ascii=False)

    @Slot()
    def toggleFullscreen(self) -> None:
        if self.main_window is not None:
            if self.main_window.isFullScreen():
                self.main_window.showNormal()
            else:
                self.main_window.showFullScreen()

    # -------------------------------------------------------------------------
    # App Version & GitHub Auto-Update Checker
    # -------------------------------------------------------------------------
    @Slot(result=str)
    def getAppVersion(self) -> str:
        return json.dumps(
            {
                "versionName": APP_VERSION_NAME,
                "versionCode": APP_VERSION_CODE,
                "repo": GITHUB_REPO,
                "releasesUrl": GITHUB_RELEASES_URL,
            },
            ensure_ascii=False,
        )

    @Slot()
    def checkGithubUpdate(self) -> None:
        def _worker() -> None:
            try:
                req = urllib.request.Request(
                    GITHUB_VERSION_JSON_URL + f"?t={int(__import__('time').time())}",
                    headers={"User-Agent": f"P61xConsole-Windows/{APP_VERSION_NAME}"},
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    remote = json.loads(resp.read().decode("utf-8"))
                r_code = int(remote.get("versionCode", APP_VERSION_CODE))
                r_name = str(remote.get("versionName", APP_VERSION_NAME))
                notes = remote.get("notes", [])
                notes_str = "\n".join(f"• {n}" for n in notes) if isinstance(notes, list) else str(notes)
                rel_url = str(remote.get("releaseUrl", GITHUB_RELEASES_URL))
                if sys.platform == "win32":
                    dl_url = str(remote.get("windowsSetupUrl") or rel_url)
                    dl_size = int(remote.get("windowsSetupSizeBytes", 0) or 0)
                else:
                    dl_url = str(remote.get("apkUrl") or rel_url)
                    dl_size = int(remote.get("apkSizeBytes", 0) or 0)
                if dl_size <= 0 and dl_url.lower().endswith((".exe", ".zip", ".apk")):
                    try:
                        hreq = urllib.request.Request(
                            dl_url,
                            method="HEAD",
                            headers={"User-Agent": f"P61xConsole-Windows/{APP_VERSION_NAME}"},
                        )
                        with urllib.request.urlopen(hreq, timeout=5) as hresp:
                            dl_size = int(hresp.headers.get("Content-Length") or 0)
                    except Exception:
                        pass
                self._on_bridge_event(
                    {
                        "event": "update_status",
                        "ok": True,
                        "installedVersionName": APP_VERSION_NAME,
                        "installedVersionCode": APP_VERSION_CODE,
                        "remoteVersionName": r_name,
                        "remoteVersionCode": r_code,
                        "remoteTag": str(remote.get("tag", f"v{r_name}")),
                        "hasUpdate": r_code > APP_VERSION_CODE,
                        "hasApkAsset": dl_url.lower().endswith((".exe", ".zip", ".apk")),
                        "apkUrl": dl_url,
                        "apkSizeBytes": dl_size,
                        "releaseUrl": rel_url,
                        "repo": GITHUB_REPO,
                        "notes": notes_str,
                    }
                )
            except Exception as e:
                self._on_bridge_event(
                    {
                        "event": "update_status",
                        "ok": False,
                        "installedVersionName": APP_VERSION_NAME,
                        "installedVersionCode": APP_VERSION_CODE,
                        "releaseUrl": GITHUB_RELEASES_URL,
                        "repo": GITHUB_REPO,
                        "error": f"Erro ao consultar GitHub: {e}",
                    }
                )

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str)
    def downloadAndInstallUpdate(self, url: str) -> None:
        clean_url = (url or "").strip() or GITHUB_RELEASES_URL
        if sys.platform != "win32" or not clean_url.lower().endswith(".exe"):
            self.openExternalUrl(clean_url)
            return

        def _dl_worker() -> None:
            import tempfile

            dest = os.path.join(tempfile.gettempdir(), "P61x_Console_Setup_update.exe")
            try:
                self._on_bridge_event(
                    {
                        "event": "update_progress",
                        "status": "downloading",
                        "pct": 0,
                        "message": "Conectando ao GitHub...",
                    }
                )
                req = urllib.request.Request(
                    clean_url,
                    headers={"User-Agent": f"P61xConsole-Windows/{APP_VERSION_NAME}"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    last_pct = -1
                    with open(dest, "wb") as out_f:
                        while True:
                            chunk = resp.read(131072)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            done += len(chunk)
                            pct = int((done * 100) / total) if total > 0 else 50
                            pct = min(99, max(1, pct))
                            if pct != last_pct:
                                last_pct = pct
                                mb_done = done / 1048576.0
                                mb_tot = f" / {total / 1048576.0:.1f} MB" if total > 0 else ""
                                self._on_bridge_event(
                                    {
                                        "event": "update_progress",
                                        "status": "downloading",
                                        "pct": pct,
                                        "message": f"Baixando instalador ({mb_done:.1f} MB{mb_tot})...",
                                    }
                                )
                with open(dest, "rb") as chk_f:
                    if chk_f.read(2) != b"MZ":
                        raise RuntimeError("Arquivo baixado não é um instalador Windows válido (.exe).")
                self._on_bridge_event(
                    {
                        "event": "update_progress",
                        "status": "installed",
                        "pct": 100,
                        "message": "Iniciando instalador P61x Console...",
                    }
                )
                subprocess.Popen([dest], close_fds=True)
                app = QApplication.instance()
                if app is not None:
                    QTimer.singleShot(450, app.quit)
            except Exception as e:
                self._on_bridge_event(
                    {
                        "event": "update_progress",
                        "status": "error",
                        "pct": 0,
                        "message": f"Falha ao baixar atualização: {e}",
                    }
                )
                self.openExternalUrl(GITHUB_RELEASES_URL)

        threading.Thread(target=_dl_worker, daemon=True).start()

    @Slot(str)
    def openExternalUrl(self, url: str) -> None:
        if url:
            try:
                webbrowser.open(str(url))
            except Exception:
                pass

    @Slot(int)
    def runStudioOptimizer(self, profile: int) -> None:
        p = 1 if int(profile) == 1 else 2

        def _worker() -> None:
            ok = run_studio_optimizer(p)
            self._on_bridge_event(
                {
                    "event": "optimizer_status",
                    "profile": p,
                    "success": ok,
                }
            )

        threading.Thread(target=_worker, daemon=True).start()


class StandaloneRigWindow(QMainWindow):
    """Main desktop P61x Console window."""

    def __init__(self, midi_engine: StandaloneMidiEngine, auto_optimize: bool = True) -> None:
        super().__init__()
        self.engine = midi_engine
        self.auto_optimize = auto_optimize
        self._optimizer_restored = False
        self._last_vu_nonzero = False

        self.setWindowTitle(f"P61x Console v{APP_VERSION_NAME} - By: Vinícius")
        if os.path.isfile(APP_ICON_PATH):
            self.setWindowIcon(QIcon(APP_ICON_PATH))
        self.resize(1460, 880)
        self.setMinimumSize(1024, 680)
        self.setStyleSheet("background-color: #0b0d12;")

        self.webview = QWebEngineView(self)
        self.webview.page().setBackgroundColor(QColor("#0b0d12"))
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)

        self.channel = QWebChannel(self.webview.page())
        self.backend = StandaloneBackend(self.engine, self)
        self.channel.registerObject("numaBackend", self.backend)
        self.webview.page().setWebChannel(self.channel)

        self.webview.setUrl(QUrl.fromLocalFile(UI_HTML_PATH))
        self.setCentralWidget(self.webview)

        self.event_flush_timer = QTimer(self)
        self.event_flush_timer.timeout.connect(self.backend.flush_pending_events)
        self.event_flush_timer.start(16)

        self.vu_timer = QTimer(self)
        self.vu_timer.timeout.connect(self._broadcast_vu_telemetry)
        self.vu_timer.start(50)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._broadcast_status)
        self.status_timer.start(1800)

        if self.auto_optimize:
            QTimer.singleShot(450, lambda: self.backend.runStudioOptimizer(1))

    def _broadcast_vu_telemetry(self) -> None:
        tel = self.engine.audio.get_telemetry()
        has_signal = (
            tel["master_vu"] > 0.008
            or any(v > 0.008 for v in tel["zone_vu"])
            or any(v > 0.008 for v in tel["pad_vu"])
            or any(v > 0.008 for v in tel.get("drum_vu", []))
            or tel["active_voices"] > 0
        )
        if has_signal or self._last_vu_nonzero:
            self._last_vu_nonzero = has_signal
            self.backend._on_bridge_event({"event": "vu_telemetry", **tel})

    def _broadcast_status(self) -> None:
        status = self.engine.get_engine_status()
        self.backend._on_bridge_event({"event": "numa_status", **status})

    def restore_everyday_mode(self) -> None:
        if self.auto_optimize and not self._optimizer_restored:
            self._optimizer_restored = True
            run_studio_optimizer(2)

    def closeEvent(self, event) -> None:
        self.engine.shutdown()
        self.restore_everyday_mode()
        super().closeEvent(event)


def run_cli_check() -> int:
    """Runs a quick non-GUI diagnostic check of the Standalone Synth, 98-Timbre Catalog, 5-Layer Pad & 4 Drum Pads."""
    import time

    engine = StandaloneMidiEngine()
    engine.send_note_on(60, 100)
    engine.send_note_on(64, 100)
    engine.send_note_on(67, 100)
    time.sleep(0.25)
    status = engine.get_engine_status()
    tel = engine.audio.get_telemetry()
    sp = engine.soundpacks.get_status_dict()
    engine.send_note_off(60)
    engine.send_note_off(64)
    engine.send_note_off(67)

    print(f"=== P61x Console v{APP_VERSION_NAME} (Build {APP_VERSION_CODE}) :: Diagnostic Check ===")
    print(f"Audio Stream Ativo : {status['running']}")
    print(f"Latência DSP       : {status['pipewire_latency']}")
    print(f"Timbres Catalogados: {status['total_timbres']} (Pacotes: {len(sp['packs'])})")
    print(f"Preset Inicial     : {engine.get_current_preset()['name']} -> Zona 4: {engine.get_current_preset()['libs'][3]}")
    print(f"SoundFonts Ativas  : {status['loaded_soundfonts']}")
    print(f"Vozes Ativas Teste : {tel['active_voices']} (Master VU: {tel['master_vu']})")
    print(f"Pad 5 Camadas Ready: {engine.audio.pad_ready}")
    print(f"Drum Pads Catalog  : {len(engine.audio.drum_catalog)} samples")
    print(f"Entrada MIDI       : {status['input_port']}")
    print(f"Bancos Carregados  : {list(engine.get_banks_metadata().keys())}")
    engine.shutdown()
    return 0


def _cleanup_previous_instances() -> None:
    if sys.platform == "win32":
        return
    import time

    my_pid = os.getpid()
    try:
        res = subprocess.run(
            ["pgrep", "-f", "(NumaStandalonePlayer|numa-standalone-player|p61x-keyboard)/main.py"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        killed = False
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid != my_pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        killed = True
                    except Exception:
                        pass
        if killed:
            time.sleep(0.35)
    except Exception:
        pass


_RUNTIME_LOG_HANDLE = None


def _setup_windows_runtime_stdio() -> str:
    global _RUNTIME_LOG_HANDLE
    log_dir = os.path.join(BASE_DIR, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        test_probe = os.path.join(log_dir, ".write_test")
        with open(test_probe, "w", encoding="utf-8") as tf:
            tf.write("ok")
        os.remove(test_probe)
    except Exception:
        local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        log_dir = os.path.join(local_app, "P61x Console", "logs")
        os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "p61x_runtime.log")
    os.environ["P61X_RUNTIME_LOG"] = log_path
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        _RUNTIME_LOG_HANDLE = log_file
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file
        faulthandler.enable(file=log_file, all_threads=True)
    except Exception:
        pass
    return log_path


def _show_fatal_startup_error(msg: str) -> None:
    try:
        log_dir = os.path.dirname(os.environ.get("P61X_RUNTIME_LOG") or os.path.join(BASE_DIR, "logs", "p61x_runtime.log"))
        os.makedirs(log_dir, exist_ok=True)
        err_path = os.path.join(log_dir, "p61x_startup_error.log")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        err_path = "logs/p61x_startup_error.log"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"Falha ao iniciar o P61x Console v{APP_VERSION_NAME}:\n\n{msg[:900]}\n\nDetalhes em: {err_path}",
                f"P61x Console v{APP_VERSION_NAME} — Erro",
                0x10,
            )
        except Exception:
            pass


def main() -> int:
    _setup_windows_runtime_stdio()
    parser = argparse.ArgumentParser(description=f"P61x Console v{APP_VERSION_NAME} (Standalone 4-Zone Synth + 4-Layer Pad + Drum Pads)")
    parser.add_argument("--check", action="store_true", help="Executa diagnóstico de áudio + timbres + MIDI e sai")
    parser.add_argument("--no-optimize", action="store_true", help="Não altera plano de energia automaticamente")
    args, qt_args = parser.parse_known_args()

    _cleanup_previous_instances()

    if args.check:
        return run_cli_check()

    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"P61xAudio.P61xConsole.{APP_VERSION_NAME}")
        except Exception:
            pass

    try:
        app = QApplication([sys.argv[0]] + qt_args)
        app.setApplicationName(f"P61x Console v{APP_VERSION_NAME}")
        app.setDesktopFileName("p61x-keyboard")
        app.setOrganizationName("ViniciusAudio")
        if os.path.isfile(APP_ICON_PATH):
            app.setWindowIcon(QIcon(APP_ICON_PATH))

        midi_engine = StandaloneMidiEngine()
        window = StandaloneRigWindow(midi_engine, auto_optimize=not args.no_optimize)
        window.show()
        if sys.platform == "win32":
            midi_engine.audio.install_crash_handler(rearm_only=True)

        signal.signal(signal.SIGINT, lambda *_: app.quit())
        signal.signal(signal.SIGTERM, lambda *_: app.quit())
        return app.exec()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        _show_fatal_startup_error(tb)
        return 1


if __name__ == "__main__":
    sys.exit(main())
