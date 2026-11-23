package com.p61x.keyboard;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.io.File;
import org.json.JSONArray;
import org.json.JSONObject;

public final class P61xAudioHelper {
    private static final String TAG = "P61xAudio";

    // Verified source duration of all 5 bundled pad_layer_0..4.ogg assets: 44100 Hz, 882000 frames (20.000s)
    public static final int PAD_SRC_SAMPLE_RATE = 44100;
    public static final int PAD_SRC_FRAMES = 882000;

    // Non-destructive Global Transpose state (-12 .. +12 semitones)
    private static final Object TR_LOCK = new Object();
    private static final int[] BASE_TRANSPOSE = new int[] { 0, 0, 0, 0 };
    private static final int[] BASE_KEY_LOW = new int[] { 21, 21, 21, 21 };
    private static final int[] BASE_KEY_HIGH = new int[] { 108, 108, 108, 108 };
    private static final int[] BASE_VEL_LOW = new int[] { 0, 0, 0, 0 };
    private static final int[] BASE_VEL_HIGH = new int[] { 127, 127, 127, 127 };
    private static final int[] BASE_SUSTAIN = new int[] { 1, 1, 1, 1 };
    private static final int[] BASE_ENABLED = new int[] { 1, 1, 1, 1 };
    private static final boolean[] ZONE_SEEN = new boolean[] { false, false, false, false };
    private static volatile long cachedDspPtr = 0L;
    private static volatile int globalTranspose = 0;

