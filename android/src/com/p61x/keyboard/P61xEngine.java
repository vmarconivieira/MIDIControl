package com.p61x.keyboard;

import android.util.Log;

public final class P61xEngine {
    private volatile long dspPtr;
    private volatile int hwBlockSize;
    private volatile int hwSampleRate;
    private volatile double latencyMs;

    public void initialize() {}
    public void onResume() {}
    public void shutdown() {}

    private void loadAllContinuousPads$orig() {}

    private void loadAllContinuousPads() {
        try {
            loadAllContinuousPads$orig();
        } catch (Throwable t) {
            Log.w("P61xConsole", "loadAllContinuousPads failed", t);
        }
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
        int clamped = Math.max(64, Math.min(1024, blockSize));
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
