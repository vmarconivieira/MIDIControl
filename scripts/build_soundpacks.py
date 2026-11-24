#!/usr/bin/env python3
"""
Build modular Sound Packs (.zip with decoded .sf2 files), soundpacks.json manifest,
and optimized PNG thumbnails (android/soundimages/) from base_template.apk.
"""
import hashlib
import io
import json
import os
import sys
import zipfile
from PIL import Image

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_APK = os.path.join(ROOT_DIR, "build", "base_template.apk")
OUT_PACKS_DIR = os.path.join(ROOT_DIR, "dist", "soundpacks")
OUT_IMAGES_DIR = os.path.join(ROOT_DIR, "android", "soundimages")
OUT_MANIFEST = os.path.join(ROOT_DIR, "soundpacks.json")

REPO = "vmarconivieira/MIDIControl"
PACKS_TAG = "soundpacks-v1"
BASE_URL = f"https://github.com/{REPO}/releases/download/{PACKS_TAG}"

CORE_ASSET_FILES = {
    "soundbank/1_-_Model_D_1983.numares",
    "soundbank/1_-_EP-Mark_I.numares",
    "soundbank/5_-_SynthPad2.numares",
    "soundbank/1_-_PURE_B3.numares",
}

PACK_DEFS = [
    {
        "id": "pack_apiano_extra",
        "name": "Pianos Acústicos",
        "description": "The Upright, CP E-Grand",
        "category": "1 - A_PIANO",
        "asset_files": [
            "soundbank/3_-_The_Upright.numares",
            "soundbank/4_-_CP_E-Grand.numares",
        ],
    },
    {
        "id": "pack_epiano_extra",
        "name": "Pianos Elétricos & FM",
        "description": "EP-Mark II, Wurly 200/255, FM-EP 1–4",
        "category": "2 - E_PIANO",
        "asset_files": [
            "soundbank/2_-_EP-Mark_II.numares",
            "soundbank/3_-_Wurly_200.numares",
            "soundbank/4_-_Wurly_255.numares",
            "soundbank/5_-_FM-EP1.numares",
            "soundbank/6_-_FM-EP2.numares",
            "soundbank/7_-_FM-EP3.numares",
            "soundbank/8_-_FM-EP4.numares",
        ],
    },
    {
        "id": "pack_strings_pads",
        "name": "Cordas, Corais & Pads",
        "description": "Strings Ensemble/Section, Cellos, SynthPad1, VoicePad, SynChoir",
        "category": "4 - STRINGS_PADS",
        "asset_files": [
            "soundbank/1_-_StringsEnsemble.numares",
            "soundbank/2_-_StringsSection.numares",
            "soundbank/3_-_Cellos.numares",
            "soundbank/4_-_SynthPad1.numares",
            "soundbank/6_-_VoicePad.numares",
            "soundbank/7_-_SynChoir.numares",
        ],
    },
    {
        "id": "pack_keys_mallets",
        "name": "Keys, Mallets & Acordeons",
        "description": "Clavinet, Harpsi, Vibes, Marimba, Celesta, Cassotto, MasteFisa, Musette",
        "category": "3 - KEYS_MALLETS",
        "asset_files": [
            "soundbank/1_-_Clavinet.numares",
            "soundbank/2_-_Harpsi.numares",
            "soundbank/3_-_Vibes.numares",
            "soundbank/4_-_Marimba.numares",
            "soundbank/5_-_Celesta.numares",
            "soundbank/6_-_Cassotto.numares",
            "soundbank/7_-_MasteFisa.numares",
            "soundbank/8_-_Musette.numares",
        ],
    },
    {
        "id": "pack_organs",
        "name": "Órgãos B3, Pipe & FM",
        "description": "19 órgãos adicionais (Jazz/Rock/Funk B3, Pipe Diapason, Full Organ)",
        "category": "5 - ORGANS",
        "asset_files": [
            "soundbank/2_-_SCAN_B3.numares",
            "soundbank/3_-_JAZZ_B3.numares",
            "soundbank/4_-_ROCK_B3.numares",
            "soundbank/5_-_FUNK_B3.numares",
            "soundbank/6_-_SCAN_PERC_B3.numares",
            "soundbank/7_-_POP_MID_SET.numares",
            "soundbank/8_-_MID_VIB_SET.numares",
            "soundbank/9_-_FULL_SET_B3.numares",
            "soundbank/10_-_FULL_VIB_SET.numares",
            "soundbank/11_-_SILK_SETTING.numares",
            "soundbank/12_-_EL_ORGAN_1.numares",
            "soundbank/13_-_EL_ORGAN_2.numares",
            "soundbank/14_-_VINT_PERC_1.numares",
            "soundbank/15_-_VINT_PERC_2.numares",
            "soundbank/16_-_FM_ORGAN_1.numares",
            "soundbank/17_-_FM_ORGAN_2.numares",
            "soundbank/18-_PIPE_DIAPASON.numares",
            "soundbank/19_-_PIPE_PLENUM.numares",
            "soundbank/20_-_FULL_ORGAN.numares",
        ],
    },
    {
        "id": "pack_bells_bass",
        "name": "Fantasia Bells & Synth Bass",
        "description": "Fantasia Bells, Sub Moog, Juno 80s, Reese, FM Solid Pluck",
        "category": "SF2",
        "asset_files": [
            "soundbank/Fantasia_Bells.sf2",
            "soundbank/SynthBass_Pack.sf2",
        ],
    },
]


def decoded_sf2_name(asset_file: str) -> str:
    base = os.path.basename(asset_file)
    return base[:-8] + ".sf2" if base.endswith(".numares") else base


