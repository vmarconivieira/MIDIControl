package com.p61x.keyboard;

import android.app.Activity;
import android.app.ActivityOptions;
import android.app.PendingIntent;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;

public final class P61xUpdater {
    private static final String TAG = "P61xUpdater";
    public static final String REPO = "vmarconivieira/MIDIControl";
    private static final String GITHUB_API_LATEST = "https://api.github.com/repos/" + REPO + "/releases/latest";
    private static final String GITHUB_RAW_VERSION = "https://raw.githubusercontent.com/" + REPO + "/main/version.json";
    private static final String GITHUB_RELEASES_WEB = "https://github.com/" + REPO + "/releases";
    private static final String USER_AGENT = "P61xConsole-Android";

    private static final ExecutorService CHECK_EXEC = Executors.newSingleThreadExecutor();
    private static final ExecutorService DOWNLOAD_EXEC = Executors.newSingleThreadExecutor();
    private static final AtomicBoolean DOWNLOADING = new AtomicBoolean(false);

    private P61xUpdater() {}

    public static String getAppVersionJson(Context ctx) {
        JSONObject obj = new JSONObject();
        try {
            obj.put("repo", REPO);
            obj.put("releasesUrl", GITHUB_RELEASES_WEB);
            obj.put("packageName", ctx != null ? ctx.getPackageName() : "com.p61x.keyboard");
            if (ctx != null) {
                PackageInfo pi = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
                obj.put("versionName", pi.versionName != null ? pi.versionName : "1.0.0");
                long code = Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
                obj.put("versionCode", code);
            } else {
                obj.put("versionName", "1.1.0");
                obj.put("versionCode", 2);
            }
        } catch (Throwable t) {
            Log.w(TAG, "getAppVersionJson failed", t);
        }
        return obj.toString();
    }

    private static String normalizeVersion(String v) {
        if (v == null) return "";
        String s = v.trim();
        while (s.startsWith("v") || s.startsWith("V")) {
            s = s.substring(1).trim();
        }
        return s;
    }

