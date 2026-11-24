#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# 1. Read version metadata from version.json
VERSION_JSON="$ROOT_DIR/version.json"
VERSION_CODE="${VERSION_CODE:-$(python3 -c "import json; print(json.load(open('$VERSION_JSON'))['versionCode'])")}"
VERSION_NAME="${VERSION_NAME:-$(python3 -c "import json; print(json.load(open('$VERSION_JSON'))['versionName'])")}"
APK_FILENAME="${APK_FILENAME:-$(python3 -c "import json; d=json.load(open('$VERSION_JSON')); print(d.get('apkFileName', f'P61x_Console_v{d[\"versionName\"]}.apk'))")}"
OUT_APK="${1:-$DIST_DIR/$APK_FILENAME}"

echo "=== Building P61x Console v${VERSION_NAME} (versionCode=${VERSION_CODE}) ==="

# 2. Locate Android SDK, build-tools, and android.jar
SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$SDK_DIR" ]]; then
  for cand in /opt/android-sdk /usr/local/lib/android/sdk "$HOME/Android/Sdk"; do
    if [[ -d "$cand/build-tools" ]]; then
      SDK_DIR="$cand"
      break
    fi
  done
fi
if [[ -z "$SDK_DIR" || ! -d "$SDK_DIR/build-tools" ]]; then
  echo "[ERROR] Android SDK not found. Set ANDROID_HOME." >&2
  exit 1
fi

BT_DIR="$(find "$SDK_DIR/build-tools" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -n 1)"
ANDROID_JAR="$(find "$SDK_DIR/platforms" -maxdepth 2 -name android.jar | sort -V | tail -n 1)"
echo "[INFO] SDK=$SDK_DIR"
echo "[INFO] Build-tools=$BT_DIR"
echo "[INFO] Android JAR=$ANDROID_JAR"

# 3. Locate smali-dexlib2 jars (or download from Maven Central if missing on CI)
find_jar() {
  local pattern="$1"
  find "$SDK_DIR" "$BUILD_DIR/libs" -name "$pattern" 2>/dev/null | head -n 1 || true
}

mkdir -p "$BUILD_DIR/libs"
DEXLIB2_JAR="$(find_jar 'smali-dexlib2-*.jar')"
SMALI_UTIL_JAR="$(find_jar 'smali-util-*.jar')"
GUAVA_JAR="$(find_jar 'guava-*.jar')"
FAILUREACCESS_JAR="$(find_jar 'failureaccess-*.jar')"

download_maven() {
  local url="$1"
  local dest="$BUILD_DIR/libs/$(basename "$1")"
  if [[ ! -f "$dest" ]]; then
    echo "[INFO] Downloading $(basename "$dest")..."
    curl -fsSL "$url" -o "$dest"
  fi
  echo "$dest"
}

[[ -z "$DEXLIB2_JAR" ]] && DEXLIB2_JAR="$(download_maven https://repo1.maven.org/maven2/com/android/tools/smali/smali-dexlib2/3.0.3/smali-dexlib2-3.0.3.jar)"
[[ -z "$SMALI_UTIL_JAR" ]] && SMALI_UTIL_JAR="$(download_maven https://repo1.maven.org/maven2/com/android/tools/smali/smali-util/3.0.3/smali-util-3.0.3.jar)"
[[ -z "$GUAVA_JAR" ]] && GUAVA_JAR="$(download_maven https://repo1.maven.org/maven2/com/google/guava/guava/32.0.1-jre/guava-32.0.1-jre.jar)"
[[ -z "$FAILUREACCESS_JAR" ]] && FAILUREACCESS_JAR="$(download_maven https://repo1.maven.org/maven2/com/google/guava/failureaccess/1.0.1/failureaccess-1.0.1.jar)"
DEXLIB_CP="${DEXLIB2_JAR}:${SMALI_UTIL_JAR}:${GUAVA_JAR}:${FAILUREACCESS_JAR}"

# 4. Reassemble base_template.apk from split chunks and verify SHA-256
BASE_APK="$BUILD_DIR/base_template.apk"
if [[ ! -f "$BASE_APK" ]]; then
  echo "[STEP] Reassembling base_template.apk from base_pack/..."
  cat "$ROOT_DIR"/base_pack/base_template.apk.part_* > "$BASE_APK"
fi
if [[ -f "$ROOT_DIR/base_pack/base_template.sha256" ]]; then
  EXPECTED_SHA="$(awk '{print $1}' "$ROOT_DIR/base_pack/base_template.sha256")"
  ACTUAL_SHA="$(sha256sum "$BASE_APK" | awk '{print $1}')"
  if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    echo "[WARN] Cached base_template.apk SHA mismatch; reassembling..."
    cat "$ROOT_DIR"/base_pack/base_template.apk.part_* > "$BASE_APK"
    ACTUAL_SHA="$(sha256sum "$BASE_APK" | awk '{print $1}')"
    if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
      echo "[ERROR] base_template.apk SHA-256 verification failed!" >&2
      exit 1
    fi
  fi
  echo "[OK] base_template.apk SHA-256 verified"
