package com.p61x.keyboard;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Log;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

public final class BleMidiHelper {
    private static final String TAG = "P61xBleMidi";
    public static final int REQ_BLE_MIDI_PERM = 2001;
    public static final String BLE_MIDI_SERVICE_UUID = "03B80E5A-EDE8-4B33-A751-6CE34EC4C700";

    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());
    private static final Object LOCK = new Object();
    private static final Map<String, DiscoveredBle> DISCOVERED = new LinkedHashMap<>();

    private static BluetoothLeScanner activeScanner;
    private static ScanCallback activeScanCallback;
    private static Runnable stopScanRunnable;
    private static volatile boolean scanning = false;
    private static volatile long lastEmitMs = 0L;

    // Pending action while awaiting runtime permission dialog
    private static volatile boolean pendingScan = false;
    private static volatile boolean pendingIncludeAll = false;
    private static volatile String pendingConnectMac = null;

    private static final class DiscoveredBle {
        final String address;
        String name;
        int rssi;
        boolean hasMidiUuid;
        boolean bonded;
        BluetoothDevice device;

        DiscoveredBle(String address, String name, int rssi, boolean hasMidiUuid, boolean bonded, BluetoothDevice device) {
            this.address = address;
            this.name = name;
            this.rssi = rssi;
            this.hasMidiUuid = hasMidiUuid;
            this.bonded = bonded;
            this.device = device;
        }
    }

    private BleMidiHelper() {}

    public static boolean hasBlePermissions(Context ctx) {
        if (ctx == null) return false;
        if (Build.VERSION.SDK_INT >= 31) {
            return ctx.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
                    && ctx.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
        }
        return ctx.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private static String[] requiredPermissions() {
        if (Build.VERSION.SDK_INT >= 31) {
            return new String[] {
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT
            };
        }
        return new String[] { Manifest.permission.ACCESS_FINE_LOCATION };
    }

    public static void onPermissionsResult(Activity activity, int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode != REQ_BLE_MIDI_PERM) return;
        boolean granted = grantResults != null && grantResults.length > 0;
        if (granted) {
            for (int r : grantResults) {
                if (r != PackageManager.PERMISSION_GRANTED) {
                    granted = false;
                    break;
                }
            }
        }
        if (!granted) {
            pendingScan = false;
            pendingConnectMac = null;
            emitScanState(false, "Permissão Bluetooth negada. Habilite 'Dispositivos por perto' nas configurações do app.");
            return;
        }
        String mac = pendingConnectMac;
        boolean doScan = pendingScan;
        boolean incAll = pendingIncludeAll;
        pendingConnectMac = null;
        pendingScan = false;
        if (mac != null && !mac.isEmpty()) {
            connectDevice(activity, mac);
        } else if (doScan) {
            startScan(activity, incAll);
        }
    }

    @SuppressLint("MissingPermission")
    public static void startScan(final Activity activity, final boolean includeAllBle) {
        if (activity == null) return;
        if (!hasBlePermissions(activity)) {
            pendingScan = true;
            pendingIncludeAll = includeAllBle;
            pendingConnectMac = null;
            emitScanState(false, "Solicitando permissão Bluetooth ao Android...");
            activity.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        activity.requestPermissions(requiredPermissions(), REQ_BLE_MIDI_PERM);
                    } catch (Throwable t) {
                        Log.w(TAG, "requestPermissions failed", t);
                    }
                }
            });
            return;
        }

        final BluetoothAdapter adapter = getAdapter(activity);
        if (adapter == null) {
            emitScanState(false, "Bluetooth não disponível neste aparelho.");
            return;
        }
        if (!adapter.isEnabled()) {
            emitScanState(false, "Ative o Bluetooth do celular para buscar controladores BLE MIDI.");
            return;
        }

        stopScanInternal(false);

        synchronized (LOCK) {
            DISCOVERED.clear();
            // 1. Seed already connected BLE MIDI devices
            Map<String, String> connected = UsbMidiEnhanced.getConnectedBleSnapshot();
            for (Map.Entry<String, String> e : connected.entrySet()) {
                BluetoothDevice bd = null;
                try {
                    bd = adapter.getRemoteDevice(e.getKey());
                } catch (Throwable ignored) {
                }
                DISCOVERED.put(e.getKey(), new DiscoveredBle(e.getKey(), e.getValue(), 0, true, true, bd));
            }
            // 2. Seed bonded BLE/Dual Bluetooth devices
            try {
                Set<BluetoothDevice> bonded = adapter.getBondedDevices();
                if (bonded != null) {
                    for (BluetoothDevice bd : bonded) {
                        if (bd == null || bd.getAddress() == null) continue;
                        int dtype = bd.getType();
                        if (dtype != BluetoothDevice.DEVICE_TYPE_LE && dtype != BluetoothDevice.DEVICE_TYPE_DUAL) {
                            continue;
                        }
                        String name = safeDeviceName(bd);
                        boolean looksMidi = looksLikeMidiDeviceName(name);
                        if (!includeAllBle && !looksMidi) continue;
                        if (!DISCOVERED.containsKey(bd.getAddress())) {
                            DISCOVERED.put(bd.getAddress(), new DiscoveredBle(bd.getAddress(), name, -50, looksMidi, true, bd));
                        }
                    }
                }
            } catch (Throwable t) {
                Log.w(TAG, "getBondedDevices failed", t);
            }
        }

        BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) {
            emitScanState(false, "Scanner Bluetooth LE indisponível no momento.");
            return;
        }

        ScanCallback cb = new ScanCallback() {
            @Override
            public void onScanResult(int callbackType, ScanResult result) {
                handleScanResult(result, includeAllBle);
            }

            @Override
            public void onBatchScanResults(List<ScanResult> results) {
                if (results == null) return;
                for (ScanResult r : results) {
                    handleScanResult(r, includeAllBle);
                }
            }

            @Override
            public void onScanFailed(int errorCode) {
                Log.w(TAG, "BLE scan failed: code=" + errorCode);
                stopScanInternal(false);
                emitScanState(false, "Erro ao buscar BLE MIDI (código " + errorCode + ").");
            }
        };

        try {
            ScanSettings settings = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .build();
            List<ScanFilter> filters;
            if (includeAllBle) {
                filters = Collections.emptyList();
            } else {
                ScanFilter midiFilter = new ScanFilter.Builder()
                        .setServiceUuid(ParcelUuid.fromString(BLE_MIDI_SERVICE_UUID))
                        .build();
                filters = Collections.singletonList(midiFilter);
            }

            activeScanner = scanner;
            activeScanCallback = cb;
            scanning = true;
            scanner.startScan(filters, settings, cb);

            stopScanRunnable = new Runnable() {
                @Override
                public void run() {
                    stopScanInternal(true);
                }
            };
            MAIN_HANDLER.postDelayed(stopScanRunnable, 12000L);

            emitScanState(true, includeAllBle
                    ? "Buscando todos os dispositivos Bluetooth LE próximos..."
                    : "Buscando controladores MIDI Bluetooth (BLE MIDI)...");
        } catch (Throwable t) {
            Log.e(TAG, "startScan failed", t);
            stopScanInternal(false);
            emitScanState(false, "Não foi possível iniciar busca BLE: " + t.getMessage());
        }
    }

    public static void stopScan() {
        stopScanInternal(true);
    }

    @SuppressLint("MissingPermission")
    private static void stopScanInternal(boolean emit) {
        if (stopScanRunnable != null) {
            MAIN_HANDLER.removeCallbacks(stopScanRunnable);
            stopScanRunnable = null;
        }
        boolean wasScanning = scanning;
        scanning = false;
        BluetoothLeScanner sc = activeScanner;
        ScanCallback cb = activeScanCallback;
        activeScanner = null;
        activeScanCallback = null;
        if (sc != null && cb != null) {
            try {
                sc.stopScan(cb);
            } catch (Throwable ignored) {
            }
        }
        if (emit && wasScanning) {
            int count;
            synchronized (LOCK) {
                count = DISCOVERED.size();
            }
            emitScanState(false, count > 0
                    ? ("Busca concluída (" + count + " encontrado(s)). Toque em Conectar.")
                    : "Nenhum controlador BLE MIDI encontrado. Ligue o adaptador/teclado ou marque 'Mostrar todos BLE'.");
        }
    }

    @SuppressLint("MissingPermission")
    private static void handleScanResult(ScanResult result, boolean includeAllBle) {
        if (result == null || result.getDevice() == null) return;
        BluetoothDevice dev = result.getDevice();
        String addr = dev.getAddress();
        if (addr == null || addr.isEmpty()) return;

        ScanRecord rec = result.getScanRecord();
        String name = null;
        boolean hasMidiUuid = false;
        if (rec != null) {
            name = rec.getDeviceName();
            List<ParcelUuid> uuids = rec.getServiceUuids();
            if (uuids != null) {
                for (ParcelUuid u : uuids) {
                    if (u != null && BLE_MIDI_SERVICE_UUID.equalsIgnoreCase(u.toString())) {
                        hasMidiUuid = true;
                        break;
                    }
                }
            }
        }
        if (name == null || name.trim().isEmpty()) {
            name = safeDeviceName(dev);
        }
        if (includeAllBle && !hasMidiUuid && (name == null || name.isEmpty() || name.startsWith("BLE "))) {
            // Skip unnamed random beacons/trackers when showing all BLE
            return;
        }

        boolean isNew;
        synchronized (LOCK) {
            DiscoveredBle prev = DISCOVERED.get(addr);
            if (prev == null) {
                DISCOVERED.put(addr, new DiscoveredBle(addr, name, result.getRssi(), hasMidiUuid, false, dev));
                isNew = true;
            } else {
                prev.rssi = result.getRssi();
                if (name != null && !name.isEmpty()) prev.name = name;
                if (hasMidiUuid) prev.hasMidiUuid = true;
                prev.device = dev;
                isNew = false;
            }
        }

        long now = System.currentTimeMillis();
        if (isNew || now - lastEmitMs >= 600L) {
            lastEmitMs = now;
            emitScanState(scanning, null);
        }
    }

    @SuppressLint("MissingPermission")
    public static void connectDevice(final Activity activity, final String address) {
        if (activity == null || address == null || address.trim().isEmpty()) return;
        final String mac = address.trim();
        if (!hasBlePermissions(activity)) {
            pendingConnectMac = mac;
            pendingScan = false;
            activity.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    try {
                        activity.requestPermissions(requiredPermissions(), REQ_BLE_MIDI_PERM);
                    } catch (Throwable ignored) {
                    }
                }
            });
            return;
        }

        // Always stop BLE scanning before GATT/MIDI open on Samsung stacks
        stopScanInternal(false);

        BluetoothAdapter adapter = getAdapter(activity);
        if (adapter == null || !adapter.isEnabled()) {
            emitConnectResult(mac, "", false, false, "Ative o Bluetooth do aparelho para conectar.");
            return;
        }

        BluetoothDevice btDev = null;
        String displayName = mac;
        synchronized (LOCK) {
            DiscoveredBle entry = DISCOVERED.get(mac);
            if (entry != null) {
                btDev = entry.device;
                displayName = entry.name;
            }
        }
        if (btDev == null) {
            try {
                btDev = adapter.getRemoteDevice(mac);
                displayName = safeDeviceName(btDev);
            } catch (Throwable t) {
                emitConnectResult(mac, mac, false, false, "Endereço Bluetooth inválido.");
                return;
            }
        }

        emitConnectResult(mac, displayName, false, true, "Conectando a " + displayName + " via BLE MIDI...");
        UsbMidiEnhanced.openBluetoothDevice(btDev, displayName);
    }

    public static void disconnectDevice(String address) {
        if (address == null || address.trim().isEmpty()) return;
        UsbMidiEnhanced.disconnectBluetoothDevice(address.trim());
    }

    public static void emitConnectResult(String address, String name, boolean connected, boolean connecting, String message) {
        try {
            JSONObject ev = new JSONObject();
            ev.put("event", "ble_connect_result");
            ev.put("address", address != null ? address : "");
            ev.put("name", name != null ? name : "");
            ev.put("connected", connected);
            ev.put("connecting", connecting);
            ev.put("message", message != null ? message : "");
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable ignored) {
        }
        emitScanState(scanning, message);
    }

    public static void emitScanState(boolean isScanning, String message) {
        try {
            Map<String, String> connectedBle = UsbMidiEnhanced.getConnectedBleSnapshot();
            JSONArray arr = new JSONArray();
            List<DiscoveredBle> snapshot;
            synchronized (LOCK) {
                snapshot = new ArrayList<>(DISCOVERED.values());
            }
            for (DiscoveredBle d : snapshot) {
                JSONObject o = new JSONObject();
                o.put("address", d.address);
                o.put("name", d.name);
                o.put("rssi", d.rssi);
                o.put("hasMidiUuid", d.hasMidiUuid);
                o.put("bonded", d.bonded);
                o.put("connected", connectedBle.containsKey(d.address));
                arr.put(o);
            }
            // Ensure any connected BLE device not in DISCOVERED is still listed
            for (Map.Entry<String, String> e : connectedBle.entrySet()) {
                boolean present = false;
                for (DiscoveredBle d : snapshot) {
                    if (e.getKey().equals(d.address)) {
                        present = true;
                        break;
                    }
                }
                if (!present) {
                    JSONObject o = new JSONObject();
                    o.put("address", e.getKey());
                    o.put("name", e.getValue());
                    o.put("rssi", 0);
                    o.put("hasMidiUuid", true);
                    o.put("bonded", true);
                    o.put("connected", true);
                    arr.put(o);
                }
            }

            JSONObject ev = new JSONObject();
            ev.put("event", "ble_scan_result");
            ev.put("scanning", isScanning);
            ev.put("devices", arr);
            if (message != null) ev.put("message", message);
            P61xPatch.postEventToActiveUi(ev);
        } catch (Throwable t) {
            Log.w(TAG, "emitScanState failed", t);
        }
    }

    private static BluetoothAdapter getAdapter(Context ctx) {
        try {
            BluetoothManager bm = (BluetoothManager) ctx.getSystemService(Context.BLUETOOTH_SERVICE);
            return bm != null ? bm.getAdapter() : null;
        } catch (Throwable ignored) {
            return null;
        }
    }

    @SuppressLint("MissingPermission")
    private static String safeDeviceName(BluetoothDevice dev) {
        if (dev == null) return "BLE MIDI";
        try {
            String n = dev.getName();
            if (n != null && !n.trim().isEmpty()) return n.trim();
        } catch (Throwable ignored) {
        }
        String addr = dev.getAddress();
        return addr != null ? ("BLE " + addr) : "BLE MIDI";
    }

    private static boolean looksLikeMidiDeviceName(String name) {
        if (name == null) return false;
        String u = name.toUpperCase();
        return u.contains("MIDI") || u.contains("WIDI") || u.contains("MD-BT")
                || u.contains("UD-BT") || u.contains("WM-1") || u.contains("KORG")
                || u.contains("ROLAND") || u.contains("YAMAHA") || u.contains("ARTURIA")
                || u.contains("M-VAVE") || u.contains("MVAVE") || u.contains("MS1")
                || u.contains("CUVAVE") || u.contains("SINCO") || u.contains("AKAI")
                || u.contains("CME") || u.contains("NUX") || u.contains("KEY")
                || u.contains("PIANO") || u.contains("SYNTH") || u.contains("PAD");
    }
}
