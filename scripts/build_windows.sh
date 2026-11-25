#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
WIN_SRC="$ROOT_DIR/windows"
CACHE_DIR="$BUILD_DIR/win_cache"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$CACHE_DIR/wheels"

VERSION_JSON="$ROOT_DIR/version.json"
VERSION_NAME="${VERSION_NAME:-$(python3 -c "import json; print(json.load(open('$VERSION_JSON'))['versionName'])")}"
VERSION_CODE="${VERSION_CODE:-$(python3 -c "import json; print(json.load(open('$VERSION_JSON'))['versionCode'])")}"
VER_COMMA="$(python3 -c "p='$VERSION_NAME'.split('.'); p=(p+['0','0','0'])[:3]; print(f'{p[0]},{p[1]},{p[2]},$VERSION_CODE')")"

ZIP_FILENAME="P61x_Console_Windows_v${VERSION_NAME}.zip"
SETUP_FILENAME="P61x_Console_Setup_v${VERSION_NAME}.exe"
OUT_ZIP="${1:-$DIST_DIR/$ZIP_FILENAME}"
OUT_EXE="${2:-$DIST_DIR/$SETUP_FILENAME}"

echo "=== Building P61x Console Windows v${VERSION_NAME} (code=${VERSION_CODE}) ==="

for tool in x86_64-w64-mingw32-gcc x86_64-w64-mingw32-windres makensis zip unzip curl python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "[ERROR] Missing required tool: $tool" >&2; exit 1; }
done

# 1. Ensure base_template.apk is assembled & verified for shared assets
BASE_APK="$BUILD_DIR/base_template.apk"
if [[ ! -f "$BASE_APK" ]]; then
  echo "[STEP] Reassembling base_template.apk from base_pack/..."
  cat "$ROOT_DIR"/base_pack/base_template.apk.part_* > "$BASE_APK"
fi
if [[ -f "$ROOT_DIR/base_pack/base_template.sha256" ]]; then
  EXPECTED_SHA="$(awk '{print $1}' "$ROOT_DIR/base_pack/base_template.sha256")"
  ACTUAL_SHA="$(sha256sum "$BASE_APK" | awk '{print $1}')"
  if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    cat "$ROOT_DIR"/base_pack/base_template.apk.part_* > "$BASE_APK"
    ACTUAL_SHA="$(sha256sum "$BASE_APK" | awk '{print $1}')"
    [[ "$EXPECTED_SHA" == "$ACTUAL_SHA" ]] || { echo "[ERROR] base_template.apk SHA mismatch" >&2; exit 1; }
  fi
fi

# 2. Cross-compile native stagerig_dsp.dll (WinMM C ring buffer + crash logger + FluidSynth 2.6.3 SR fix)
echo "[STEP] Cross-compiling windows/dsp/stagerig_dsp.dll..."
x86_64-w64-mingw32-gcc -O3 -shared -fno-math-errno -std=gnu11 \
  -Wall -Wno-unused-function -Wno-unused-variable -s \
  "$ROOT_DIR/native/stagerig_dsp.c" \
  -o "$WIN_SRC/dsp/stagerig_dsp.dll" \
  -L"$WIN_SRC/dsp" -l:libfluidsynth-3.dll -l:portaudio_x64.dll -lwinmm -lm \
  -Wl,--enable-stdcall-fixup

# Verify required exports in stagerig_dsp.dll (avoid pipe into grep -q under set -o pipefail)
DLL_DUMP="$(x86_64-w64-mingw32-objdump -p "$WIN_SRC/dsp/stagerig_dsp.dll")"
grep -q "stagerig_winmm_in_poll" <<< "$DLL_DUMP"
grep -q "stagerig_install_crash_handler" <<< "$DLL_DUMP"
grep -q "fluid_synth_sfcount" <<< "$DLL_DUMP"

