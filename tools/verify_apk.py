#!/usr/bin/env python3
"""Verify built P61x Console APK integrity, manifest, alignment, signature, and UI checks."""
import json
import os
import subprocess
import sys
import zipfile


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        print(f"[FAIL] Command failed: {' '.join(cmd)}\n{p.stdout}")
        sys.exit(1)
    return p.stdout


def main():
    if len(sys.argv) < 4:
        print("Usage: verify_apk.py <apk_path> <build_tools_dir> <version_json>")
        sys.exit(1)

    apk_path = sys.argv[1]
    bt = sys.argv[2]
    ver_path = sys.argv[3]

    with open(ver_path, "r", encoding="utf-8") as f:
        ver = json.load(f)
    expected_code = str(ver["versionCode"])
    expected_name = str(ver["versionName"])

    aapt2 = os.path.join(bt, "aapt2")
    zipalign = os.path.join(bt, "zipalign")
    apksigner = os.path.join(bt, "apksigner")

    # 1. ZIP CRC & structure
    with zipfile.ZipFile(apk_path, "r") as zf:
        bad = zf.testzip()
        assert bad is None, f"Corrupt ZIP entry: {bad}"
        names = set(zf.namelist())
        for req in [
            "AndroidManifest.xml",
            "resources.arsc",
            "classes.dex",
            "assets/ui/index.html",
            "assets/soundpacks.json",
            "lib/arm64-v8a/libstagerig_dsp.so",
            "lib/arm64-v8a/libfluidsynth.so",
            "lib/arm64-v8a/liboboe.so",
            "res/mipmap-xxxhdpi-v4/ic_launcher.png",
        ]:
            assert req in names, f"Missing APK entry: {req}"
        # Verify uncompressed alignment-sensitive files
        for info in zf.infolist():
            if info.filename.endswith(".so") or info.filename == "resources.arsc":
                assert info.compress_type == zipfile.ZIP_STORED, f"Must be STORED: {info.filename}"
        html = zf.read("assets/ui/index.html").decode("utf-8")
        assert 'id="btnToggleFullscreen"' not in html, "Fullscreen button should stay removed"
        assert 'id="setlistModal"' in html, "Missing #setlistModal"
        assert 'id="updateModal"' in html, "Missing #updateModal"
        assert 'id="btnRescanMidi"' in html, "Missing #btnRescanMidi"
        assert 'id="globalTransposePill"' in html, "Missing #globalTransposePill"
        assert 'class="knobs-rack"' not in html, "Top knobs-rack should be removed from Mixer"
        assert 'id="subtabFxBtn"' in html, "Missing #subtabFxBtn in Zone Inspector modal"
        assert 'id="zoneFxKnobsGrid"' in html, "Missing #zoneFxKnobsGrid"
        assert 'id="zoneEqKnobsGrid"' in html, "Missing #zoneEqKnobsGrid"
        assert 'id="masterFxModalKnobs"' in html, "Missing #masterFxModalKnobs"
        assert 'id="btnScanBleMidi"' in html, "Missing #btnScanBleMidi"
        assert 'id="btnModeBtLowLat"' not in html, "BT audio optimization button should be removed"
        assert 'id="btnOpenBtSettings"' not in html, "BT audio settings shortcut should be removed"
        assert "applyAudioMode" not in html, "applyAudioMode bridge call should be removed"
        assert "openBluetoothSettings" not in html, "openBluetoothSettings bridge call should be removed"
        assert 'id="padLayerKnobHost0"' in html, "Missing Pad Layer rotary knob hosts"
        assert 'id="padsQuickMasterKnobHost"' in html, "Missing Pads Quick Master rotary knob host"
        assert "drum-vol-slider" not in html, "Horizontal drum sliders should be replaced by rotary knobs"
        assert "padLayerSlider0" not in html, "Horizontal pad layer sliders should be replaced by rotary knobs"
        assert "data-vu-left=" not in html, "Left-side VU ladders should be removed (right side only)"
        assert "data-vu-right=" in html, "Right-side VU ladders missing"
        assert "nkp-major" in html and "nkp-minor" in html, "Missing centered major/minor pad key styling"
        assert ">SOBRE<" in html, "Missing SOBRE menu item"
        assert "drawer-setlist-box" not in html, "Sidebar still contains drawer-setlist-box!"
        assert "translate3d(" in html, "Faders should use GPU translate3d"
        assert 'id="soundPacksModal"' in html, "Missing #soundPacksModal"
        assert 'id="padLayersFadersGrid"' in html, "Missing Pads faders grid"
        assert 'id="btnPadsModeFaders"' in html, "Missing Pads FADERS toggle"
        assert 'id="btnExportCtrlProfile"' in html, "Missing #btnExportCtrlProfile"
        assert 'id="btnImportCtrlProfile"' in html, "Missing #btnImportCtrlProfile"
        for bad in ("\U0001F3B5", "\U0001F3B9", "STAGE RIG WORKSTATION", "Arraste no knob ou na barra"):
            assert bad not in html, f"Removed UI text/emoji still present: {bad!r}"
        ui_map_def = json.loads(zf.read("assets/config_defaults/ui_mappings.json").decode("utf-8"))
        assert len(ui_map_def) == 21 and "vol_master_pad" in ui_map_def, f"Unexpected default ui_mappings count: {len(ui_map_def)}"
        origin_prof = json.loads(zf.read("assets/config_defaults/controller_profiles/Origin_62_P61x_AMW.json").decode("utf-8"))
        assert "vol_master_pad" in origin_prof.get("ui_mappings", {}), "Origin_62_P61x_AMW missing vol_master_pad"
        assert len(origin_prof.get("ui_mappings", {})) == 21, f"Origin_62_P61x_AMW should have 21 mappings"
        prebuilt_so = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "native", "prebuilt", "arm64-v8a", "libstagerig_dsp.so")
        if os.path.isfile(prebuilt_so):
            import hashlib
            h_prebuilt = hashlib.sha256(open(prebuilt_so, "rb").read()).hexdigest()
            h_apk = hashlib.sha256(zf.read("lib/arm64-v8a/libstagerig_dsp.so")).hexdigest()
            assert h_apk == h_prebuilt, f"APK libstagerig_dsp.so SHA mismatch: {h_apk} != {h_prebuilt}"
        sp = json.loads(zf.read("assets/soundpacks.json").decode("utf-8"))
        assert len(sp["packs"]) == 18, f"Expected 18 sound packs, got {len(sp['packs'])}"
        for core in sp["coreAssetFiles"]:
            assert "assets/" + core in names, f"Missing core soundbank in APK: {core}"
        bundled = [n for n in names if n.startswith("assets/soundbank/")]
        assert len(bundled) == len(sp["coreAssetFiles"]), f"Lite APK must bundle only core timbres, found {len(bundled)}"
        cat = json.loads(zf.read("assets/mobile_catalog.json").decode("utf-8"))
        assert len(cat["timbre_catalog"]) == 98, f"Expected 98 timbres in mobile_catalog.json, got {len(cat['timbre_catalog'])}"
        w0 = cat["banks"]["0 - Live Rig"][0]
        assert w0["name"] == "Worship Immersion", f"Expected Preset 0 to be Worship Immersion, got {w0['name']}"
        assert w0["libs"][3] == "Nord Red Ambient Pad.sf2/Red Ambient Pad", f"Unexpected Zona 4 timbre in Worship Immersion: {w0['libs'][3]}"
    print(f"[OK] ZIP CRC + structure + UI + DSP SHA + 98-timbre catalog checks passed ({len(names)} entries)")

    # 2. Manifest & resource IDs
    badging = run([aapt2, "dump", "badging", apk_path])
    assert f"versionCode='{expected_code}'" in badging, f"Unexpected versionCode in badging:\n{badging}"
    assert f"versionName='{expected_name}'" in badging, f"Unexpected versionName in badging:\n{badging}"
    assert "android.permission.INTERNET" in badging, "Missing INTERNET permission"
    assert "android.permission.REQUEST_INSTALL_PACKAGES" in badging, "Missing REQUEST_INSTALL_PACKAGES permission"
    assert "android.permission.BLUETOOTH_SCAN" in badging, "Missing BLUETOOTH_SCAN permission"
    assert "android.permission.BLUETOOTH_CONNECT" in badging, "Missing BLUETOOTH_CONNECT permission"
    manifest_tree = run([aapt2, "dump", "xmltree", apk_path, "--file", "AndroidManifest.xml"])
    assert "com.p61x.keyboard.UpdateInstallReceiver" in manifest_tree, "Missing UpdateInstallReceiver in manifest"
    assert "com.p61x.keyboard.UpdateInstallActivity" in manifest_tree, "Missing UpdateInstallActivity in manifest"
    assert "android.intent.action.MY_PACKAGE_REPLACED" in manifest_tree, "Missing MY_PACKAGE_REPLACED receiver filter"
    res_dump = run([aapt2, "dump", "resources", apk_path])
    assert "0x7f010000 mipmap/ic_launcher" in res_dump, "mipmap/ic_launcher ID mismatch"
    assert "0x7f020000 style/Theme.P61xStage" in res_dump, "style/Theme.P61xStage ID mismatch"
    print(f"[OK] Manifest (v{expected_name} code={expected_code}, permissions, receiver) & resource IDs verified")

    # 3. 16 KB page alignment check
    run([zipalign, "-c", "-P", "16", "4", apk_path])
    print("[OK] zipalign -c -P 16 4 passed (16 KB page alignment)")

    # 4. Signature verification (v1+v2+v3)
    sig_out = run([apksigner, "verify", "--verbose", "--min-sdk-version", "21", apk_path])
    assert "Verified using v1 scheme (JAR signing): true" in sig_out, sig_out
    assert "Verified using v2 scheme (APK Signature Scheme v2): true" in sig_out, sig_out
    assert "Verified using v3 scheme (APK Signature Scheme v3): true" in sig_out, sig_out
    print("[OK] apksigner verify passed (v1=true, v2=true, v3=true)")

    size_mb = os.path.getsize(apk_path) / (1024 * 1024)
    assert size_mb < 100, f"APK too large for Lite build: {size_mb:.1f} MB"
    print(f"[SUCCESS] APK verified cleanly: {apk_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