    // Audio route monitoring (USB Hub + Audio Interface hotplug)
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());
    private static volatile Context appCtx;
    private static volatile P61xEngine activeEngine;
    private static volatile String lastRouteType = "";
    private static AudioDeviceCallback deviceCallback;
    private static AudioFocusRequest activeFocusRequest;
    private static Runnable pendingRouteRestart;

    private P61xAudioHelper() {}

    // =========================================================================
    // 1. NON-DESTRUCTIVE GLOBAL TRANSPOSE & PITCH BEND SAFETY
    // =========================================================================
    public static void setZoneParamsWithGlobalTranspose(
            long ptr, int zone, int zoneTranspose, int keyLow, int keyHigh,
            int velLow, int velHigh, int sustain, int enabled) {
        int eff = zoneTranspose;
        if (zone >= 0 && zone < 4) {
            synchronized (TR_LOCK) {
                cachedDspPtr = ptr;
                BASE_TRANSPOSE[zone] = zoneTranspose;
                BASE_KEY_LOW[zone] = keyLow;
                BASE_KEY_HIGH[zone] = keyHigh;
                BASE_VEL_LOW[zone] = velLow;
                BASE_VEL_HIGH[zone] = velHigh;
                BASE_SUSTAIN[zone] = sustain;
                BASE_ENABLED[zone] = enabled;
                ZONE_SEEN[zone] = true;
                eff = clamp(zoneTranspose + globalTranspose, -36, 36);
            }
        }
        if (ptr != 0L) {
            NativeDsp.nativeSetZoneParams(ptr, zone, eff, keyLow, keyHigh, velLow, velHigh, sustain, enabled);
        }
    }

    public static int setGlobalTranspose(int semitones) {
        int clamped = clamp(semitones, -12, 12);
        long ptr;
        int[] tr = new int[4];
        int[] kl = new int[4];
        int[] kh = new int[4];
        int[] vl = new int[4];
        int[] vh = new int[4];
        int[] sus = new int[4];
        int[] en = new int[4];
        boolean[] seen = new boolean[4];

        synchronized (TR_LOCK) {
            globalTranspose = clamped;
            ptr = cachedDspPtr;
            for (int z = 0; z < 4; z++) {
                tr[z] = clamp(BASE_TRANSPOSE[z] + clamped, -36, 36);
                kl[z] = BASE_KEY_LOW[z];
                kh[z] = BASE_KEY_HIGH[z];
                vl[z] = BASE_VEL_LOW[z];
                vh[z] = BASE_VEL_HIGH[z];
                sus[z] = BASE_SUSTAIN[z];
                en[z] = BASE_ENABLED[z];
                seen[z] = ZONE_SEEN[z];
            }
        }

        if (ptr != 0L) {
            for (int z = 0; z < 4; z++) {
                if (seen[z]) {
                    try {
                        NativeDsp.nativeSetZoneParams(ptr, z, tr[z], kl[z], kh[z], vl[z], vh[z], sus[z], en[z]);
                    } catch (Throwable t) {
                        Log.w(TAG, "Re-applying transpose on zone " + z + " failed", t);
                    }
                }
            }
            if (clamped == 0) {
                resetPitchBendCenter();
            }
        }
        return clamped;
    }

    public static int getGlobalTranspose() {
        return globalTranspose;
    }

    public static void resetPitchBendCenter() {
        long ptr = cachedDspPtr;
        if (ptr == 0L) {
            P61xEngine eng = activeEngine;
            if (eng != null) {
                try {
                    ptr = eng.getDspPtrForPatch();
                } catch (Throwable ignored) {
                }
            }
        }
        if (ptr != 0L) {
            try {
                NativeDsp.nativePitchBend(ptr, 8192);
            } catch (Throwable t) {
                Log.w(TAG, "resetPitchBendCenter failed", t);
            }
        }
    }

    // =========================================================================
    // 2. CONTINUOUS PAD SAMPLE-RATE & PITCH INTEGRITY
    // =========================================================================
    public static int expectedPadFramesForRate(int targetSampleRate) {
        int sr = targetSampleRate > 8000 ? targetSampleRate : 48000;
        return (int) Math.round((double) PAD_SRC_FRAMES * (double) sr / (double) PAD_SRC_SAMPLE_RATE);
    }

    public static void purgeLegacyPadCache(File padPcmDir) {
        if (padPcmDir == null || !padPcmDir.isDirectory()) return;
        try {
            File[] files = padPcmDir.listFiles();
            if (files == null) return;
            for (File f : files) {
                if (f == null || !f.isFile()) continue;
                String name = f.getName();
                if (name.startsWith("pad_layer_") && name.endsWith(".f32") && !name.endsWith("_v2.f32")) {
                    if (f.delete()) {
                        Log.i(TAG, "Removed legacy pad PCM cache: " + name);
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "purgeLegacyPadCache failed", t);
        }
    }

    public static float[] ensurePadFrameCount(float[] pcm, int decodedFrames, int expectedFrames, int layerIdx, int targetSampleRate) {
        if (pcm == null || pcm.length < 32 || expectedFrames <= 16) return pcm;
        int actualFrames = Math.min(decodedFrames, pcm.length / 2);
        if (actualFrames <= 16) return pcm;

        // Already matches expected 20.000s frame count within ~0.4% (<7 cents)
        if (Math.abs(actualFrames - expectedFrames) <= 4000) {
            return pcm;
        }

        // Guard against Android MediaCodec returning un-resampled 44.1kHz frames (882000)
        // for a 48kHz engine (960000), which causes a +1.47 semitone (C -> ~D) pitch error.
        if (actualFrames < 750000 || actualFrames > 2000000) {
            return pcm;
        }

        Log.w(TAG, "Pad layer " + layerIdx + " sample-rate mismatch detected (got " + actualFrames
                + " frames, expected " + expectedFrames + " @" + targetSampleRate + "Hz) — resampling for exact pitch");

        float[] out = new float[expectedFrames * 2];
        double scale = (double) (actualFrames - 1) / (double) Math.max(1, expectedFrames - 1);
        int lastSrc = actualFrames - 1;
        for (int i = 0; i < expectedFrames; i++) {
            double pos = (double) i * scale;
            int idx0 = (int) pos;
            int idx1 = Math.min(lastSrc, idx0 + 1);
            float frac = (float) (pos - (double) idx0);
            int s0 = idx0 * 2;
            int s1 = idx1 * 2;
            float l0 = pcm[s0];
            float r0 = pcm[s0 + 1];
            out[i * 2] = l0 + (pcm[s1] - l0) * frac;
            out[i * 2 + 1] = r0 + (pcm[s1 + 1] - r0) * frac;
        }
        return out;
    }

    // =========================================================================
    // 3. CLEAN AUDIO ROUTE MONITORING (USB HUB + AUDIO INTERFACE HOTPLUG)
    // =========================================================================
    public static void startMonitoring(Context ctx, P61xEngine engine) {
        if (ctx != null) appCtx = ctx.getApplicationContext();
        if (engine != null) {
            activeEngine = engine;
            try {
                long ptr = engine.getDspPtrForPatch();
                if (ptr != 0L) {
                    cachedDspPtr = ptr;
                }
            } catch (Throwable ignored) {
            }
        }
        resetPitchBendCenter();
        if (appCtx == null) return;

        AudioManager am = (AudioManager) appCtx.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return;

        lastRouteType = detectPrimaryRouteType(am);
        requestMediaAudioFocus(am);

        if (deviceCallback == null) {
            deviceCallback = new AudioDeviceCallback() {
                @Override
                public void onAudioDevicesAdded(AudioDeviceInfo[] addedDevices) {
                    handleAudioRouteChanged("added");
                }

                @Override
                public void onAudioDevicesRemoved(AudioDeviceInfo[] removedDevices) {
                    handleAudioRouteChanged("removed");
                }
            };
            try {
                am.registerAudioDeviceCallback(deviceCallback, MAIN_HANDLER);
            } catch (Throwable t) {
                Log.w(TAG, "registerAudioDeviceCallback failed", t);
            }
        }

        notifyRouteStatus();
    }

    public static void stopMonitoring() {
        if (pendingRouteRestart != null) {
            MAIN_HANDLER.removeCallbacks(pendingRouteRestart);
            pendingRouteRestart = null;
        }
        Context c = appCtx;
        if (c != null) {
            AudioManager am = (AudioManager) c.getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                if (deviceCallback != null) {
                    try {
                        am.unregisterAudioDeviceCallback(deviceCallback);
                    } catch (Throwable ignored) {
                    }
                    deviceCallback = null;
                }
                if (activeFocusRequest != null && Build.VERSION.SDK_INT >= 26) {
                    try {
                        am.abandonAudioFocusRequest(activeFocusRequest);
                    } catch (Throwable ignored) {
                    }
                    activeFocusRequest = null;
                }
            }
        }
        activeEngine = null;
    }

    private static void handleAudioRouteChanged(final String reason) {
        if (pendingRouteRestart != null) {
            MAIN_HANDLER.removeCallbacks(pendingRouteRestart);
        }
        pendingRouteRestart = new Runnable() {
            @Override
            public void run() {
                pendingRouteRestart = null;
                Context c = appCtx;
                P61xEngine eng = activeEngine;
                if (c == null) return;
                AudioManager am = (AudioManager) c.getSystemService(Context.AUDIO_SERVICE);
                if (am == null) return;

                String newRoute = detectPrimaryRouteType(am);
                boolean routeChanged = !newRoute.equals(lastRouteType);
                lastRouteType = newRoute;

                if (eng != null && (routeChanged || "removed".equals(reason))) {
                    int targetBlock = clamp(eng.getHwBlockSizeForPatch(), 128, 1024);
                    try {
                        eng.applyAudioBlockSizeForPatch(targetBlock);
                    } catch (Throwable t) {
                        Log.w(TAG, "Audio stream restart on route change failed", t);
                    }
                }
                notifyRouteStatus();
            }
        };
        MAIN_HANDLER.postDelayed(pendingRouteRestart, 420L);
    }

    public static String selectAudioConfig(P61xEngine engine, String deviceId, int blockSize) {
        if (engine == null) {
            return "{\"ok\":false}";
        }
        activeEngine = engine;
        int safeBlock = clamp(blockSize, 128, 1024);
        String res = engine.applyAudioBlockSizeForPatch(safeBlock);
        notifyRouteStatus();
        return res;
    }

    public static void notifyRouteStatus() {
        try {
            JSONObject ev = new JSONObject(getAudioRouteStatusJson(appCtx, activeEngine));
            ev.put("event", "audio_route_status");
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable ignored) {
        }
    }

    public static String getAudioRouteStatusJson(Context ctx, P61xEngine engine) {
        if (ctx != null && appCtx == null) appCtx = ctx.getApplicationContext();
        Context c = ctx != null ? ctx.getApplicationContext() : appCtx;
        P61xEngine eng = engine != null ? engine : activeEngine;

        JSONObject obj = new JSONObject();
        try {
            String routeType = "speaker";
            String routeLabel = "Alto-falante Interno";
            String deviceName = "Alto-falante do Aparelho";
            JSONArray devicesArr = new JSONArray();

            AudioManager am = c != null ? (AudioManager) c.getSystemService(Context.AUDIO_SERVICE) : null;
            if (am != null) {
                AudioDeviceInfo[] outs = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
                int bestPriority = -1;
                if (outs != null) {
                    for (AudioDeviceInfo d : outs) {
                        if (d == null) continue;
                        int type = d.getType();
                        int prio = priorityForOutputType(type);
                        if (prio < 0) continue;

                        String cat = categoryForOutputType(type);
                        String pName = d.getProductName() != null ? d.getProductName().toString().trim() : "";
                        if (pName.isEmpty()) pName = labelForCategory(cat);

                        JSONObject item = new JSONObject();
                        item.put("id", String.valueOf(d.getId()));
                        item.put("name", pName);
                        item.put("category", cat);
                        devicesArr.put(item);

                        if (prio > bestPriority) {
                            bestPriority = prio;
                            routeType = cat;
                            routeLabel = labelForCategory(cat);
                            deviceName = pName;
                        }
                    }
                }
            }

            boolean isUsb = "usb".equals(routeType);
            int blockSize = eng != null ? eng.getHwBlockSizeForPatch() : 256;
            int sampleRate = eng != null ? eng.getHwSampleRateForPatch() : 48000;
            double latMs = eng != null ? eng.getLatencyMsForPatch() : 0.0;

            obj.put("ok", true);
            obj.put("routeType", routeType);
            obj.put("routeLabel", routeLabel);
            obj.put("deviceName", deviceName);
            obj.put("isUsbAudio", isUsb);
            obj.put("blockSize", blockSize);
            obj.put("sampleRate", sampleRate);
            obj.put("latencyMs", Math.round(latMs * 10.0) / 10.0);
            obj.put("globalTranspose", globalTranspose);
            obj.put("devices", devicesArr);
        } catch (Throwable t) {
            Log.w(TAG, "getAudioRouteStatusJson failed", t);
        }
        return obj.toString();
    }

    private static void requestMediaAudioFocus(AudioManager am) {
        if (am == null || Build.VERSION.SDK_INT < 26) return;
        try {
            AudioAttributes attrs = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build();
            AudioFocusRequest req = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                    .setAudioAttributes(attrs)
                    .setWillPauseWhenDucked(false)
                    .build();
            activeFocusRequest = req;
            am.requestAudioFocus(req);
        } catch (Throwable t) {
            Log.w(TAG, "requestAudioFocus failed", t);
        }
    }

    private static String detectPrimaryRouteType(AudioManager am) {
        if (am == null) return "speaker";
        try {
            AudioDeviceInfo[] outs = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
            int best = -1;
            String bestCat = "speaker";
            if (outs != null) {
                for (AudioDeviceInfo d : outs) {
                    if (d == null) continue;
                    int p = priorityForOutputType(d.getType());
                    if (p > best) {
                        best = p;
                        bestCat = categoryForOutputType(d.getType());
                    }
                }
            }
            return bestCat;
        } catch (Throwable ignored) {
            return "speaker";
        }
    }

    private static int priorityForOutputType(int type) {
        if (type == AudioDeviceInfo.TYPE_USB_DEVICE
                || type == AudioDeviceInfo.TYPE_USB_HEADSET
                || type == AudioDeviceInfo.TYPE_USB_ACCESSORY) {
            return 50;
        }
        if (type == AudioDeviceInfo.TYPE_WIRED_HEADSET
                || type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES
                || type == AudioDeviceInfo.TYPE_LINE_ANALOG
                || type == AudioDeviceInfo.TYPE_LINE_DIGITAL) {
            return 40;
        }
        if (type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER) {
            return 10;
        }
        return -1;
    }

    private static String categoryForOutputType(int type) {
        if (type == AudioDeviceInfo.TYPE_USB_DEVICE
                || type == AudioDeviceInfo.TYPE_USB_HEADSET
                || type == AudioDeviceInfo.TYPE_USB_ACCESSORY) {
            return "usb";
        }
        if (type == AudioDeviceInfo.TYPE_WIRED_HEADSET
                || type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES
                || type == AudioDeviceInfo.TYPE_LINE_ANALOG
                || type == AudioDeviceInfo.TYPE_LINE_DIGITAL) {
            return "wired";
        }
        return "speaker";
    }

    private static String labelForCategory(String cat) {
        if ("usb".equals(cat)) return "USB Áudio / Placa de Áudio";
        if ("wired".equals(cat)) return "Saída Cabeada / Linha";
        return "Alto-falante Interno";
    }

    private static int clamp(int val, int min, int max) {
        return Math.max(min, Math.min(max, val));
    }
}