def decode_numares_if_needed(raw: bytes, asset_file: str) -> bytes:
    if asset_file.endswith(".numares"):
        # Fast XOR 0x5A translation table
        tbl = bytes(i ^ 0x5A for i in range(256))
        out = raw.translate(tbl)
    else:
        out = raw
    assert out[:4] == b"RIFF" and out[8:12] == b"sfbk", f"Invalid SF2 after decode: {asset_file}"
    return out


def optimize_soundimages(zf: zipfile.ZipFile):
    os.makedirs(OUT_IMAGES_DIR, exist_ok=True)
    orig_total = 0
    opt_total = 0
    count = 0
    for info in zf.infolist():
        if not info.filename.startswith("assets/soundimages/") or not info.filename.lower().endswith(".png"):
            continue
        raw = zf.read(info.filename)
        orig_total += len(raw)
        im = Image.open(io.BytesIO(raw))
        # Resize cleanly to max 480px wide for mobile timbre cards
        w, h = im.size
        if w > 480:
            nh = max(1, round(h * 480 / w))
            im = im.resize((480, nh), Image.Resampling.LANCZOS)
        # Quantize to crisp 256-color PNG (preserves RGBA alpha cleanly via FASTOCTREE)
        if im.mode == "RGBA":
            im_q = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
        else:
            im_q = im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        out_path = os.path.join(OUT_IMAGES_DIR, os.path.basename(info.filename))
        im_q.save(out_path, format="PNG", optimize=True)
        opt_total += os.path.getsize(out_path)
        count += 1
    print(f"[OK] Optimized {count} soundimages: {orig_total/1048576:.2f} MB -> {opt_total/1048576:.2f} MB")


def main():
    if not os.path.isfile(BASE_APK):
        print(f"[ERROR] Missing {BASE_APK}. Run build_apk.sh once or reassemble base_pack first.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUT_PACKS_DIR, exist_ok=True)

    with zipfile.ZipFile(BASE_APK, "r") as zf:
        cat = json.loads(zf.read("assets/mobile_catalog.json").decode("utf-8"))
        timbres = cat.get("timbre_catalog", [])
        all_sb = sorted(f[len("assets/"):] for f in zf.namelist() if f.startswith("assets/soundbank/"))

        # Validate 100% coverage between CORE and PACK_DEFS
        covered = set(CORE_ASSET_FILES)
        for p in PACK_DEFS:
            for af in p["asset_files"]:
                assert af not in covered, f"Duplicate asset_file across packs: {af}"
                covered.add(af)
        missing = set(all_sb) - covered
        extra = covered - set(all_sb)
        assert not missing, f"Soundbank files missing from pack config: {missing}"
        assert not extra, f"Unknown soundbank files in pack config: {extra}"

        # Map asset_file -> list of timbre lib_ids and model names
        timbres_by_file = {}
        for t in timbres:
            timbres_by_file.setdefault(t["asset_file"], []).append(t)

        # 1. Optimize soundimages into android/soundimages/
        optimize_soundimages(zf)

        # 2. Build Core metadata + 6 downloadable .zip sound packs
        core_lib_ids = []
        core_sf2_files = []
        for af in sorted(CORE_ASSET_FILES):
            core_sf2_files.append(decoded_sf2_name(af))
            for t in timbres_by_file.get(af, []):
                core_lib_ids.append(t["lib_id"])

        packs_out = [
            {
                "id": "core",
                "name": "Essencial (Embutido)",
                "description": "Model D 1983, EP-Mark I, SynthPad2, PURE B3",
                "bundled": True,
                "zipFile": "",
                "downloadUrl": "",
                "sizeBytes": 0,
                "sha256": "",
                "sf2Files": core_sf2_files,
                "timbreIds": core_lib_ids,
                "timbreCount": len(core_lib_ids),
            }
        ]

        for p in PACK_DEFS:
            zip_name = f"{p['id']}.zip"
            zip_path = os.path.join(OUT_PACKS_DIR, zip_name)
            sf2_names = []
            lib_ids = []
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
                for af in p["asset_files"]:
                    raw = zf.read("assets/" + af)
                    sf2_bytes = decode_numares_if_needed(raw, af)
                    sf2_name = decoded_sf2_name(af)
                    zi = zipfile.ZipInfo(sf2_name)
                    zi.date_time = (2026, 1, 1, 0, 0, 0)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(zi, sf2_bytes)
                    sf2_names.append(sf2_name)
                    for t in timbres_by_file.get(af, []):
                        lib_ids.append(t["lib_id"])

            sz = os.path.getsize(zip_path)
            h = hashlib.sha256()
            with open(zip_path, "rb") as f:
                for chunk in iter(lambda: f.read(1048576), b""):
                    h.update(chunk)
            sha = h.hexdigest()

            packs_out.append({
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "bundled": False,
                "zipFile": zip_name,
                "downloadUrl": f"{BASE_URL}/{zip_name}",
                "sizeBytes": sz,
                "sha256": sha,
                "sf2Files": sf2_names,
                "timbreIds": lib_ids,
                "timbreCount": len(lib_ids),
            })
            print(f"[OK] Built {zip_name:24s} | {len(lib_ids):2d} timbres | {sz/1048576:6.2f} MB | sha256={sha[:12]}...")

        manifest = {
            "version": 1,
            "repo": REPO,
            "releaseTag": PACKS_TAG,
            "coreAssetFiles": sorted(CORE_ASSET_FILES),
            "packs": packs_out,
        }
        with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[DONE] Wrote {OUT_MANIFEST} ({len(packs_out)} packs, {sum(p['timbreCount'] for p in packs_out)} timbres total)")


if __name__ == "__main__":
    main()