    public static void checkGithubUpdateAsync(final Activity activity) {
        if (activity == null) return;
        final Context appCtx = activity.getApplicationContext();
        CHECK_EXEC.execute(new Runnable() {
            @Override
            public void run() {
                String localName = "1.1.0";
                long localCode = 2;
                try {
                    PackageInfo pi = appCtx.getPackageManager().getPackageInfo(appCtx.getPackageName(), 0);
                    if (pi.versionName != null) localName = pi.versionName;
                    localCode = Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
                } catch (Throwable ignored) {
                }

                JSONObject releaseJson = null;
                JSONObject rawVersionJson = null;
                String lastError = null;

                try {
                    String body = httpGetString(GITHUB_API_LATEST, "application/vnd.github+json");
                    if (body != null && !body.isEmpty()) {
                        releaseJson = new JSONObject(body);
                    }
                } catch (Throwable t) {
                    lastError = t.getMessage();
                    Log.w(TAG, "GitHub releases/latest fetch failed: " + lastError);
                }

                try {
                    String body = httpGetString(GITHUB_RAW_VERSION, "application/json");
                    if (body != null && !body.isEmpty()) {
                        rawVersionJson = new JSONObject(body);
                    }
                } catch (Throwable t) {
                    if (lastError == null) lastError = t.getMessage();
                    Log.w(TAG, "GitHub raw version.json fetch failed: " + t.getMessage());
                }

                JSONObject ev = new JSONObject();
                try {
                    ev.put("event", "update_status");
                    ev.put("repo", REPO);
                    ev.put("installedVersionName", localName);
                    ev.put("installedVersionCode", localCode);

                    if (releaseJson == null && rawVersionJson == null) {
                        ev.put("ok", false);
                        ev.put("hasUpdate", false);
                        ev.put("releaseUrl", GITHUB_RELEASES_WEB);
                        ev.put("error", "Não foi possível consultar o GitHub. Verifique sua conexão com a internet.");
                        P61xPatch.postEventToActiveUi(ev);
                        return;
                    }

                    String remoteName = "";
                    long remoteCode = -1;
                    String remoteTag = "";
                    String apkUrl = "";
                    long apkSize = 0;
                    String releaseUrl = GITHUB_RELEASES_WEB;
                    String notesText = "";
                    boolean hasApkAsset = false;

                    if (rawVersionJson != null) {
                        remoteName = normalizeVersion(rawVersionJson.optString("versionName", ""));
                        remoteCode = rawVersionJson.optLong("versionCode", -1);
                        remoteTag = rawVersionJson.optString("tag", "");
                        apkUrl = rawVersionJson.optString("apkUrl", "");
                        String rUrl = rawVersionJson.optString("releaseUrl", "");
                        if (!rUrl.isEmpty()) releaseUrl = rUrl;
                        JSONArray notesArr = rawVersionJson.optJSONArray("notes");
                        if (notesArr != null) {
                            StringBuilder sb = new StringBuilder();
                            for (int i = 0; i < notesArr.length(); i++) {
                                if (i > 0) sb.append('\n');
                                sb.append("• ").append(notesArr.optString(i, ""));
                            }
                            notesText = sb.toString();
                        } else {
                            notesText = rawVersionJson.optString("notes", "");
                        }
                    }

                    if (releaseJson != null) {
                        String tag = releaseJson.optString("tag_name", "");
                        if (!tag.isEmpty()) {
                            remoteTag = tag;
                            String relVer = normalizeVersion(tag);
                            if (!relVer.isEmpty()) {
                                // If release tag differs from version.json, prefer release tag as published version
                                if (!relVer.equalsIgnoreCase(remoteName)) {
                                    remoteCode = -1;
                                }
                                remoteName = relVer;
                            }
                        }
                        String htmlUrl = releaseJson.optString("html_url", "");
                        if (!htmlUrl.isEmpty()) releaseUrl = htmlUrl;
                        String relBody = releaseJson.optString("body", "").trim();
                        if (!relBody.isEmpty()) notesText = relBody;

                        JSONArray assets = releaseJson.optJSONArray("assets");
                        if (assets != null) {
                            for (int i = 0; i < assets.length(); i++) {
                                JSONObject a = assets.optJSONObject(i);
                                if (a == null) continue;
                                String name = a.optString("name", "");
                                String dl = a.optString("browser_download_url", "");
                                if (name.toLowerCase().endsWith(".apk") && dl.startsWith("https://")) {
                                    apkUrl = dl;
                                    apkSize = a.optLong("size", 0);
                                    hasApkAsset = true;
                                    break;
                                }
                            }
                        }
                    }

                    String normLocal = normalizeVersion(localName);
                    String normRemote = normalizeVersion(remoteName);
                    boolean differentName = !normRemote.isEmpty() && !normLocal.equalsIgnoreCase(normRemote);
                    boolean differentCode = remoteCode > 0 && remoteCode != localCode;
                    boolean hasUpdate = differentName || differentCode;

                    ev.put("ok", true);
                    ev.put("hasUpdate", hasUpdate);
                    ev.put("hasApkAsset", hasApkAsset || (!apkUrl.isEmpty() && apkUrl.startsWith("https://")));
                    ev.put("remoteVersionName", !normRemote.isEmpty() ? normRemote : localName);
                    ev.put("remoteVersionCode", remoteCode);
                    ev.put("remoteTag", !remoteTag.isEmpty() ? remoteTag : ("v" + normRemote));
                    ev.put("apkUrl", apkUrl);
                    ev.put("apkSizeBytes", apkSize);
                    ev.put("releaseUrl", releaseUrl);
                    ev.put("notes", notesText);
                    ev.put("checkedAt", System.currentTimeMillis());
                } catch (Throwable t) {
                    Log.w(TAG, "Error building update_status", t);
                    try {
                        ev.put("ok", false);
                        ev.put("error", "Erro ao processar resposta do GitHub.");
                    } catch (Throwable ignored) {
                    }
                }
                P61xPatch.postEventToActiveUi(ev);
            }
        });
    }

    // ---- Relaunch after self-update -------------------------------------------------
    private static final String PREFS = "p61x_updater_prefs";
    private static final String KEY_PENDING = "pending_relaunch_ts";
    private static final long RELAUNCH_WINDOW_MS = 10L * 60L * 1000L;

