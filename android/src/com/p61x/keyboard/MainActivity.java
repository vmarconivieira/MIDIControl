package com.p61x.keyboard;

import android.app.Activity;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.LinearLayout;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private P61xEngine engine;
    private LinearLayout splashOverlay;
    private WebView webView;

    private void enterImmersiveMode() {
        P61xPatch.enterImmersiveModeSafe(this);
    }

    private void lambda$onCreate$0() {
        P61xPatch.registerActivity(this);
        try {
            P61xEngine eng = this.engine;
            if (eng != null) {
                eng.initialize();
                P61xPatch.markEngineReady(eng);
            }
            if (!isFinishing() && !isDestroyed()) {
                runOnUiThread(new MainActivity$$ExternalSyntheticLambda8(this));
            }
        } catch (Throwable t) {
            P61xPatch.handleInitError(this, this.splashOverlay, t);
        }
    }

    void dispatchPatchEvent(JSONObject ev) {
        P61xPatch.dispatchEventOnWebView(this, this.webView, ev);
    }

    @Override
    protected void onResume() {
        super.onResume();
        P61xPatch.registerActivity(this);
        P61xPatch.enterImmersiveModeSafe(this);
        P61xPatch.safeOnResume(this.engine);
    }

    @Override
    protected void onDestroy() {
        P61xPatch.clearActivity(this);
        P61xEngine eng = this.engine;
        P61xPatch.clearEngineReady(eng);
        if (eng != null) {
            try {
                eng.shutdown();
            } catch (Throwable ignored) {
            }
        }
        super.onDestroy();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            P61xPatch.enterImmersiveModeSafe(this);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        BleMidiHelper.onPermissionsResult(this, requestCode, permissions, grantResults);
    }

    public final class MobileBridge {
        @JavascriptInterface
        public String getAppVersion() {
            return P61xUpdater.getAppVersionJson(MainActivity.this);
        }

        @JavascriptInterface
        public void checkGithubUpdate() {
            P61xUpdater.checkGithubUpdateAsync(MainActivity.this);
        }

        @JavascriptInterface
        public void downloadAndInstallUpdate(String apkUrl) {
            P61xUpdater.downloadAndInstallUpdateAsync(MainActivity.this, apkUrl);
        }

        @JavascriptInterface
        public void openExternalUrl(String url) {
            P61xUpdater.openExternalUrl(MainActivity.this, url);
        }

        @JavascriptInterface
        public String rescanMidiDevices() {
            return UsbMidiEnhanced.rescanActiveJson();
        }

        @JavascriptInterface
        public int setGlobalTranspose(int semitones) {
            return P61xAudioHelper.setGlobalTranspose(semitones);
        }

        @JavascriptInterface
        public int getGlobalTranspose() {
            return P61xAudioHelper.getGlobalTranspose();
        }

        @JavascriptInterface
        public void startBleMidiScan(boolean includeAllBle) {
            BleMidiHelper.startScan(MainActivity.this, includeAllBle);
        }

        @JavascriptInterface
        public void stopBleMidiScan() {
            BleMidiHelper.stopScan();
        }

        @JavascriptInterface
        public void connectBleMidiDevice(String address) {
            BleMidiHelper.connectDevice(MainActivity.this, address);
        }

        @JavascriptInterface
        public void disconnectBleMidiDevice(String address) {
            BleMidiHelper.disconnectDevice(address);
        }

        @JavascriptInterface
        public String getAudioRouteStatus() {
            return P61xAudioHelper.getAudioRouteStatusJson(MainActivity.this, P61xPatch.getReadyEngine());
        }

        @JavascriptInterface
        public String applyAudioMode(String mode, int customBlockSize) {
            return P61xAudioHelper.applyAudioMode(MainActivity.this, P61xPatch.getReadyEngine(), mode, customBlockSize);
        }

        @JavascriptInterface
        public void openBluetoothSettings() {
            P61xAudioHelper.openBluetoothSettings(MainActivity.this);
        }
    }
}
