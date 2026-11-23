package com.p61x.keyboard;

import android.content.Context;

public final class AudioDecoder {
    public static final class DecodedPcm {
        public final float[] interleavedLr;
        public final int frames;

        public DecodedPcm(float[] interleavedLr, int frames) {
            this.interleavedLr = interleavedLr;
            this.frames = frames;
        }
    }

    private AudioDecoder() {}

    public static DecodedPcm decodeAssetAudio(Context ctx, String assetPath, int targetSampleRate, boolean normalize) {
        return null;
    }
}
