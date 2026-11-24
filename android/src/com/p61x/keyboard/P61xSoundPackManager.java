package com.p61x.keyboard;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Optional timbre packs. The APK ships only the essential pack; additional packs are
 * downloaded either from the "soundpacks-v1" GitHub release (.zip) or directly (.sf2)
 * into files/sf2_decoded/, which Android preserves across app updates.
 */
public final class P61xSoundPackManager {
    private static final String TAG = "P61xSoundPacks";
    private static final String USER_AGENT = "P61xConsole-Android";
    private static final String PREFS = "p61x_soundpacks_prefs";
    private static final String KEY_MIGRATED_WORSHIP_NORD_PAD = "migrated_worship_nord_pad_v1";
    private static final ExecutorService EXEC = Executors.newSingleThreadExecutor();
    private static final Set<String> ACTIVE = ConcurrentHashMap.newKeySet();
    private static volatile JSONObject manifest;

    private P61xSoundPackManager() {}

    /**
     * Ensures that if the user already has a persisted config/standalone_presets.json from
     * an older version, Preset #01 (Worship Immersion) Zona 4 is updated once to Nord Red Ambient Pad.
     */
    public static void migrateSavedPresetsIfNeeded(Context ctx) {
        if (ctx == null) return;
        try {
            SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            if (sp.getBoolean(KEY_MIGRATED_WORSHIP_NORD_PAD, false)) return;
            sp.edit().putBoolean(KEY_MIGRATED_WORSHIP_NORD_PAD, true).commit();

            File cfgFile = new File(new File(ctx.getFilesDir(), "config"), "standalone_presets.json");
            if (!cfgFile.isFile()) return;

            InputStream in = new FileInputStream(cfgFile);
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();

            JSONObject banks = new JSONObject(new String(bo.toByteArray(), StandardCharsets.UTF_8));
            JSONArray liveRig = banks.optJSONArray("0 - Live Rig");
            if (liveRig == null || liveRig.length() == 0) return;

            boolean changed = false;
            for (int i = 0; i < liveRig.length(); i++) {
                JSONObject p = liveRig.optJSONObject(i);
                if (p != null && "Worship Immersion".equals(p.optString("name"))) {
                    JSONArray libs = p.optJSONArray("libs");
                    JSONArray models = p.optJSONArray("zone_models");
                    JSONArray names = p.optJSONArray("zone_names");
                    if (libs != null && libs.length() >= 4) {
                        libs.put(3, "Nord Red Ambient Pad.sf2/Red Ambient Pad");
                        changed = true;
                    }
                    if (models != null && models.length() >= 4) {
                        models.put(3, "Nord Red Ambient Pad");
                        changed = true;
                    }
                    if (names != null && names.length() >= 4) {
                        names.put(3, "Nord Ambient Pad");
                        changed = true;
                    }
                }
            }

            if (changed) {
                File tmp = new File(cfgFile.getParentFile(), "standalone_presets.json.tmp");
                OutputStream out = new FileOutputStream(tmp);
                out.write(banks.toString().getBytes(StandardCharsets.UTF_8));
                out.flush();
                out.close();
                if (cfgFile.exists()) cfgFile.delete();
                tmp.renameTo(cfgFile);
            }
        } catch (Throwable t) {
            Log.w(TAG, "migrateSavedPresetsIfNeeded failed", t);
        }
    }

    private static synchronized JSONObject loadManifest(Context ctx) {
        if (manifest != null) return manifest;
        try {
            InputStream in = ctx.getAssets().open("soundpacks.json");
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();
            manifest = new JSONObject(bo.toString("UTF-8"));
        } catch (Throwable t) {
            Log.w(TAG, "soundpacks.json unavailable", t);
            manifest = new JSONObject();
        }
        return manifest;
    }

    private static File sf2Dir(Context ctx) {
        File d = new File(ctx.getFilesDir(), "sf2_decoded");
        if (!d.isDirectory()) d.mkdirs();
        return d;
    }

    private static boolean packInstalled(Context ctx, JSONObject pack) {
        if (pack.optBoolean("bundled", false)) return true;
        JSONArray files = pack.optJSONArray("sf2Files");
        if (files == null || files.length() == 0) return false;
        File dir = sf2Dir(ctx);
        for (int i = 0; i < files.length(); i++) {
            File f = new File(dir, files.optString(i));
            if (!f.isFile() || f.length() <= 1024) return false;
        }
        return true;
    }

