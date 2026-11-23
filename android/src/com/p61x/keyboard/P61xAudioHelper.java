package com.p61x.keyboard;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;

public final class P61xAudioHelper {
    private static final String TAG = "P61xAudio";

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

    // Audio route monitoring & BT/USB latency mode
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());
    private static volatile Context appCtx;
    private static volatile P61xEngine activeEngine;
    private static volatile String activeMode = "auto";
    private static volatile String lastRouteType = "";
    private static AudioDeviceCallback deviceCallback;
    private static AudioFocusRequest activeFocusRequest;
    private static Runnable pendingRouteRestart;

    private P61xAudioHelper() {}

    // =========================================================================
    // 1. NON-DESTRUCTIVE GLOBAL TRANSPOSE
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
        }
        return clamped;
    }

    public static int getGlobalTranspose() {
        return globalTranspose;
    }

    // =========================================================================
    // 2. AUDIO ROUTE MONITORING (USB HUB DAC / BLUETOOTH A2DP & LE AUDIO)
    // =========================================================================
    public static void startMonitoring(Context ctx, P61xEngine engine) {
        if (ctx != null) appCtx = ctx.getApplicationContext();
        if (engine != null) activeEngine = engine;
        if (appCtx == null) return;

        AudioManager am = (AudioManager) appCtx.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return;

        lastRouteType = detectPrimaryRouteType(am);
        requestOptimalAudioFocus(am, true);

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
                    int targetBlock = eng.getHwBlockSizeForPatch();
                    if ("usb".equals(newRoute) && ("auto".equals(activeMode) || "usb_pro".equals(activeMode))) {
                        targetBlock = 128;
                        requestOptimalAudioFocus(am, true);
                    } else if (("bt_a2dp".equals(newRoute) || "ble_audio".equals(newRoute)) && "bt_low_latency".equals(activeMode)) {
                        targetBlock = 96;
                        requestOptimalAudioFocus(am, true);
                        trySetLowLatencyHint(am, true);
                    }
                    try {
                        eng.applyAudioBlockSizeForPatch(targetBlock);
                    } catch (Throwable t) {
                        Log.w(TAG, "Auto audio stream restart on route change failed", t);
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
        int safeBlock = clamp(blockSize, 64, 1024);
        String res = engine.applyAudioBlockSizeForPatch(safeBlock);
        notifyRouteStatus();
        return res;
    }

    public static String applyAudioMode(Context ctx, P61xEngine engine, String mode, int customBlockSize) {
        if (ctx != null) appCtx = ctx.getApplicationContext();
        if (engine != null) activeEngine = engine;
        String m = (mode == null || mode.trim().isEmpty()) ? "auto" : mode.trim().toLowerCase();
        activeMode = m;

        Context c = appCtx;
        AudioManager am = c != null ? (AudioManager) c.getSystemService(Context.AUDIO_SERVICE) : null;

        int targetBlock = customBlockSize >= 64 ? clamp(customBlockSize, 64, 1024) : 128;
        boolean lowLatencyHint = true;

        if ("bt_low_latency".equals(m)) {
            targetBlock = customBlockSize >= 64 ? clamp(customBlockSize, 64, 256) : 96;
            lowLatencyHint = true;
            if (am != null) {
                try {
                    am.setMode(AudioManager.MODE_NORMAL);
                    am.setSpeakerphoneOn(false);
                } catch (Throwable ignored) {
                }
                requestOptimalAudioFocus(am, true);
                trySetLowLatencyHint(am, true);
            }
        } else if ("usb_pro".equals(m)) {
            targetBlock = customBlockSize >= 64 ? clamp(customBlockSize, 64, 512) : 128;
            lowLatencyHint = true;
            if (am != null) {
                try {
                    am.setMode(AudioManager.MODE_NORMAL);
                } catch (Throwable ignored) {
                }
                requestOptimalAudioFocus(am, true);
                trySetLowLatencyHint(am, true);
            }
        } else if ("safe".equals(m)) {
            targetBlock = 256;
            lowLatencyHint = false;
            if (am != null) {
                requestOptimalAudioFocus(am, false);
                trySetLowLatencyHint(am, false);
            }
        } else {
            if (am != null) {
                requestOptimalAudioFocus(am, lowLatencyHint);
            }
        }

        P61xEngine eng = activeEngine;
        if (eng != null) {
            try {
                eng.applyAudioBlockSizeForPatch(targetBlock);
            } catch (Throwable t) {
                Log.w(TAG, "applyAudioMode restart failed", t);
            }
        }

        String statusJson = getAudioRouteStatusJson(c, eng);
        notifyRouteStatus();
        return statusJson;
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

            boolean isBt = "bt_a2dp".equals(routeType) || "ble_audio".equals(routeType);
            boolean isUsb = "usb".equals(routeType);
            int blockSize = eng != null ? eng.getHwBlockSizeForPatch() : 256;
            int sampleRate = eng != null ? eng.getHwSampleRateForPatch() : 48000;
            double latMs = eng != null ? eng.getLatencyMsForPatch() : 0.0;

            obj.put("ok", true);
            obj.put("routeType", routeType);
            obj.put("routeLabel", routeLabel);
            obj.put("deviceName", deviceName);
            obj.put("isBluetooth", isBt);
            obj.put("isBleAudio", "ble_audio".equals(routeType));
            obj.put("isUsbAudio", isUsb);
            obj.put("mode", activeMode);
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

    public static void openBluetoothSettings(final Activity activity) {
        if (activity == null) return;
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    Intent i = new Intent(Settings.ACTION_BLUETOOTH_SETTINGS);
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    activity.startActivity(i);
                } catch (Throwable t) {
                    Log.w(TAG, "openBluetoothSettings failed", t);
                }
            }
        });
    }

    private static void requestOptimalAudioFocus(AudioManager am, boolean gameLowLatency) {
        if (am == null || Build.VERSION.SDK_INT < 26) return;
        try {
            AudioAttributes attrs = new AudioAttributes.Builder()
                    .setUsage(gameLowLatency ? AudioAttributes.USAGE_GAME : AudioAttributes.USAGE_MEDIA)
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

    private static void trySetLowLatencyHint(AudioManager am, boolean enable) {
        if (am == null) return;
        try {
            am.setParameters(enable ? "audio_low_latency=1" : "audio_low_latency=0");
        } catch (Throwable ignored) {
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
        if (Build.VERSION.SDK_INT >= 31) {
            if (type == AudioDeviceInfo.TYPE_BLE_HEADSET
                    || type == AudioDeviceInfo.TYPE_BLE_SPEAKER) {
                return 35;
            }
        }
        if (type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP) {
            return 30;
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
        if (Build.VERSION.SDK_INT >= 31
                && (type == AudioDeviceInfo.TYPE_BLE_HEADSET || type == AudioDeviceInfo.TYPE_BLE_SPEAKER)) {
            return "ble_audio";
        }
        if (type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP) {
            return "bt_a2dp";
        }
        return "speaker";
    }

    private static String labelForCategory(String cat) {
        if ("usb".equals(cat)) return "USB Áudio / Placa (Baixa Latência)";
        if ("wired".equals(cat)) return "Saída Cabeada / Linha";
        if ("ble_audio".equals(cat)) return "Bluetooth LE Audio (LC3)";
        if ("bt_a2dp".equals(cat)) return "Bluetooth Estéreo (A2DP)";
        return "Alto-falante Interno";
    }

    private static int clamp(int val, int min, int max) {
        return Math.max(min, Math.min(max, val));
    }
}
