package com.p61x.keyboard;

import android.content.Context;
import android.util.Log;
import java.io.File;

public final class P61xEngine {
    private static final int[] KEY_SEMITONES = new int[12];

    private final Context ctx = null;
    private final File padPcmDir = null;
    private volatile long dspPtr;
    private volatile int hwBlockSize;
    private volatile int hwSampleRate;
    private volatile double latencyMs;
    private volatile boolean padReady;

    public void initialize() {}
    public void onResume() {}
    public void shutdown() {}

    private void syncPadToDsp() {}
    private float[] readCachedFloatPcm(File f) { return null; }
    private void writeCachedFloatPcm(File f, float[] data) {}
    private void loadAllContinuousPads$orig() {}

    void fixPadSemitonesForPatch() {
        int[] ks = KEY_SEMITONES;
        if (ks != null && ks.length == 12) {
            // Align Android pad semitone offsets with Windows P61x reference
            // (C=0 -> 1.0x native pitch instead of -12 / 0.5x sub-octave shift)
            int[] fixed = new int[] { 0, 1, 2, 3, 4, 5, 6, -5, -4, -3, -2, -1 };
            System.arraycopy(fixed, 0, ks, 0, 12);
        }
    }

    private void loadAllContinuousPads() {
        try {
            fixPadSemitonesForPatch();
            P61xAudioHelper.purgeLegacyPadCache(this.padPcmDir);

            int sr = this.hwSampleRate > 8000 ? this.hwSampleRate : 48000;
            int expectedFrames = P61xAudioHelper.expectedPadFramesForRate(sr);
            boolean anyLoaded = false;

            for (int i = 0; i < 5; i++) {
                long ptr = this.dspPtr;
                if (ptr == 0L) return;

                File cacheFile = new File(this.padPcmDir, "pad_layer_" + i + "_" + sr + "_v2.f32");
                float[] pcm = readCachedFloatPcm(cacheFile);
                if (pcm != null) {
                    int cachedFrames = pcm.length / 2;
                    if (Math.abs(cachedFrames - expectedFrames) > 4000) {
                        pcm = null;
                    }
                }

                if (pcm == null) {
                    AudioDecoder.DecodedPcm dec = AudioDecoder.decodeAssetAudio(
                            this.ctx, "pad_loops/pad_layer_" + i + ".ogg", sr, false);
                    if (dec != null && dec.interleavedLr != null && dec.frames > 16) {
                        pcm = P61xAudioHelper.ensurePadFrameCount(
                                dec.interleavedLr, dec.frames, expectedFrames, i, sr);
                        if (pcm != null && pcm.length >= 32) {
                            writeCachedFloatPcm(cacheFile, pcm);
                        }
                    }
                }

                ptr = this.dspPtr;
                if (pcm != null && pcm.length >= 32 && ptr != 0L) {
                    NativeDsp.nativeSetPadLayer(ptr, i, pcm, pcm.length / 2);
                    anyLoaded = true;
                }
            }

            this.padReady = anyLoaded;
            syncPadToDsp();
        } catch (Throwable t) {
            Log.w("P61xConsole", "Validated loadAllContinuousPads failed, falling back", t);
            try {
                loadAllContinuousPads$orig();
            } catch (Throwable t2) {
                Log.w("P61xConsole", "loadAllContinuousPads$orig fallback failed", t2);
            }
        }
    }

    long getDspPtrForPatch() {
        return this.dspPtr;
    }

    int getHwBlockSizeForPatch() {
        return this.hwBlockSize;
    }

    int getHwSampleRateForPatch() {
        return this.hwSampleRate;
    }

    double getLatencyMsForPatch() {
        return this.latencyMs;
    }

    String applyAudioBlockSizeForPatch(int blockSize) {
        int clamped = Math.max(128, Math.min(1024, blockSize));
        this.hwBlockSize = clamped;
        long ptr = this.dspPtr;
        if (ptr != 0L) {
            NativeDsp.nativeStopStream(ptr);
            double lat = NativeDsp.nativeStartStream(ptr, (double) this.hwSampleRate, this.hwBlockSize);
            if (lat > 0.0) {
                this.latencyMs = lat;
            }
        }
        return "{\"ok\":true,\"block_size\":" + this.hwBlockSize + ",\"latency_ms\":" + this.latencyMs + "}";
    }

    public String selectAudioConfig(String deviceId, int blockSize) {
        return P61xAudioHelper.selectAudioConfig(this, deviceId, blockSize);
    }
}