    public static String getStatusJson(Context ctx) {
        JSONObject out = new JSONObject();
        try {
            JSONObject m = loadManifest(ctx);
            JSONArray packs = m.optJSONArray("packs");
            JSONArray outPacks = new JSONArray();
            JSONArray libIds = new JSONArray();
            int total = 0;
            int installed = 0;
            long installedBytes = 0;
            File dir = sf2Dir(ctx);
            if (packs != null) {
                for (int i = 0; i < packs.length(); i++) {
                    JSONObject p = packs.getJSONObject(i);
                    boolean inst = packInstalled(ctx, p);
                    int count = p.optInt("timbreCount", 0);
                    total += count;
                    JSONObject o = new JSONObject();
                    o.put("id", p.optString("id"));
                    o.put("name", p.optString("name"));
                    o.put("description", p.optString("description"));
                    o.put("bundled", p.optBoolean("bundled", false));
                    o.put("installed", inst);
                    o.put("downloading", ACTIVE.contains(p.optString("id")));
                    o.put("timbreCount", count);
                    o.put("sizeBytes", p.optLong("sizeBytes", 0));
                    o.put("timbreIds", p.optJSONArray("timbreIds"));
                    outPacks.put(o);
                    if (inst) {
                        installed += count;
                        JSONArray ids = p.optJSONArray("timbreIds");
                        if (ids != null) {
                            for (int k = 0; k < ids.length(); k++) libIds.put(ids.optString(k));
                        }
                        JSONArray files = p.optJSONArray("sf2Files");
                        if (files != null && !p.optBoolean("bundled", false)) {
                            for (int k = 0; k < files.length(); k++) {
                                installedBytes += new File(dir, files.optString(k)).length();
                            }
                        }
                    }
                }
            }
            out.put("ok", true);
            out.put("totalTimbres", total);
            out.put("installedTimbres", installed);
            out.put("installedBytes", installedBytes);
            out.put("packs", outPacks);
            out.put("installedLibIds", libIds);
        } catch (Throwable t) {
            Log.w(TAG, "getStatusJson failed", t);
            try {
                out.put("ok", false);
            } catch (Throwable ignored) {
            }
        }
        return out.toString();
    }

    private static JSONObject findPack(Context ctx, String packId) {
        JSONArray packs = loadManifest(ctx).optJSONArray("packs");
        if (packs == null || packId == null) return null;
        for (int i = 0; i < packs.length(); i++) {
            JSONObject p = packs.optJSONObject(i);
            if (p != null && packId.equals(p.optString("id"))) return p;
        }
        return null;
    }

    private static void emit(String packId, String status, int pct, long done, long total, String msg) {
        try {
            JSONObject ev = new JSONObject();
            ev.put("event", "soundpack_progress");
            ev.put("packId", packId);
            ev.put("status", status);
            ev.put("pct", pct);
            ev.put("downloadedMb", Math.round((done / 1048576.0) * 10.0) / 10.0);
            ev.put("totalMb", Math.round((total / 1048576.0) * 10.0) / 10.0);
            ev.put("message", msg != null ? msg : "");
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable ignored) {
        }
    }

    private static void emitStatus(Context ctx) {
        try {
            JSONObject ev = new JSONObject(getStatusJson(ctx));
            ev.put("event", "soundpack_status");
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable ignored) {
        }
    }

