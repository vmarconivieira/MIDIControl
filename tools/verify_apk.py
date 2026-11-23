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
        assert "drawer-setlist-box" not in html, "Sidebar still contains drawer-setlist-box!"
        assert "translate3d(" in html, "Faders should use GPU translate3d"
    print(f"[OK] ZIP CRC + structure + UI checks passed ({len(names)} entries)")

    # 2. Manifest & resource IDs
    badging = run([aapt2, "dump", "badging", apk_path])
    assert f"versionCode='{expected_code}'" in badging, f"Unexpected versionCode in badging:\n{badging}"
    assert f"versionName='{expected_name}'" in badging, f"Unexpected versionName in badging:\n{badging}"
    assert "android.permission.INTERNET" in badging, "Missing INTERNET permission"
    assert "android.permission.REQUEST_INSTALL_PACKAGES" in badging, "Missing REQUEST_INSTALL_PACKAGES permission"
    manifest_tree = run([aapt2, "dump", "xmltree", apk_path, "--file", "AndroidManifest.xml"])
    assert "com.p61x.keyboard.UpdateInstallReceiver" in manifest_tree, "Missing UpdateInstallReceiver in manifest"
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
    print(f"[SUCCESS] APK verified cleanly: {apk_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