# 3. Assemble clean staging folder (reusing base_pack/, ui/, android/ shared assets)
STAGE_PARENT="$BUILD_DIR/windows_stage"
STAGE_DIR="$STAGE_PARENT/P61x_Keyboard_Windows"
rm -rf "$STAGE_PARENT"
mkdir -p "$STAGE_DIR"/{dsp,ui,Libraries,config,drum_pads,pad_loops,soundbank,soundimages,soundfonts}

cp "$WIN_SRC"/*.py "$WIN_SRC"/*.bat "$WIN_SRC"/*.vbs "$WIN_SRC/requirements-windows.txt" "$WIN_SRC/LEIAME_WINDOWS.txt" "$STAGE_DIR/"
cp "$ROOT_DIR/version.json" "$ROOT_DIR/soundpacks.json" "$STAGE_DIR/"
cp "$ROOT_DIR/android/mobile_catalog.json" "$STAGE_DIR/"
cp "$WIN_SRC"/dsp/*.dll "$STAGE_DIR/dsp/"
cp -r "$WIN_SRC"/Libraries/* "$STAGE_DIR/Libraries/"
cp -r "$WIN_SRC"/config/* "$STAGE_DIR/config/"
cp -r "$WIN_SRC"/ui_assets/* "$STAGE_DIR/ui/"
cp "$ROOT_DIR/ui/index.html" "$STAGE_DIR/ui/index.html"
cp -r "$ROOT_DIR/android/soundimages/"* "$STAGE_DIR/soundimages/"

echo "[STEP] Extracting core shared audio assets from base_template.apk..."
python3 - "$BASE_APK" "$ROOT_DIR/soundpacks.json" "$STAGE_DIR" << 'PY'
import json, os, sys, zipfile

base_apk, manifest_path, stage_dir = sys.argv[1:4]
core_assets = set("assets/" + p for p in json.load(open(manifest_path, encoding="utf-8"))["coreAssetFiles"])
# 4 Worship Pad layers only (Shimmer layer 4 permanently removed)
ALLOWED_PADS = {f"assets/pad_loops/pad_layer_{i}.ogg" for i in range(4)}

with zipfile.ZipFile(base_apk, "r") as zf:
    for info in zf.infolist():
        fn = info.filename
        if fn.endswith("/"):
            continue
        rel = None
        if fn.startswith("assets/drum_pads/"):
            rel = fn[len("assets/"):]
        elif fn in ALLOWED_PADS:
            rel = fn[len("assets/"):]
        elif fn in core_assets and fn.startswith("assets/soundbank/"):
            rel = fn[len("assets/"):]
        if rel:
            out_path = os.path.join(stage_dir, rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(zf.read(fn))
PY

# 4. Compile native GUI launcher executable (P61x Console.exe)
echo "[STEP] Compiling native Windows launcher P61x Console.exe..."
ICON_FILE="$WIN_SRC/ui_assets/p61x-keyboard.ico"
RC_GEN="$BUILD_DIR/p61x_launcher.rc"
RES_OBJ="$BUILD_DIR/p61x_launcher_res.o"
python3 - "$WIN_SRC/installer/p61x_launcher.rc.in" "$RC_GEN" "$ICON_FILE" "$VERSION_NAME" "$VER_COMMA" << 'PY'
import sys
src, dst, icon, vname, vcomma = sys.argv[1:6]
txt = open(src, encoding="utf-8").read()
txt = txt.replace("@ICON_PATH@", icon).replace("@VERSION_NAME@", vname).replace("@VER_COMMA@", vcomma)
open(dst, "w", encoding="utf-8").write(txt)
PY
x86_64-w64-mingw32-windres "$RC_GEN" -O coff -o "$RES_OBJ"
x86_64-w64-mingw32-gcc -O2 -mwindows -municode -s \
  "$WIN_SRC/installer/p61x_launcher.c" "$RES_OBJ" \
  -o "$STAGE_DIR/P61x Console.exe" -lshell32

# 5. Build portable ZIP (without embedded Python runtime; uses instalar_windows.bat)
echo "[STEP] Packaging portable ZIP: $OUT_ZIP..."
rm -f "$OUT_ZIP"
(cd "$STAGE_PARENT" && zip -q -r "$OUT_ZIP" "P61x_Keyboard_Windows")
echo "[OK] Built portable ZIP ($(du -h "$OUT_ZIP" | awk '{print $1}'))"

# 6. Bundle standalone Python 3.12 win_amd64 + PySide6 + numpy into STAGE_DIR/runtime for zero-dependency Setup EXE
EMBED_ZIP="$CACHE_DIR/python-3.12.10-embed-amd64.zip"
if [[ ! -f "$EMBED_ZIP" ]]; then
  echo "[STEP] Downloading Python 3.12.10 embeddable runtime (win_amd64)..."
  curl -fsSL "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" -o "$EMBED_ZIP"
fi

if ! ls "$CACHE_DIR/wheels"/PySide6-*.whl >/dev/null 2>&1; then
  echo "[STEP] Downloading PySide6 + numpy Windows wheels..."
  python3 -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 \
    -d "$CACHE_DIR/wheels" "PySide6>=6.7,<6.9" "numpy>=1.26,<2.2"
fi

echo "[STEP] Extracting offline Windows runtime into STAGE_DIR/runtime..."
mkdir -p "$STAGE_DIR/runtime/Lib/site-packages"
unzip -oq "$EMBED_ZIP" -d "$STAGE_DIR/runtime"
printf "python312.zip\r\n.\r\nLib\r\nLib\\\\site-packages\r\n..\r\nimport site\r\n" > "$STAGE_DIR/runtime/python312._pth"

for whl in "$CACHE_DIR/wheels"/*.whl; do
  unzip -oq "$whl" -d "$STAGE_DIR/runtime/Lib/site-packages"
done

# Strip development-only headers/stubs from PySide6 while keeping all runtime binaries & WebEngine resources intact
rm -rf "$STAGE_DIR/runtime/Lib/site-packages/PySide6/"{include,typesystems,metatypes,glue,doc,examples}
find "$STAGE_DIR/runtime/Lib/site-packages" -type f -name "*.pyi" -delete

# Ensure VC++ runtime DLLs sit directly next to pythonw.exe/python312.dll (matching v1.3.5 layout)
for dll in concrt140.dll msvcp140.dll msvcp140_1.dll msvcp140_2.dll msvcp140_codecvt_ids.dll vcruntime140.dll vcruntime140_1.dll; do
  if [[ -f "$STAGE_DIR/runtime/Lib/site-packages/PySide6/$dll" ]]; then
    cp -f "$STAGE_DIR/runtime/Lib/site-packages/PySide6/$dll" "$STAGE_DIR/runtime/$dll"
  fi
done

# 7. Compile self-contained NSIS Windows Setup Installer EXE
echo "[STEP] Building NSIS installer: $OUT_EXE..."
NSI_GEN="$BUILD_DIR/p61x_setup.nsi"
python3 - "$WIN_SRC/installer/p61x_setup.nsi.in" "$NSI_GEN" "$VERSION_NAME" "$OUT_EXE" "$ICON_FILE" "$STAGE_DIR" << 'PY'
import sys
src, dst, vname, out_exe, icon, stage_dir = sys.argv[1:7]
txt = open(src, encoding="utf-8").read()
txt = (txt
       .replace("@VERSION_NAME@", vname)
       .replace("@OUT_EXE@", out_exe)
       .replace("@ICON_PATH@", icon)
       .replace("@STAGE_DIR@", stage_dir))
open(dst, "w", encoding="utf-8").write(txt)
PY

makensis -V2 "$NSI_GEN"
test -s "$OUT_EXE"
echo "[OK] Built Windows Setup EXE: $OUT_EXE ($(du -h "$OUT_EXE" | awk '{print $1}'))"