    public static void downloadPackAsync(Context ctx, final String packId) {
        final Context app = ctx.getApplicationContext();
        final JSONObject pack = findPack(app, packId);
        if (pack == null || pack.optBoolean("bundled", false)) {
            emit(packId, "error", 0, 0, 0, "Pacote inválido.");
            return;
        }
        if (!ACTIVE.add(packId)) return;
        emit(packId, "downloading", 0, 0, 0, "Conectando...");
        EXEC.execute(new Runnable() {
            @Override
            public void run() {
                File zipTmp = new File(app.getCacheDir(), packId + ".zip.part");
                try {
                    JSONArray directFiles = pack.optJSONArray("directFiles");
                    String url = pack.optString("downloadUrl", "");
                    if (directFiles != null && directFiles.length() > 0 && url.isEmpty()) {
                        downloadDirectFiles(app, packId, pack, directFiles);
                        return;
                    }
                    if (!url.startsWith("https://")) throw new Exception("URL inválida");
                    long expected = pack.optLong("sizeBytes", 0);
                    String expectedSha = pack.optString("sha256", "");
                    HttpURLConnection conn = open(url);
                    if (conn.getResponseCode() != 200) {
                        throw new Exception("HTTP " + conn.getResponseCode());
                    }
                    long total = conn.getContentLengthLong();
                    if (total <= 0) total = expected;
                    MessageDigest md = MessageDigest.getInstance("SHA-256");
                    InputStream in = new BufferedInputStream(conn.getInputStream(), 65536);
                    OutputStream out = new FileOutputStream(zipTmp);
                    byte[] buf = new byte[65536];
                    long done = 0;
                    long last = 0;
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                        md.update(buf, 0, n);
                        done += n;
                        long now = System.currentTimeMillis();
                        if (now - last >= 200) {
                            last = now;
                            int pct = total > 0 ? (int) Math.min(99, done * 100L / total) : 0;
                            emit(packId, "downloading", pct, done, total, "Baixando");
                        }
                    }
                    out.close();
                    in.close();
                    conn.disconnect();

                    if (!expectedSha.isEmpty()) {
                        StringBuilder sb = new StringBuilder();
                        for (byte b : md.digest()) sb.append(String.format("%02x", b));
                        if (!sb.toString().equalsIgnoreCase(expectedSha)) {
                            throw new Exception("Arquivo corrompido (checksum)");
                        }
                    }

                    emit(packId, "extracting", 100, done, total, "Instalando");
                    extract(app, zipTmp, pack);
                    emit(packId, "installed", 100, done, total, "Instalado");
                } catch (Throwable t) {
                    Log.w(TAG, "download failed " + packId, t);
                    emit(packId, "error", 0, 0, 0, t.getMessage() != null ? t.getMessage() : "Falha no download");
                } finally {
                    zipTmp.delete();
                    ACTIVE.remove(packId);
                    emitStatus(app);
                }
            }
        });
    }

    private static void downloadDirectFiles(Context ctx, String packId, JSONObject pack, JSONArray directFiles) throws Exception {
        File dir = sf2Dir(ctx);
        long totalPackBytes = pack.optLong("sizeBytes", 0);
        if (totalPackBytes <= 0) {
            for (int i = 0; i < directFiles.length(); i++) {
                JSONObject df = directFiles.optJSONObject(i);
                if (df != null) totalPackBytes += df.optLong("sizeBytes", 0);
            }
        }
        long donePackBytes = 0;
        byte[] buf = new byte[65536];

        for (int i = 0; i < directFiles.length(); i++) {
            JSONObject df = directFiles.getJSONObject(i);
            String sf2Name = df.optString("sf2File", "");
            String fileUrl = df.optString("downloadUrl", "");
            long expectedSize = df.optLong("sizeBytes", 0);
            String expectedSha = df.optString("sha256", "");
            if (sf2Name.isEmpty() || !fileUrl.startsWith("https://")) {
                throw new Exception("Arquivo inválido no pacote");
            }

            File dest = new File(dir, sf2Name);
            if (dest.isFile() && expectedSize > 1024 && dest.length() == expectedSize) {
                donePackBytes += expectedSize;
                int pct = totalPackBytes > 0 ? (int) Math.min(99, donePackBytes * 100L / totalPackBytes) : 0;
                emit(packId, "downloading", pct, donePackBytes, totalPackBytes, "Baixando");
                continue;
            }

            File tmp = new File(dir, sf2Name + ".tmp");
            HttpURLConnection conn = open(fileUrl);
            try {
                if (conn.getResponseCode() != 200) {
                    throw new Exception("HTTP " + conn.getResponseCode());
                }
                MessageDigest md = MessageDigest.getInstance("SHA-256");
                InputStream in = new BufferedInputStream(conn.getInputStream(), 65536);
                OutputStream out = new FileOutputStream(tmp);
                byte[] head = new byte[12];
                int headLen = 0;
                long fileDone = 0;
                long lastEmit = 0;
                try {
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        if (headLen < 12) {
                            int c = Math.min(12 - headLen, n);
                            System.arraycopy(buf, 0, head, headLen, c);
                            headLen += c;
                        }
                        out.write(buf, 0, n);
                        md.update(buf, 0, n);
                        fileDone += n;
                        long now = System.currentTimeMillis();
                        if (now - lastEmit >= 200) {
                            lastEmit = now;
                            long curTotal = donePackBytes + fileDone;
                            int pct = totalPackBytes > 0 ? (int) Math.min(99, curTotal * 100L / totalPackBytes) : 0;
                            emit(packId, "downloading", pct, curTotal, totalPackBytes, "Baixando");
                        }
                    }
                    out.flush();
                } finally {
                    try { out.close(); } catch (Throwable ignored) {}
                    try { in.close(); } catch (Throwable ignored) {}
                }

                if (headLen < 12 || head[0] != 'R' || head[1] != 'I' || head[2] != 'F' || head[3] != 'F'
                        || head[8] != 's' || head[9] != 'f' || head[10] != 'b' || head[11] != 'k') {
                    tmp.delete();
                    throw new Exception("SoundFont inválido: " + sf2Name);
                }

                if (!expectedSha.isEmpty()) {
                    StringBuilder sb = new StringBuilder();
                    for (byte b : md.digest()) sb.append(String.format("%02x", b));
                    if (!sb.toString().equalsIgnoreCase(expectedSha)) {
                        tmp.delete();
                        throw new Exception("Arquivo corrompido (checksum)");
                    }
                }

                if (dest.exists()) dest.delete();
                if (!tmp.renameTo(dest)) {
                    tmp.delete();
                    throw new Exception("Não foi possível gravar " + sf2Name);
                }
                donePackBytes += fileDone;
            } finally {
                conn.disconnect();
            }
        }

        emit(packId, "installed", 100, donePackBytes, totalPackBytes > 0 ? totalPackBytes : donePackBytes, "Instalado");
    }

    private static void extract(Context ctx, File zip, JSONObject pack) throws Exception {
        JSONArray wanted = pack.optJSONArray("sf2Files");
        Set<String> names = new HashSet<>();
        if (wanted != null) {
            for (int i = 0; i < wanted.length(); i++) names.add(wanted.optString(i));
        }
        File dir = sf2Dir(ctx);
        int found = 0;
        ZipInputStream zin = new ZipInputStream(new BufferedInputStream(new java.io.FileInputStream(zip), 65536));
        try {
            ZipEntry e;
            byte[] buf = new byte[65536];
            while ((e = zin.getNextEntry()) != null) {
                String name = e.getName();
                if (e.isDirectory() || !names.contains(name)) continue;
                File tmp = new File(dir, name + ".tmp");
                OutputStream out = new FileOutputStream(tmp);
                byte[] head = new byte[4];
                int headLen = 0;
                int n;
                while ((n = zin.read(buf)) > 0) {
                    if (headLen < 4) {
                        int c = Math.min(4 - headLen, n);
                        System.arraycopy(buf, 0, head, headLen, c);
                        headLen += c;
                    }
                    out.write(buf, 0, n);
                }
                out.close();
                if (headLen < 4 || head[0] != 'R' || head[1] != 'I' || head[2] != 'F' || head[3] != 'F') {
                    tmp.delete();
                    throw new Exception("Soundfont inválido: " + name);
                }
                File dest = new File(dir, name);
                if (dest.exists()) dest.delete();
                if (!tmp.renameTo(dest)) throw new Exception("Não foi possível gravar " + name);
                found++;
            }
        } finally {
            zin.close();
        }
        if (found != names.size()) throw new Exception("Pacote incompleto");
    }

    public static String removePack(Context ctx, String packId) {
        Context app = ctx.getApplicationContext();
        JSONObject pack = findPack(app, packId);
        if (pack != null && !pack.optBoolean("bundled", false) && !ACTIVE.contains(packId)) {
            JSONArray files = pack.optJSONArray("sf2Files");
            if (files != null) {
                File dir = sf2Dir(app);
                for (int i = 0; i < files.length(); i++) {
                    new File(dir, files.optString(i)).delete();
                }
            }
        }
        emitStatus(app);
        return getStatusJson(app);
    }

    private static HttpURLConnection open(String url) throws Exception {
        String cur = url;
        for (int i = 0; i < 7; i++) {
            HttpURLConnection c = (HttpURLConnection) new URL(cur).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            c.setRequestProperty("User-Agent", USER_AGENT);
            int code = c.getResponseCode();
            if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                String loc = c.getHeaderField("Location");
                c.disconnect();
                if (loc == null) throw new Exception("Redirecionamento inválido");
                cur = new URL(new URL(cur), loc).toString();
                continue;
            }
            return c;
        }
        throw new Exception("Muitos redirecionamentos");
    }
}