fi

# 5. Compile resources and AndroidManifest.xml with aapt2
rm -rf "$BUILD_DIR/res_stage" "$BUILD_DIR/cls_patch" "$BUILD_DIR/cls_tools" "$BUILD_DIR/dex_patch" "$BUILD_DIR/d8_check"
mkdir -p "$BUILD_DIR/res_stage" "$BUILD_DIR/cls_patch" "$BUILD_DIR/cls_tools" "$BUILD_DIR/dex_patch" "$BUILD_DIR/d8_check"

echo "[STEP] Compiling AndroidManifest.xml and resources via aapt2..."
"$BT_DIR/aapt2" compile --dir "$ROOT_DIR/android/res" -o "$BUILD_DIR/res_stage/res.zip"
"$BT_DIR/aapt2" link \
  -I "$ANDROID_JAR" \
  --manifest "$ROOT_DIR/android/AndroidManifest.xml" \
  --min-sdk-version 27 \
  --target-sdk-version 35 \
  --version-code "$VERSION_CODE" \
  --version-name "$VERSION_NAME" \
  -o "$BUILD_DIR/res_stage/res_linked.apk" \
  "$BUILD_DIR/res_stage/res.zip"

# 6. Compile Android Java patches + d8 + DexPatcher + DexVerifier
echo "[STEP] Compiling Java patches..."
javac --release 11 -cp "$ANDROID_JAR" -d "$BUILD_DIR/cls_patch" $(find "$ROOT_DIR/android/src" -name '*.java')
"$BT_DIR/d8" --min-api 27 --lib "$ANDROID_JAR" --output "$BUILD_DIR/dex_patch" $(find "$BUILD_DIR/cls_patch" -name '*.class')

echo "[STEP] Compiling and running DexPatcher & DexVerifier..."
javac --release 11 -cp "$DEXLIB_CP" -d "$BUILD_DIR/cls_tools" \
  "$ROOT_DIR/tools/DexPatcher.java" "$ROOT_DIR/tools/DexVerifier.java"

unzip -p "$BASE_APK" classes.dex > "$BUILD_DIR/orig.dex"
java -cp "$BUILD_DIR/cls_tools:$DEXLIB_CP" DexPatcher \
  "$BUILD_DIR/orig.dex" "$BUILD_DIR/dex_patch/classes.dex" "$BUILD_DIR/classes_patched.dex"
java -cp "$BUILD_DIR/cls_tools:$DEXLIB_CP" DexVerifier \
  "$BUILD_DIR/orig.dex" "$BUILD_DIR/classes_patched.dex"
"$BT_DIR/d8" --min-api 27 --lib "$ANDROID_JAR" --output "$BUILD_DIR/d8_check" "$BUILD_DIR/classes_patched.dex"

# 7. Assemble unaligned APK preserving STORED entries for .so & resources.arsc
echo "[STEP] Repacking APK with patched DEX, Manifest, resources, and UI..."
UNALIGNED_APK="$BUILD_DIR/unaligned.apk"
ALIGNED_APK="$BUILD_DIR/aligned.apk"

python3 - "$BASE_APK" "$BUILD_DIR/res_stage/res_linked.apk" "$BUILD_DIR/classes_patched.dex" "$ROOT_DIR/ui/index.html" "$UNALIGNED_APK" "$ROOT_DIR" << 'PY'
import sys, zipfile, os, json

base_apk, res_apk, patched_dex, ui_html, out_apk, root_dir = sys.argv[1:7]
manifest_path = os.path.join(root_dir, "soundpacks.json")
with open(manifest_path, "rb") as f:
    manifest_bytes = f.read()
CORE_ASSETS = set("assets/" + a for a in json.loads(manifest_bytes)["coreAssetFiles"])
thumb_dir = os.path.join(root_dir, "android", "soundimages")
SKIP_PREFIXES = ("META-INF/", "res/")
SKIP_EXACT = {"AndroidManifest.xml", "resources.arsc", "classes.dex", "assets/ui/index.html"}

