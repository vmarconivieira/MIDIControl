#!/usr/bin/env bash
# Builds libstagerig_dsp.so (arm64-v8a) from native/stagerig_dsp.c + native/stagerig_jni.c with the Android NDK.
# Usage: ANDROID_NDK_HOME=/path/to/ndk ./native/build_android.sh <dir-with-libfluidsynth.so> <output.so>
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
FLUID_DIR="${1:?dir containing libfluidsynth.so (extracted from the base APK lib/arm64-v8a)}"
OUT="${2:?output .so path}"
[[ -d "$NDK" ]] || { echo "ANDROID_NDK_HOME not set / not found" >&2; exit 1; }
CC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android27-clang"
"$CC" -O3 -fPIC -shared -std=gnu11 -fno-math-errno -fno-trapping-math -fvisibility=hidden \
  -ffunction-sections -fdata-sections -Wall -Wno-unused-function -Wno-unused-variable \
  -DNDEBUG -D__STDC_FORMAT_MACROS \
  "$HERE/stagerig_dsp.c" "$HERE/stagerig_jni.c" \
  -o "$OUT" \
  -L"$FLUID_DIR" -lfluidsynth -laaudio -llog -lm \
  -Wl,--gc-sections -Wl,-s -Wl,-soname,libstagerig_dsp.so \
  -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384 -Wl,--no-undefined
echo "built $OUT"