    public static void markPendingRelaunch(Context ctx) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putLong(KEY_PENDING, System.currentTimeMillis()).commit();
    }

    public static void clearPendingRelaunch(Context ctx) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_PENDING).commit();
    }

    /** True once per update: the flag is consumed so the app is never launched twice. */
    public static synchronized boolean consumePendingRelaunch(Context ctx) {
        SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long ts = sp.getLong(KEY_PENDING, 0L);
        if (ts == 0L) return false;
        sp.edit().remove(KEY_PENDING).commit();
        return System.currentTimeMillis() - ts < RELAUNCH_WINDOW_MS;
    }

    public static void launchMainActivity(Context ctx) {
        try {
            Intent i = new Intent(ctx, MainActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            ctx.startActivity(i);
        } catch (Throwable t) {
            Log.w(TAG, "Unable to relaunch app", t);
        }
    }

    public static void downloadAndInstallUpdateAsync(final Activity activity, final String apkUrl) {
        if (activity == null) return;
        if (apkUrl == null || !apkUrl.startsWith("https://")) {
            emitProgress("error", 0, 0, 0, "URL de download inválida.");
            return;
        }
        final Context appCtx = activity.getApplicationContext();

        // Check Android 8+ unknown app sources permission before downloading
        if (Build.VERSION.SDK_INT >= 26) {
            try {
                if (!appCtx.getPackageManager().canRequestPackageInstalls()) {
                    emitProgress("permission_required", 0, 0, 0,
                            "Permita 'Instalar apps desconhecidos' para o P61x Console e depois toque em 'Baixar e Atualizar' novamente.");
                    activity.runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            try {
                                Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                        Uri.parse("package:" + appCtx.getPackageName()));
                                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                                activity.startActivity(i);
                            } catch (Throwable t) {
                                Log.w(TAG, "Unable to open unknown sources settings", t);
                            }
                        }
                    });
                    return;
                }
            } catch (Throwable t) {
                Log.w(TAG, "canRequestPackageInstalls check failed", t);
            }
        }

        if (!DOWNLOADING.compareAndSet(false, true)) {
            emitProgress("downloading", 0, 0, 0, "Um download de atualização já está em andamento...");
            return;
        }

        DOWNLOAD_EXEC.execute(new Runnable() {
            @Override
            public void run() {
                PackageInstaller.Session session = null;
                HttpURLConnection conn = null;
                try {
                    emitProgress("downloading", 0, 0, 0, "Conectando ao GitHub Releases...");
                    conn = openConnectionFollowRedirects(apkUrl, "*/*", 20000, 60000);
                    int code = conn.getResponseCode();
                    if (code != 200) {
                        throw new Exception("GitHub retornou HTTP " + code + " (verifique se a release já terminou de publicar o APK).");
                    }

                    long totalBytes = Build.VERSION.SDK_INT >= 24 ? conn.getContentLengthLong() : conn.getContentLength();
                    PackageInstaller installer = appCtx.getPackageManager().getPackageInstaller();
                    PackageInstaller.SessionParams params =
                            new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                    params.setAppPackageName(appCtx.getPackageName());
                    if (Build.VERSION.SDK_INT >= 34) {
                        try {
                            params.setRequestUpdateOwnership(true);
                        } catch (Throwable ignored) {
                        }
                    }
                    if (totalBytes > 0) {
                        params.setSize(totalBytes);
                    }
                    int sessionId = installer.createSession(params);
                    session = installer.openSession(sessionId);

                    InputStream in = conn.getInputStream();
                    OutputStream out = session.openWrite("p61x_update.apk", 0, totalBytes > 0 ? totalBytes : -1);
                    byte[] buf = new byte[65536];
                    long downloaded = 0;
                    long lastEmit = 0;
                    int n;
                    while ((n = in.read(buf)) >= 0) {
                        if (n > 0) {
                            out.write(buf, 0, n);
                            downloaded += n;
                            long now = System.currentTimeMillis();
                            if (now - lastEmit >= 250) {
                                lastEmit = now;
                                int pct = totalBytes > 0 ? (int) Math.min(99, (downloaded * 100L) / totalBytes) : 0;
                                emitProgress("downloading", pct, downloaded, totalBytes,
                                        totalBytes > 0
                                                ? String.format("Baixando APK: %.1f / %.1f MB (%d%%)",
                                                    downloaded / 1048576.0, totalBytes / 1048576.0, pct)
                                                : String.format("Baixando APK: %.1f MB...", downloaded / 1048576.0));
                            }
                        }
                    }
                    session.fsync(out);
                    out.close();
                    in.close();

                    emitProgress("committing", 100, downloaded, totalBytes > 0 ? totalBytes : downloaded,
                            "Preparando instalador do Android...");

                    Intent activityIntent = new Intent(appCtx, UpdateInstallActivity.class);
                    activityIntent.setAction("com.p61x.keyboard.ACTION_INSTALL_COMMIT");
                    activityIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
                    if (Build.VERSION.SDK_INT >= 31) {
                        piFlags |= PendingIntent.FLAG_MUTABLE;
                    }
                    PendingIntent pendingIntent = null;
                    if (Build.VERSION.SDK_INT >= 34) {
                        try {
                            Bundle balOptions = ActivityOptions.makeBasic()
                                    .setPendingIntentCreatorBackgroundActivityStartMode(
                                            ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED)
                                    .toBundle();
                            pendingIntent = PendingIntent.getActivity(
                                    appCtx, sessionId, activityIntent, piFlags, balOptions);
                        } catch (Throwable balErr) {
                            Log.w(TAG, "PendingIntent creator BAL options fallback", balErr);
                        }
                    }
                    if (pendingIntent == null) {
                        pendingIntent = PendingIntent.getActivity(
                                appCtx, sessionId, activityIntent, piFlags);
                    }
                    markPendingRelaunch(appCtx);
                    session.commit(pendingIntent.getIntentSender());
                    session.close();
                    session = null;
                } catch (Throwable t) {
                    Log.e(TAG, "Update download/install failed", t);
                    if (session != null) {
                        try {
                            session.abandon();
                        } catch (Throwable ignored) {
                        }
                        try {
                            session.close();
                        } catch (Throwable ignored) {
                        }
                    }
                    String msg = t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName();
                    clearPendingRelaunch(appCtx);
                    emitProgress("error", 0, 0, 0, "Falha ao baixar atualização: " + msg);
                } finally {
                    if (conn != null) {
                        try {
                            conn.disconnect();
                        } catch (Throwable ignored) {
                        }
                    }
                    DOWNLOADING.set(false);
                }
            }
        });
    }

    public static void openExternalUrl(final Activity activity, final String url) {
        if (activity == null || url == null || !url.startsWith("https://")) return;
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    activity.startActivity(i);
                } catch (Throwable t) {
                    Log.w(TAG, "openExternalUrl failed", t);
                }
            }
        });
    }

    public static void emitProgress(String status, int pct, long downloadedBytes, long totalBytes, String message) {
        try {
            JSONObject ev = new JSONObject();
            ev.put("event", "update_progress");
            ev.put("status", status);
            ev.put("pct", pct);
            ev.put("downloadedMb", Math.round((downloadedBytes / 1048576.0) * 10.0) / 10.0);
            ev.put("totalMb", Math.round((totalBytes / 1048576.0) * 10.0) / 10.0);
            ev.put("message", message != null ? message : "");
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable ignored) {
        }
    }

    private static String httpGetString(String urlStr, String accept) throws Exception {
        HttpURLConnection conn = null;
        try {
            conn = openConnectionFollowRedirects(urlStr, accept, 10000, 12000);
            int code = conn.getResponseCode();
            if (code != 200) {
                throw new Exception("HTTP " + code);
            }
            BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line).append('\n');
            }
            br.close();
            return sb.toString();
        } finally {
            if (conn != null) {
                try {
                    conn.disconnect();
                } catch (Throwable ignored) {
                }
            }
        }
    }

    private static HttpURLConnection openConnectionFollowRedirects(
            String initialUrl, String accept, int connectTimeoutMs, int readTimeoutMs) throws Exception {
        String currentUrl = initialUrl;
        for (int hops = 0; hops < 7; hops++) {
            HttpURLConnection conn = (HttpURLConnection) new URL(currentUrl).openConnection();
            conn.setInstanceFollowRedirects(false);
            conn.setConnectTimeout(connectTimeoutMs);
            conn.setReadTimeout(readTimeoutMs);
            conn.setRequestProperty("User-Agent", USER_AGENT);
            if (accept != null && !accept.isEmpty()) {
                conn.setRequestProperty("Accept", accept);
            }
            int code = conn.getResponseCode();
            if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                String loc = conn.getHeaderField("Location");
                conn.disconnect();
                if (loc == null || loc.isEmpty()) {
                    throw new Exception("Redirect sem Location (HTTP " + code + ")");
                }
                URL next = new URL(new URL(currentUrl), loc);
                currentUrl = next.toString();
                continue;
            }
            return conn;
        }
        throw new Exception("Muitos redirecionamentos HTTP");
    }
}
