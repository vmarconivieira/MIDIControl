package com.p61x.keyboard;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Bundle;
import android.util.Log;

/**
 * Invisible trampoline that receives PackageInstaller status. Being an Activity
 * (instead of a broadcast) lets the app be relaunched after the update replaces it.
 */
public final class UpdateInstallActivity extends Activity {
    private static final String TAG = "P61xUpdater";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handle(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handle(intent);
    }

    private void handle(Intent intent) {
        try {
            if (intent != null) {
                int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
                String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                    Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                    if (confirm != null) {
                        startActivity(confirm);
                        P61xUpdater.emitProgress("prompting", 100, 0, 0, "Confirme a instalação.");
                    } else {
                        P61xUpdater.clearPendingRelaunch(this);
                        P61xUpdater.emitProgress("error", 0, 0, 0, "O instalador não retornou confirmação.");
                    }
                } else if (status == PackageInstaller.STATUS_SUCCESS) {
                    P61xUpdater.clearPendingRelaunch(this);
                    P61xUpdater.launchMainActivity(this);
                    P61xUpdater.emitProgress("installed", 100, 0, 0, "Atualização instalada.");
                } else {
                    P61xUpdater.clearPendingRelaunch(this);
                    UpdateInstallReceiver.emitFailure(status, msg);
                }
            }
        } catch (Throwable t) {
            Log.e(TAG, "UpdateInstallActivity failed", t);
            P61xUpdater.clearPendingRelaunch(this);
        }
        finish();
        overridePendingTransition(0, 0);
    }
}
