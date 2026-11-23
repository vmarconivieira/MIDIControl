package com.p61x.keyboard;

import android.util.Log;

public final class P61xEngine {
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
}
