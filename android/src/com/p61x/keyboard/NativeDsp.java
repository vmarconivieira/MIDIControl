package com.p61x.keyboard;

public final class NativeDsp {
    private NativeDsp() {}

    public static native void nativeSetZoneParams(
            long ptr, int zone, int transpose, int keyLow, int keyHigh,
            int velLow, int velHigh, int sustain, int enabled);

    public static native double nativeStartStream(long ptr, double sampleRate, int blockSize);

    public static native void nativeStopStream(long ptr);
}
