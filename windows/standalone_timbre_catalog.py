#!/usr/bin/env python3
"""
P61x Console (Windows & Linux Standalone) - Timbre Catalog, Preset Banks & Modular SoundPack Manager
(standalone_timbre_catalog.py — v1.3.3)

Features:
1. Full 98-Timbre Catalog (51 Numa/Nord/SynthBass + 47 Audio Evolution SoundFont timbres) from mobile_catalog.json
2. Automatic scanning of local/custom .sf2 and .numares files (soundbank/, cache/sf2_decoded/, soundfonts/, Libraries/)
3. On-demand Modular SoundPack Manager (18 packs in soundpacks.json: GitHub Release .zip packs + Google Drive direct .sf2 packs)
4. Automatic migration of Worship Immersion (Preset #0, Zona 4) to Nord Red Ambient Pad
5. Favorites persistence (config/favorites.json) and user preset overrides (config/standalone_presets.json)
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import threading
import urllib.request
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

if os.access(BASE_DIR, os.W_OK) and not BASE_DIR.startswith("/opt/"):
    CONFIG_DIR = os.path.join(BASE_DIR, "config")
    CACHE_SF2_DIR = os.path.join(BASE_DIR, "cache", "sf2_decoded")
else:
    if sys.platform == "win32":
        CONFIG_DIR = os.path.expanduser("~/AppData/Roaming/P61xConsole")
        CACHE_SF2_DIR = os.path.expanduser("~/AppData/Local/P61xConsole/sf2_decoded")
    elif sys.platform == "darwin":
        CONFIG_DIR = os.path.expanduser("~/Library/Application Support/P61xConsole")
        CACHE_SF2_DIR = os.path.expanduser("~/Library/Caches/P61xConsole/sf2_decoded")
    else:
        CONFIG_DIR = os.path.expanduser("~/.config/P61xConsole")
        CACHE_SF2_DIR = os.path.expanduser("~/.cache/P61xConsole/sf2_decoded")

SOUNDBANK_DIR = os.path.join(BASE_DIR, "soundbank")
LOCAL_SOUNDFONTS_DIR = os.path.join(BASE_DIR, "soundfonts")
_LOCAL_MC = os.path.join(BASE_DIR, "mobile_catalog.json")
MOBILE_CATALOG_FILE = _LOCAL_MC if os.path.isfile(_LOCAL_MC) else os.path.join(PARENT_DIR, "android", "mobile_catalog.json")
_LOCAL_SP = os.path.join(BASE_DIR, "soundpacks.json")
SOUNDPACKS_MANIFEST_FILE = _LOCAL_SP if os.path.isfile(_LOCAL_SP) else os.path.join(PARENT_DIR, "soundpacks.json")
STANDALONE_PRESETS_FILE = os.path.join(CONFIG_DIR, "standalone_presets.json")
FAVORITES_FILE = os.path.join(CONFIG_DIR, "favorites.json")
MIGRATION_STATE_FILE = os.path.join(CONFIG_DIR, "migration_state.json")

_POSSIBLE_NUMA_LIBS = [
    os.path.join(BASE_DIR, "Libraries"),
    os.path.join(PARENT_DIR, "Libraries"),
    os.path.expanduser("~/.config/Studiologic/Numa Player/Libraries"),
    os.path.expanduser("~/AppData/Roaming/Studiologic/Numa Player/Libraries"),
    os.path.expanduser("~/Library/Application Support/Studiologic/Numa Player/Libraries"),
    "/Library/Application Support/Studiologic/Numa Player/Libraries",
    r"C:\ProgramData\Studiologic\Numa Player\Libraries",
]
NUMA_LIBRARIES_ROOT = next(
    (p for p in _POSSIBLE_NUMA_LIBS if os.path.isdir(p)),
    _POSSIBLE_NUMA_LIBS[0],
)

LIVE_RIG_BANK_NAME = "0 - Live Rig"

CATEGORY_LABELS: Dict[str, str] = {
    "1 - A_PIANO": "Acoustic Pianos",
    "2 - E_PIANO": "Electric Pianos",
    "3 - KEYS_MALLETS": "Keys & Mallets",
    "4 - STRINGS_PADS": "Strings & Pads",
    "5 - ORGANS": "Tonewheel & Pipe Organs",
    "6 - SYNTH_BASS": "Synth Bass & Sub",
    "SF2": "Nord, Steinway & Custom SF2",
}


def parse_sf2_phdr_from_bytes(tail_bytes: bytes) -> List[Tuple[int, int, str]]:
    """Extracts (bank, program, preset_name) tuples from an SF2 phdr chunk."""
    idx = tail_bytes.find(b"phdr")
    if idx < 0:
        return [(0, 0, "Default")]
    try:
        size = struct.unpack("<I", tail_bytes[idx + 4 : idx + 8])[0]
        data = tail_bytes[idx + 8 : idx + 8 + size]
        presets: List[Tuple[int, int, str]] = []
        for off in range(0, len(data) - 38, 38):
            name, preset, bank = struct.unpack("<20sHH", data[off : off + 24])
            name_s = name.split(b"\x00")[0].decode("latin1", errors="replace").strip()
            if name_s and name_s != "EOP":
                presets.append((int(bank), int(preset), name_s))
        return presets if presets else [(0, 0, "Default")]
    except Exception:
        return [(0, 0, "Default")]


def parse_sf2_file_presets(sf2_path: str, is_numares_xor: bool = False) -> List[Tuple[int, int, str]]:
    """Reads the last 512 KB of an .sf2 or .numares file to inspect presets fast."""
    if not os.path.isfile(sf2_path):
        return [(0, 0, "Default")]
    try:
        fsize = os.path.getsize(sf2_path)
        read_len = min(fsize, 524288)
        with open(sf2_path, "rb") as f:
            f.seek(fsize - read_len)
            tail = f.read(read_len)
        if is_numares_xor:
            tail = (np.frombuffer(tail, dtype=np.uint8) ^ 0x5A).tobytes()
        return parse_sf2_phdr_from_bytes(tail)
    except Exception:
        return [(0, 0, "Default")]


def ensure_decoded_numares_sf2(numares_path: str, out_filename: Optional[str] = None) -> Optional[str]:
    """
    Decodes a Numa Player .numares file (XOR 0x5A obfuscated SF2) into cache/sf2_decoded/
    if not already cached, returning the absolute path to the standard .sf2 file.
    """
    if not os.path.isfile(numares_path):
        return None
    os.makedirs(CACHE_SF2_DIR, exist_ok=True)
    if not out_filename:
        out_filename = os.path.splitext(os.path.basename(numares_path))[0] + ".sf2"
    out_sf2 = os.path.join(CACHE_SF2_DIR, out_filename)

    src_size = os.path.getsize(numares_path)
    if os.path.isfile(out_sf2) and os.path.getsize(out_sf2) == src_size:
        return out_sf2

    try:
        with open(numares_path, "rb") as f:
            head = f.read(4)
        if head == b"RIFF":
            return numares_path
        arr = np.fromfile(numares_path, dtype=np.uint8)
        arr ^= 0x5A
        tmp_out = out_sf2 + ".tmp"
        arr.tofile(tmp_out)
        os.replace(tmp_out, out_sf2)
        return out_sf2
    except Exception as e:
        print(f"[TimbreCatalog] Erro ao decodificar {numares_path}: {e}")
        return None


class TimbreCatalog:
    """
    Central catalog of all 98+ Numa, Nord, Audio Evolution & Custom SoundFont Timbres.
    """

    def __init__(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(CACHE_SF2_DIR, exist_ok=True)
        os.makedirs(SOUNDBANK_DIR, exist_ok=True)
        os.makedirs(LOCAL_SOUNDFONTS_DIR, exist_ok=True)
        self.timbres_by_id: Dict[str, dict] = {}
        self.timbres_list: List[dict] = []
        self.aliases: Dict[str, str] = {}
        self.catalog_banks: Dict[str, List[dict]] = {}
        self.favorites: List[str] = self._load_favorites()
        self._build_catalog()

    def _load_favorites(self) -> List[str]:
        if os.path.isfile(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return [str(x) for x in data]
            except Exception:
                pass
        return []

    def toggle_favorite(self, lib_id: str) -> List[str]:
        lid = str(lib_id or "").strip()
        if not lid:
            return self.favorites
        if lid in self.favorites:
            self.favorites.remove(lid)
        else:
            self.favorites.append(lid)
        try:
            with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.favorites, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return list(self.favorites)

    def _build_catalog(self) -> None:
        self.timbres_by_id.clear()
        self.timbres_list.clear()
        self.aliases.clear()

        # 1. Load primary 98-timbre catalog from mobile_catalog.json
        if os.path.isfile(MOBILE_CATALOG_FILE):
            try:
                with open(MOBILE_CATALOG_FILE, "r", encoding="utf-8") as f:
                    mcat = json.load(f)
                self.aliases = dict(mcat.get("aliases", {}))
                self.catalog_banks = copy.deepcopy(mcat.get("banks", {}))
                for item in mcat.get("timbre_catalog", []):
                    entry = dict(item)
                    lid = entry["lib_id"]
                    self.timbres_by_id[lid] = entry
                    self.timbres_list.append(entry)
            except Exception as e:
                print(f"[TimbreCatalog] Erro ao ler mobile_catalog.json: {e}")

        # 2. Scan custom .sf2 files in soundfonts/ and user SoundFont folders
        extra_sf2_dirs = [
            LOCAL_SOUNDFONTS_DIR,
            os.path.join(NUMA_LIBRARIES_ROOT, "SF2"),
            os.path.expanduser("~/Músicas/Soundfonts"),
            os.path.expanduser("~/Music/Soundfonts"),
            os.path.expanduser("~/Documentos/Soundfonts"),
            os.path.expanduser("~/Documents/Soundfonts"),
        ]
        known_files = {
            os.path.basename(t.get("asset_file", "")) for t in self.timbres_list if t.get("asset_file")
        }
        for sdir in extra_sf2_dirs:
            if not os.path.isdir(sdir):
                continue
            for sf2_path in sorted(glob.glob(os.path.join(sdir, "*.sf2"))):
                fname = os.path.basename(sf2_path)
                if fname in known_files:
                    continue
                known_files.add(fname)
                presets = parse_sf2_file_presets(sf2_path, is_numares_xor=False)
                is_bass = "bass" in fname.lower()
                for bank, prog, p_name in presets:
                    lib_id = f"{fname}/{p_name}"
                    if lib_id in self.timbres_by_id:
                        continue
                    stem_clean = os.path.splitext(fname)[0]
                    cat_key = "6 - SYNTH_BASS" if (is_bass or "bass" in p_name.lower()) else "SF2"
                    entry = {
                        "lib_id": lib_id,
                        "category_key": cat_key,
                        "category_name": CATEGORY_LABELS.get(cat_key, "Custom SF2"),
                        "zone_title": "Synth Bass" if cat_key == "6 - SYNTH_BASS" else stem_clean,
                        "model_name": p_name if p_name.lower() not in stem_clean.lower() else stem_clean,
                        "internal_preset": p_name,
                        "asset_file": f"soundfonts/{fname}",
                        "source_path": sf2_path,
                        "image_path": "../soundimages/INSTR_SYNTH_1.png",
                        "is_numares": False,
                        "bank": bank,
                        "prog": prog,
                    }
                    self.timbres_by_id[lib_id] = entry
                    self.timbres_list.append(entry)

    def reload(self) -> List[dict]:
        self._build_catalog()
        return self.get_catalog_for_ui()

    def _locate_asset_on_disk(self, entry: dict) -> Optional[str]:
        """Finds or decodes the .sf2 file on disk for a catalog entry."""
        if entry.get("source_path") and os.path.isfile(entry["source_path"]):
            if entry.get("is_numares"):
                return ensure_decoded_numares_sf2(entry["source_path"])
            return entry["source_path"]

        asset_rel = entry.get("asset_file", "")
        fname = os.path.basename(asset_rel) if asset_rel else ""
        if not fname:
            return None

        # 1. Check cache/sf2_decoded/<fname> (direct .sf2 downloads from Audio Evolution or decoded files)
        cand_cache = os.path.join(CACHE_SF2_DIR, fname)
        if os.path.isfile(cand_cache) and os.path.getsize(cand_cache) > 1024:
            return cand_cache

        # 2. Check soundbank/<fname>
        cand_sb = os.path.join(SOUNDBANK_DIR, fname)
        if os.path.isfile(cand_sb) and os.path.getsize(cand_sb) > 1024:
            if entry.get("is_numares") or fname.endswith(".numares"):
                return ensure_decoded_numares_sf2(cand_sb)
            return cand_sb

        # 3. Check soundfonts/<fname>
        cand_sf = os.path.join(LOCAL_SOUNDFONTS_DIR, fname)
        if os.path.isfile(cand_sf) and os.path.getsize(cand_sf) > 1024:
            return cand_sf

        # 4. Check Numa Player Libraries on system if installed
        cat_key = entry.get("category_key", "")
        lib_id = entry.get("lib_id", "")
        if "/" in lib_id and os.path.isdir(NUMA_LIBRARIES_ROOT):
            sound_stem = lib_id.split("/", 1)[1]
            cand_numa = os.path.join(NUMA_LIBRARIES_ROOT, f"{cat_key}.numalib", "sounds", f"{sound_stem}.numares")
            if os.path.isfile(cand_numa):
                return ensure_decoded_numares_sf2(cand_numa)
            cand_numa_sf2 = os.path.join(NUMA_LIBRARIES_ROOT, "SF2", fname)
            if os.path.isfile(cand_numa_sf2):
                return cand_numa_sf2

        return None

    def is_timbre_installed(self, entry: dict) -> bool:
        return self._locate_asset_on_disk(entry) is not None

    def resolve_timbre(self, lib_id: str) -> Optional[dict]:
        """
        Resolves lib_id to a ready-to-load SF2 file path on disk plus (bank, prog, model_name).
        Falls back gracefully to a bundled core timbre if the target pack has not been downloaded yet.
        """
        target_id = self.aliases.get(lib_id, lib_id)
        entry = self.timbres_by_id.get(target_id) or self.timbres_by_id.get(lib_id)

        if entry is None:
            prefix = lib_id.split("/")[0].lower()
            suffix = lib_id.split("/")[-1].lower()
            for k, v in self.timbres_by_id.items():
                kl = k.lower()
                if suffix in kl or prefix in kl:
                    entry = v
                    break

        if entry is not None:
            sf2_path = self._locate_asset_on_disk(entry)
            if sf2_path and os.path.isfile(sf2_path):
                res = dict(entry)
                res["sf2_path"] = sf2_path
                return res

        # Graceful fallback to bundled core timbre of matching category while pack downloads
        cat_key = entry.get("category_key", "") if entry else ""
        fallback_map = {
            "1 - A_PIANO": "1 - A_PIANO/1 - Model D 1983",
            "2 - E_PIANO": "2 - E_PIANO/1 - EP-Mark I",
            "4 - STRINGS_PADS": "4 - STRINGS_PADS/5 - SynthPad2",
            "5 - ORGANS": "5 - ORGANS/1 - PURE B3",
        }
        fb_id = fallback_map.get(cat_key, "1 - A_PIANO/1 - Model D 1983")
        fb_entry = self.timbres_by_id.get(fb_id)
        if fb_entry:
            sf2_path = self._locate_asset_on_disk(fb_entry)
            if sf2_path and os.path.isfile(sf2_path):
                res = dict(entry if entry else fb_entry)
                res["sf2_path"] = sf2_path
                res["bank"] = fb_entry["bank"]
                res["prog"] = fb_entry["prog"]
                return res

        return None

    def get_catalog_for_ui(self) -> List[dict]:
        return [
            {
                "lib_id": t["lib_id"],
                "category_key": t["category_key"],
                "category_name": t["category_name"],
                "zone_title": t.get("zone_title", t["category_name"]),
                "model_name": t["model_name"],
                "image_path": t.get("image_path", "../soundimages/INSTR_GRAND_PIANO_2.png"),
                "is_numares": bool(t.get("is_numares", False)),
                "bank": int(t.get("bank", 0)),
                "prog": int(t.get("prog", 0)),
            }
            for t in self.timbres_list
        ]


class SoundPackManager:
    """
    On-demand SoundPack Manager for Windows & Linux (matching Android P61xSoundPackManager).
    Supports both GitHub Release .zip packs and Google Drive direct .sf2 packs.
    """

    def __init__(
        self,
        catalog: TimbreCatalog,
        emit_callback: Optional[Callable[[dict], None]] = None,
        on_pack_installed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.catalog = catalog
        self.emit_callback = emit_callback
        self.on_pack_installed = on_pack_installed
        self._lock = threading.RLock()
        self._active_downloads: set = set()
        self.manifest: dict = self._load_manifest()

    def _load_manifest(self) -> dict:
        if os.path.isfile(SOUNDPACKS_MANIFEST_FILE):
            try:
                with open(SOUNDPACKS_MANIFEST_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[SoundPackManager] Erro ao carregar soundpacks.json: {e}")
        return {"packs": [], "coreAssetFiles": []}

    def _emit(self, payload: dict) -> None:
        if self.emit_callback:
            try:
                self.emit_callback(payload)
            except Exception:
                pass

    def _is_pack_installed(self, pack: dict) -> Tuple[bool, int]:
        if pack.get("bundled"):
            return True, 0
        direct_files = pack.get("directFiles", [])
        if direct_files:
            total_b = 0
            for df in direct_files:
                fname = df.get("sf2File", "")
                cand = os.path.join(CACHE_SF2_DIR, fname)
                if not os.path.isfile(cand) or os.path.getsize(cand) <= 1024:
                    cand_sf = os.path.join(LOCAL_SOUNDFONTS_DIR, fname)
                    if not os.path.isfile(cand_sf) or os.path.getsize(cand_sf) <= 1024:
                        return False, 0
                    total_b += os.path.getsize(cand_sf)
                else:
                    total_b += os.path.getsize(cand)
            return True, total_b

        asset_files = pack.get("assetFiles", [])
        if not asset_files:
            return False, 0
        total_b = 0
        for rel in asset_files:
            fname = os.path.basename(rel)
            cand_sb = os.path.join(SOUNDBANK_DIR, fname)
            cand_cache = os.path.join(CACHE_SF2_DIR, fname)
            if os.path.isfile(cand_sb) and os.path.getsize(cand_sb) > 1024:
                total_b += os.path.getsize(cand_sb)
            elif os.path.isfile(cand_cache) and os.path.getsize(cand_cache) > 1024:
                total_b += os.path.getsize(cand_cache)
            else:
                return False, 0
        return True, total_b

    def get_status_dict(self) -> dict:
        packs_out: List[dict] = []
        installed_lib_ids: List[str] = []
        total_timbres = 0
        installed_timbres = 0
        installed_bytes = 0

        for pk in self.manifest.get("packs", []):
            pid = pk.get("id", "")
            t_ids = list(pk.get("timbreIds", []))
            t_cnt = int(pk.get("timbreCount", len(t_ids)))
            total_timbres += t_cnt
            is_inst, disk_bytes = self._is_pack_installed(pk)
            if is_inst:
                installed_timbres += t_cnt
                installed_bytes += disk_bytes
                installed_lib_ids.extend(t_ids)
            with self._lock:
                is_dl = pid in self._active_downloads
            packs_out.append(
                {
                    "id": pid,
                    "name": pk.get("name", pid),
                    "description": pk.get("description", ""),
                    "bundled": bool(pk.get("bundled", False)),
                    "installed": is_inst,
                    "downloading": is_dl,
                    "timbreCount": t_cnt,
                    "sizeBytes": int(pk.get("sizeBytes", 0)),
                    "timbreIds": t_ids,
                }
            )

        # Also mark any local custom SF2 timbres as installed
        known_set = set(installed_lib_ids)
        for t in self.catalog.timbres_list:
            lid = t["lib_id"]
            if lid not in known_set and self.catalog.is_timbre_installed(t):
                installed_lib_ids.append(lid)
                known_set.add(lid)

        return {
            "ok": True,
            "totalTimbres": total_timbres,
            "installedTimbres": installed_timbres,
            "installedBytes": installed_bytes,
            "installedLibIds": installed_lib_ids,
            "packs": packs_out,
        }

    def download_pack(self, pack_id: str) -> None:
        pid = str(pack_id or "").strip()
        target_pack = next((p for p in self.manifest.get("packs", []) if p.get("id") == pid), None)
        if not target_pack or target_pack.get("bundled"):
            return
        with self._lock:
            if pid in self._active_downloads:
                return
            self._active_downloads.add(pid)

        def _worker() -> None:
            try:
                direct_files = target_pack.get("directFiles", [])
                if direct_files:
                    self._download_direct_files(pid, direct_files, int(target_pack.get("sizeBytes", 0)))
                else:
                    self._download_zip_pack(pid, target_pack)

                with self._lock:
                    self._active_downloads.discard(pid)
                self._emit({"event": "soundpack_progress", "packId": pid, "status": "installed", "pct": 100})
                self._emit({"event": "soundpack_status", **self.get_status_dict()})
                if self.on_pack_installed:
                    self.on_pack_installed(pid)
            except Exception as e:
                with self._lock:
                    self._active_downloads.discard(pid)
                self._emit(
                    {
                        "event": "soundpack_progress",
                        "packId": pid,
                        "status": "error",
                        "pct": 0,
                        "message": f"Falha no download: {e}",
                    }
                )
                self._emit({"event": "soundpack_status", **self.get_status_dict()})

        threading.Thread(target=_worker, daemon=True).start()

    def _download_direct_files(self, pid: str, direct_files: List[dict], pack_total_bytes: int) -> None:
        os.makedirs(CACHE_SF2_DIR, exist_ok=True)
        total_expected = pack_total_bytes or sum(int(df.get("sizeBytes", 0)) for df in direct_files)
        cumulative = 0
        last_pct = -1

        for df in direct_files:
            fname = df.get("sf2File", "")
            url = df.get("url", "")
            expected_size = int(df.get("sizeBytes", 0))
            expected_sha = str(df.get("sha256", "")).strip().lower()
            dest_path = os.path.join(CACHE_SF2_DIR, fname)

            if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 1024:
                if expected_size <= 0 or os.path.getsize(dest_path) == expected_size:
                    cumulative += os.path.getsize(dest_path)
                    continue

            tmp_path = dest_path + ".tmp"
            req = urllib.request.Request(url, headers={"User-Agent": "P61xConsole-Windows/1.3.3"})
            hasher = hashlib.sha256()
            header_buf = bytearray()

            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as out_f:
                while True:
                    chunk = resp.read(131072)
                    if not chunk:
                        break
                    if len(header_buf) < 12:
                        need = 12 - len(header_buf)
                        header_buf.extend(chunk[:need])
                        if len(header_buf) >= 12:
                            if header_buf[:4] != b"RIFF" or header_buf[8:12] != b"sfbk":
                                raise ValueError(f"Arquivo inválido para {fname} (cabeçalho não é SoundFont RIFF/sfbk)")
                    out_f.write(chunk)
                    hasher.update(chunk)
                    cumulative += len(chunk)
                    if total_expected > 0:
                        pct = min(99, int((cumulative * 100) / total_expected))
                        if pct != last_pct:
                            last_pct = pct
                            self._emit(
                                {
                                    "event": "soundpack_progress",
                                    "packId": pid,
                                    "status": "downloading",
                                    "pct": pct,
                                    "downloadedMb": round(cumulative / 1048576.0, 1),
                                    "totalMb": round(total_expected / 1048576.0, 1),
                                }
                            )

            if expected_sha and hasher.hexdigest().lower() != expected_sha:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                raise ValueError(f"Checksum SHA-256 inválido para {fname}")

            os.replace(tmp_path, dest_path)

    def _download_zip_pack(self, pid: str, pack: dict) -> None:
        os.makedirs(SOUNDBANK_DIR, exist_ok=True)
        url = pack.get("url", "")
        total_expected = int(pack.get("sizeBytes", 0))
        expected_sha = str(pack.get("sha256", "")).strip().lower()
        tmp_zip = os.path.join(CACHE_SF2_DIR, f"{pid}.zip.tmp")

        req = urllib.request.Request(url, headers={"User-Agent": "P61xConsole-Windows/1.3.3"})
        hasher = hashlib.sha256()
        downloaded = 0
        last_pct = -1

        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_zip, "wb") as out_f:
            if total_expected <= 0:
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total_expected = int(cl)
            while True:
                chunk = resp.read(131072)
                if not chunk:
                    break
                out_f.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if total_expected > 0:
                    pct = min(98, int((downloaded * 100) / total_expected))
                    if pct != last_pct:
                        last_pct = pct
                        self._emit(
                            {
                                "event": "soundpack_progress",
                                "packId": pid,
                                "status": "downloading",
                                "pct": pct,
                                "downloadedMb": round(downloaded / 1048576.0, 1),
                                "totalMb": round(total_expected / 1048576.0, 1),
                            }
                        )

        if expected_sha and hasher.hexdigest().lower() != expected_sha:
            try:
                os.remove(tmp_zip)
            except Exception:
                pass
            raise ValueError("Checksum SHA-256 do pacote ZIP não confere")

        self._emit({"event": "soundpack_progress", "packId": pid, "status": "extracting", "pct": 99})
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                fname = os.path.basename(member.filename)
                if not fname:
                    continue
                dest = os.path.join(SOUNDBANK_DIR, fname)
                tmp_dest = dest + ".tmp"
                with zf.open(member, "r") as src_f, open(tmp_dest, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)
                os.replace(tmp_dest, dest)
        try:
            os.remove(tmp_zip)
        except Exception:
            pass

    def remove_pack(self, pack_id: str) -> dict:
        pid = str(pack_id or "").strip()
        target_pack = next((p for p in self.manifest.get("packs", []) if p.get("id") == pid), None)
        if not target_pack or target_pack.get("bundled"):
            return self.get_status_dict()

        for df in target_pack.get("directFiles", []):
            fname = df.get("sf2File", "")
            if fname:
                p = os.path.join(CACHE_SF2_DIR, fname)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

        for rel in target_pack.get("assetFiles", []):
            fname = os.path.basename(rel)
            if fname:
                for folder in (SOUNDBANK_DIR, CACHE_SF2_DIR):
                    p = os.path.join(folder, fname)
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                    stem_sf2 = os.path.join(CACHE_SF2_DIR, os.path.splitext(fname)[0] + ".sf2")
                    if os.path.isfile(stem_sf2):
                        try:
                            os.remove(stem_sf2)
                        except Exception:
                            pass

        return self.get_status_dict()


def _migrate_saved_presets_if_needed(banks: Dict[str, List[dict]]) -> bool:
    """
    Ensures Worship Immersion (0 - Live Rig #0) Zona 4 is migrated once to Nord Red Ambient Pad.
    """
    migrated = False
    if os.path.isfile(MIGRATION_STATE_FILE):
        try:
            with open(MIGRATION_STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("migrated_worship_nord_pad_v1"):
                return False
        except Exception:
            pass

    live_rig = banks.get(LIVE_RIG_BANK_NAME, [])
    if live_rig and len(live_rig) > 0:
        p0 = live_rig[0]
        if p0.get("name") == "Worship Immersion":
            libs = p0.get("libs", [])
            if len(libs) >= 4 and libs[3] in ("4 - STRINGS_PADS/5 - SynthPad2", "4 - STRINGS_PADS/1 - StringsEnsemble"):
                libs[3] = "Nord Red Ambient Pad.sf2/Red Ambient Pad"
                if "zone_names" in p0 and len(p0["zone_names"]) >= 4:
                    p0["zone_names"][3] = "Nord Ambient Pad"
                if "zone_models" in p0 and len(p0["zone_models"]) >= 4:
                    p0["zone_models"][3] = "Nord Red Ambient Pad"
                migrated = True

    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(MIGRATION_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"migrated_worship_nord_pad_v1": True}, f)
    except Exception:
        pass
    return migrated


def load_all_standalone_banks(catalog: Optional[TimbreCatalog] = None) -> Dict[str, List[dict]]:
    """
    Loads all preset banks from mobile_catalog.json and overlays any user customizations
    stored in config/standalone_presets.json.
    """
    banks: Dict[str, List[dict]] = {}
    if catalog and catalog.catalog_banks:
        banks = copy.deepcopy(catalog.catalog_banks)
    elif os.path.isfile(MOBILE_CATALOG_FILE):
        try:
            with open(MOBILE_CATALOG_FILE, "r", encoding="utf-8") as f:
                banks = copy.deepcopy(json.load(f).get("banks", {}))
        except Exception:
            banks = {}

    if os.path.isfile(STANDALONE_PRESETS_FILE):
        try:
            with open(STANDALONE_PRESETS_FILE, "r", encoding="utf-8") as f:
                saved_overrides = json.load(f)
            if isinstance(saved_overrides, dict):
                for bname, plist in saved_overrides.items():
                    if isinstance(plist, list) and len(plist) > 0:
                        banks[bname] = plist
        except Exception:
            pass

    if _migrate_saved_presets_if_needed(banks) and os.path.isfile(STANDALONE_PRESETS_FILE):
        save_standalone_banks(banks)

    for plist in banks.values():
        for p in plist:
            p.setdefault("transposes", [0, 0, 0, 0])
            p.setdefault("key_lows", [21, 21, 21, 21])
            p.setdefault("key_his", [108, 108, 108, 108])
            p.setdefault("pans", [64, 64, 64, 64])
            p.setdefault("cutoffs", [127, 127, 127, 127])
            p.setdefault("resonances", [0, 0, 0, 0])
            p.setdefault("tones", [64, 64, 64, 64])
            p.setdefault("chorus", [0, 0, 0, 0])
            p.setdefault("attacks", [0, 0, 0, 0])
            p.setdefault("releases", [64, 64, 64, 64])
            p.setdefault("eqs", [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)])
            p.setdefault("sustain_enables", [True, True, True, True])

    return banks


def save_standalone_banks(banks: Dict[str, List[dict]]) -> bool:
    """Persists user preset modifications to config/standalone_presets.json."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(STANDALONE_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(banks, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[TimbreCatalog] Erro ao salvar presets: {e}")
        return False
