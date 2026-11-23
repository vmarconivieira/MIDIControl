package com.p61x.keyboard;

import android.app.Activity;
import android.os.Build;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.WebView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.lang.ref.WeakReference;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public final class P61xPatch {
    private static final String TAG = "P61xConsole";
    private static volatile P61xEngine readyEngine;
    private static volatile WeakReference<MainActivity> activeActivityRef = new WeakReference<>(null);
    private static final ExecutorService RESUME_EXEC = Executors.newSingleThreadExecutor();

    private P61xPatch() {}

    public static void registerActivity(MainActivity activity) {
        if (activity != null) {
            activeActivityRef = new WeakReference<>(activity);
        }
    }

    public static void clearActivity(MainActivity activity) {
        MainActivity cur = activeActivityRef.get();
        if (cur == activity) {
            activeActivityRef = new WeakReference<>(null);
        }
    }

    public static MainActivity getActiveActivity() {
        MainActivity act = activeActivityRef.get();
        if (act == null || act.isFinishing() || act.isDestroyed()) {
            return null;
        }
        return act;
    }

    public static void dispatchEventOnWebView(final Activity activity, final WebView webView, final JSONObject ev) {
        if (activity == null || webView == null || ev == null) {
            return;
        }
        if (activity.isFinishing() || activity.isDestroyed()) {
            return;
        }
        final String js = "window.onAndroidNativeEvent && window.onAndroidNativeEvent(" + JSONObject.quote(ev.toString()) + ");";
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (!activity.isFinishing() && !activity.isDestroyed()) {
                        webView.evaluateJavascript(js, null);
                    }
                } catch (Throwable t) {
                    Log.w(TAG, "dispatchEventOnWebView failed", t);
                }
            }
        });
    }

    public static void postEventToActiveUi(JSONObject ev) {
        if (ev == null) return;
        MainActivity act = getActiveActivity();
        if (act != null) {
            try {
                act.dispatchPatchEvent(ev);
            } catch (Throwable t) {
                Log.w(TAG, "postEventToActiveUi failed", t);
            }
        }
    }

    public static void onPageFinished(MainActivity activity) {
        registerActivity(activity);
        try {
            UsbMidiEnhanced.onUiPageReady();
        } catch (Throwable t) {
            Log.w(TAG, "onPageFinished MIDI sync failed", t);
        }
        try {
            P61xAudioHelper.notifyRouteStatus();
        } catch (Throwable ignored) {
        }
    }

    public static void enterImmersiveModeSafe(Activity activity) {
        if (activity == null) {
            return;
        }
        try {
            Window window = activity.getWindow();
            if (window == null) {
                return;
            }
            View decor = window.getDecorView();
            if (decor == null) {
                return;
            }
            if (Build.VERSION.SDK_INT >= 30) {
                window.setDecorFitsSystemWindows(false);
                WindowInsetsController controller = window.getInsetsController();
                if (controller != null) {
                    controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                    controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                }
            } else {
                decor.setSystemUiVisibility(5894);
            }
        } catch (Throwable t) {
            Log.w(TAG, "enterImmersiveModeSafe failed", t);
        }
    }

    public static P61xEngine getReadyEngine() {
        return readyEngine;
    }

    public static void markEngineReady(P61xEngine engine) {
        readyEngine = engine;
        if (engine != null) {
            try {
                engine.fixPadSemitonesForPatch();
            } catch (Throwable ignored) {
            }
        }
        try {
            MainActivity act = getActiveActivity();
            if (act != null) {
                P61xAudioHelper.startMonitoring(act, engine);
            }
        } catch (Throwable ignored) {
        }
        try {
            UsbMidiEnhanced.onUiPageReady();
        } catch (Throwable ignored) {
        }
    }

    public static void clearEngineReady(P61xEngine engine) {
        if (readyEngine == engine) {
            readyEngine = null;
        }
        try {
            BleMidiHelper.stopScan();
        } catch (Throwable ignored) {
        }
        try {
            P61xAudioHelper.stopMonitoring();
        } catch (Throwable ignored) {
        }
    }

    public static void safeOnResume(final P61xEngine engine) {
        try {
            UsbMidiEnhanced.rescanQuietly("resume");
        } catch (Throwable ignored) {
        }
        try {
            P61xAudioHelper.notifyRouteStatus();
        } catch (Throwable ignored) {
        }
        if (engine == null || readyEngine != engine) {
            return;
        }
        RESUME_EXEC.execute(new Runnable() {
            @Override
            public void run() {
                if (readyEngine != engine) {
                    return;
                }
                try {
                    engine.onResume();
                } catch (Throwable t) {
                    Log.w(TAG, "engine.onResume failed", t);
                }
            }
        });
    }

    public static void handleInitError(final Activity activity, final LinearLayout splashOverlay, final Throwable error) {
        Log.e(TAG, "P61xEngine initialization failed", error);
        if (activity == null || splashOverlay == null) {
            return;
        }
        if (activity.isFinishing() || activity.isDestroyed()) {
            return;
        }
        String detail = error != null ? error.getClass().getSimpleName() : "Erro desconhecido";
        if (error != null && error.getMessage() != null && !error.getMessage().isEmpty()) {
            detail = detail + ": " + error.getMessage();
        }
        final String msg = "Falha ao inicializar áudio DSP:\n" + detail;
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    if (activity.isFinishing() || activity.isDestroyed()) {
                        return;
                    }
                    int count = splashOverlay.getChildCount();
                    for (int i = 0; i < count; i++) {
                        View child = splashOverlay.getChildAt(i);
                        if (i == 1 && child instanceof TextView) {
                            TextView tv = (TextView) child;
                            tv.setText(msg);
                            tv.setTextColor(0xFFFF6B6B);
                        } else if (!(child instanceof TextView)) {
                            child.setVisibility(View.GONE);
                        }
                    }
                } catch (Throwable ignored) {
                }
            }
        });
    }
}
