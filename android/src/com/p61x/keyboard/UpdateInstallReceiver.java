package com.p61x.keyboard;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.util.Log;

public final class UpdateInstallReceiver extends BroadcastReceiver {
    private static final String TAG = "P61xUpdater";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) {
            return;
        }
        // The new version has just replaced the app: reopen it if the update was started in-app.
        if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction())) {
            if (P61xUpdater.consumePendingRelaunch(context)) {
                P61xUpdater.launchMainActivity(context);
            }
            return;
        }
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);

        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirmIntent = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirmIntent != null) {
                try {
                    confirmIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    context.startActivity(confirmIntent);
                    P61xUpdater.emitProgress("prompting", 100, 0, 0, "Confirme a instalação.");
                } catch (Throwable t) {
                    Log.e(TAG, "Failed to start confirmation activity", t);
                    P61xUpdater.emitProgress("error", 0, 0, 0, "Não foi possível abrir o instalador: " + t.getMessage());
                }
            } else {
                P61xUpdater.emitProgress("error", 0, 0, 0, "O instalador não retornou confirmação.");
            }
        } else if (status == PackageInstaller.STATUS_SUCCESS) {
            P61xUpdater.emitProgress("installed", 100, 0, 0, "Atualização instalada.");
        } else {
            P61xUpdater.clearPendingRelaunch(context);
            emitFailure(status, msg);
        }
    }

    static void emitFailure(int status, String msg) {
        if (status == PackageInstaller.STATUS_FAILURE_ABORTED) {
            P61xUpdater.emitProgress("cancelled", 0, 0, 0, "Instalação cancelada.");
        } else if (status == PackageInstaller.STATUS_FAILURE_CONFLICT) {
            P61xUpdater.emitProgress("error", 0, 0, 0,
                    "Conflito de assinatura com o APK instalado. Instale manualmente pelo GitHub.");
        } else if (status == PackageInstaller.STATUS_FAILURE_STORAGE) {
            P61xUpdater.emitProgress("error", 0, 0, 0, "Espaço insuficiente para instalar.");
        } else {
            String detail = (msg != null && !msg.isEmpty()) ? msg : ("Código " + status);
            Log.w(TAG, "PackageInstaller failed: status=" + status + " msg=" + detail);
            P61xUpdater.emitProgress("error", 0, 0, 0, "Falha na instalação: " + detail);
        }
    }
}