with zipfile.ZipFile(out_apk, "w", allowZip64=True) as zout:
    # 1. Copy compiled manifest, resources.arsc (STORED), and res/* from aapt2 output
    with zipfile.ZipFile(res_apk, "r") as zres:
        for info in zres.infolist():
            data = zres.read(info.filename)
            zi = zipfile.ZipInfo(info.filename)
            zi.date_time = (2026, 1, 1, 0, 0, 0)
            if info.filename == "resources.arsc":
                zi.compress_type = zipfile.ZIP_STORED
            else:
                zi.compress_type = info.compress_type
            zout.writestr(zi, data)

    # 2. Write patched classes.dex
    zi_dex = zipfile.ZipInfo("classes.dex")
    zi_dex.date_time = (2026, 1, 1, 0, 0, 0)
    zi_dex.compress_type = zipfile.ZIP_DEFLATED
    with open(patched_dex, "rb") as f:
        zout.writestr(zi_dex, f.read())

    # 3. Write updated UI index.html
    zi_ui = zipfile.ZipInfo("assets/ui/index.html")
    zi_ui.date_time = (2026, 1, 1, 0, 0, 0)
    zi_ui.compress_type = zipfile.ZIP_DEFLATED
    with open(ui_html, "rb") as f:
        zout.writestr(zi_ui, f.read())

    # 4. Copy remaining untouched assets, native libs, and kotlin metadata from base_template
    with zipfile.ZipFile(base_apk, "r") as zbase:
        for info in zbase.infolist():
            fn = info.filename
            if fn in SKIP_EXACT or fn.startswith(SKIP_PREFIXES):
                continue
            # Lite build: only the essential timbres and optimized thumbnails ship in the APK
            if fn.startswith("assets/soundbank/") and fn not in CORE_ASSETS:
                continue
            if fn.startswith("assets/soundimages/"):
                continue
            data = zbase.read(fn)
            zi = zipfile.ZipInfo(fn)
            zi.date_time = info.date_time
            if fn.endswith(".so"):
                zi.compress_type = zipfile.ZIP_STORED
            else:
                zi.compress_type = info.compress_type
            zout.writestr(zi, data)

    # 5. Sound pack manifest and optimized thumbnails
    zi_m = zipfile.ZipInfo("assets/soundpacks.json")
    zi_m.date_time = (2026, 1, 1, 0, 0, 0)
    zi_m.compress_type = zipfile.ZIP_DEFLATED
    zout.writestr(zi_m, manifest_bytes)
    for name in sorted(os.listdir(thumb_dir)):
        if not name.lower().endswith(".png"):
            continue
        zi_t = zipfile.ZipInfo("assets/soundimages/" + name)
        zi_t.date_time = (2026, 1, 1, 0, 0, 0)
        zi_t.compress_type = zipfile.ZIP_STORED
        with open(os.path.join(thumb_dir, name), "rb") as f:
            zout.writestr(zi_t, f.read())

print("[OK] Packed unaligned APK:", out_apk)
PY

# 8. Align with 16 KB page alignment (Android 15/16)
echo "[STEP] Running zipalign -f -P 16 4..."
"$BT_DIR/zipalign" -f -P 16 4 "$UNALIGNED_APK" "$ALIGNED_APK"

# 9. Sign APK (v1 + v2 + v3)
KEYSTORE_PATH="${KEYSTORE_PATH:-}"
KEYSTORE_PASS="${KEYSTORE_PASS:-}"
KEY_ALIAS="${KEY_ALIAS:-}"
KEY_PASS="${KEY_PASS:-$KEYSTORE_PASS}"

if [[ -z "$KEYSTORE_PATH" ]]; then
  echo "[WARN] KEYSTORE_PATH not set — generating temporary signing key (configure ANDROID_KEYSTORE_B64 secret for in-place updates!)."
  KEYSTORE_PATH="$BUILD_DIR/temp_debug.jks"
  KEYSTORE_PASS="android123"
  KEY_ALIAS="p61x_ci"
  KEY_PASS="android123"
  if [[ ! -f "$KEYSTORE_PATH" ]]; then
    keytool -genkeypair -v -keystore "$KEYSTORE_PATH" -storepass "$KEYSTORE_PASS" \
      -alias "$KEY_ALIAS" -keypass "$KEY_PASS" -keyalg RSA -keysize 2048 -validity 10000 \
      -dname "CN=P61x Console CI,O=P61x,C=BR" >/dev/null 2>&1
  fi
fi

mkdir -p "$(dirname "$OUT_APK")"
echo "[STEP] Signing APK (v1+v2+v3) -> $OUT_APK..."
"$BT_DIR/apksigner" sign \
  --ks "$KEYSTORE_PATH" \
  --ks-pass "pass:${KEYSTORE_PASS}" \
  --ks-key-alias "$KEY_ALIAS" \
  --key-pass "pass:${KEY_PASS}" \
  --v1-signing-enabled true \
  --v2-signing-enabled true \
  --v3-signing-enabled true \
  --out "$OUT_APK" \
  "$ALIGNED_APK"

# 10. Full APK verification
echo "[STEP] Running verify_apk.py..."
python3 "$ROOT_DIR/tools/verify_apk.py" "$OUT_APK" "$BT_DIR" "$VERSION_JSON"
