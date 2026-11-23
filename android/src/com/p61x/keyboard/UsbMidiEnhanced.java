package com.p61x.keyboard;

import android.bluetooth.BluetoothDevice;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbManager;
import android.media.midi.MidiDevice;
import android.media.midi.MidiDeviceInfo;
import android.media.midi.MidiManager;
import android.media.midi.MidiOutputPort;
import android.media.midi.MidiReceiver;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Executor;
import org.json.JSONArray;
import org.json.JSONObject;

public final class UsbMidiEnhanced {
    private static final String TAG = "P61xMidi";
    private static final String VIRTUAL_LABEL = "Virtual / Teclado 61 Teclas";
    private static final String ACTION_USB_STATE = "android.hardware.usb.action.USB_STATE";

    private static final Map<UsbMidiController, State> STATES = new IdentityHashMap<>();
    private static volatile State activeState;

    private static final class DeviceEntry {
        final int id;
        final String name;
        final String transport; // "usb" or "ble"
        final String bleAddress;
        final MidiDeviceInfo info;
        final MidiDevice device;
        final List<MidiOutputPort> outputPorts = new ArrayList<>();

        DeviceEntry(int id, String name, String transport, String bleAddress, MidiDeviceInfo info, MidiDevice device) {
            this.id = id;
            this.name = name;
            this.transport = transport;
            this.bleAddress = bleAddress;
            this.info = info;
            this.device = device;
        }
    }

    private static final class State {
        final Object lock = new Object();
        final UsbMidiController controller;
        final Context appCtx;
        final UsbMidiController.EventListener listener;
        final Handler mainHandler = new Handler(Looper.getMainLooper());
        final Map<Integer, DeviceEntry> openedDevices = new LinkedHashMap<>();
        final Map<String, Integer> bleAddrToId = new LinkedHashMap<>();
        final Set<Integer> openingIds = new HashSet<>();
        final Set<String> bleOpeningAddrs = new HashSet<>();
        final Map<Integer, Integer> retryCounts = new HashMap<>();

        MidiManager midiManager;
        MidiManager.DeviceCallback legacyCallback;
        MidiManager.DeviceCallback transportCallback;
        BroadcastReceiver usbReceiver;

        volatile boolean started = false;
        volatile String selectedPortId = "auto";
        volatile String activePortName = VIRTUAL_LABEL;

        State(UsbMidiController controller, Context ctx, UsbMidiController.EventListener listener) {
            this.controller = controller;
            this.appCtx = ctx != null ? ctx.getApplicationContext() : null;
            this.listener = listener;
        }
    }

    private UsbMidiEnhanced() {}

    private static State getOrCreateState(UsbMidiController ctrl, Context ctx, UsbMidiController.EventListener listener) {
        synchronized (STATES) {
            State st = STATES.get(ctrl);
            if (st == null) {
                st = new State(ctrl, ctx, listener);
                STATES.put(ctrl, st);
            }
            activeState = st;
            return st;
        }
    }

    private static State getState(UsbMidiController ctrl) {
        synchronized (STATES) {
            return STATES.get(ctrl);
        }
    }

    public static void start(UsbMidiController ctrl, Context ctx, UsbMidiController.EventListener listener) {
        final State st = getOrCreateState(ctrl, ctx, listener);
        if (st.appCtx == null) return;

        synchronized (st.lock) {
            if (st.started) {
                scheduleRescanBurst(st, "restart");
                return;
            }
            st.started = true;
        }

        try {
            st.midiManager = (MidiManager) st.appCtx.getSystemService(Context.MIDI_SERVICE);
        } catch (Throwable t) {
            Log.w(TAG, "MIDI_SERVICE unavailable", t);
        }

        if (st.midiManager != null) {
            st.legacyCallback = createDeviceCallback(st);
            try {
                st.midiManager.registerDeviceCallback(st.legacyCallback, st.mainHandler);
            } catch (Throwable t) {
                Log.w(TAG, "Legacy registerDeviceCallback failed", t);
            }

            if (Build.VERSION.SDK_INT >= 33) {
                try {
                    st.transportCallback = createDeviceCallback(st);
                    Executor mainExec = new Executor() {
                        @Override
                        public void execute(Runnable command) {
                            st.mainHandler.post(command);
                        }
                    };
                    st.midiManager.registerDeviceCallback(
                            MidiManager.TRANSPORT_MIDI_BYTE_STREAM, mainExec, st.transportCallback);
                } catch (Throwable t) {
                    Log.w(TAG, "API 33 registerDeviceCallback failed", t);
                }
            }
        }

        registerUsbReceiver(st);

        scanAndOpenAll(st, "startup");
        scheduleRescanBurst(st, "startup_retry");
    }

    public static void stop(UsbMidiController ctrl) {
        State st = getState(ctrl);
        if (st == null) return;

        synchronized (st.lock) {
            st.started = false;
        }

        try {
            st.mainHandler.removeCallbacksAndMessages(null);
        } catch (Throwable ignored) {
        }

        if (st.midiManager != null) {
            if (st.legacyCallback != null) {
                try {
                    st.midiManager.unregisterDeviceCallback(st.legacyCallback);
                } catch (Throwable ignored) {
                }
                st.legacyCallback = null;
            }
            if (st.transportCallback != null) {
                try {
                    st.midiManager.unregisterDeviceCallback(st.transportCallback);
                } catch (Throwable ignored) {
                }
                st.transportCallback = null;
            }
        }

        if (st.usbReceiver != null && st.appCtx != null) {
            try {
                st.appCtx.unregisterReceiver(st.usbReceiver);
            } catch (Throwable ignored) {
            }
            st.usbReceiver = null;
        }

        synchronized (st.lock) {
            for (DeviceEntry entry : st.openedDevices.values()) {
                closeEntryQuietly(entry);
            }
            st.openedDevices.clear();
            st.bleAddrToId.clear();
            st.openingIds.clear();
            st.bleOpeningAddrs.clear();
            st.retryCounts.clear();
            st.activePortName = VIRTUAL_LABEL;
        }

        synchronized (STATES) {
            STATES.remove(ctrl);
            if (activeState == st) {
                activeState = null;
            }
        }
    }

    public static String getActivePortName(UsbMidiController ctrl) {
        State st = getState(ctrl);
        return st != null ? st.activePortName : VIRTUAL_LABEL;
    }

    public static JSONArray listInputPortsJson(UsbMidiController ctrl) {
        State st = getState(ctrl);
        if (st == null) return new JSONArray();
        return buildPortsArray(st);
    }

    public static void selectInputPort(UsbMidiController ctrl, String portId) {
        State st = getState(ctrl);
        if (st == null) return;
        st.selectedPortId = (portId == null || portId.trim().isEmpty()) ? "auto" : portId.trim();
        scanAndOpenAll(st, "select");
        refreshAndEmit(st, "select");
    }

    public static void onUiPageReady() {
        final State st = activeState;
        if (st == null || !st.started) return;
        st.mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (!st.started) return;
                scanAndOpenAll(st, "page_ready");
                refreshAndEmit(st, "page_ready");
            }
        });
        st.mainHandler.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (!st.started) return;
                scanAndOpenAll(st, "page_ready_delayed");
            }
        }, 650L);
    }

    public static void rescanQuietly(final String reason) {
        final State st = activeState;
        if (st == null || !st.started) return;
        st.mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (!st.started) return;
                scanAndOpenAll(st, reason);
            }
        });
    }

    public static String rescanActiveJson() {
        State st = activeState;
        JSONObject out = new JSONObject();
        try {
            if (st != null && st.started) {
                scanAndOpenAll(st, "manual_rescan");
                scheduleRescanBurst(st, "manual_rescan_followup");
                refreshAndEmit(st, "manual_rescan");
                out.put("ok", true);
                out.put("active_port", st.activePortName);
                out.put("selected_port_id", st.selectedPortId);
                JSONArray ports = buildPortsArray(st);
                out.put("ports", ports);
                out.put("connected_count", countOpened(st));
            } else {
                out.put("ok", false);
                out.put("active_port", VIRTUAL_LABEL);
                out.put("selected_port_id", "auto");
                out.put("ports", new JSONArray());
                out.put("connected_count", 0);
            }
        } catch (Throwable t) {
            Log.w(TAG, "rescanActiveJson failed", t);
        }
        return out.toString();
    }

    // =========================================================================
    // BLE MIDI CONNECTION SUPPORT (MidiManager.openBluetoothDevice)
    // =========================================================================
    public static Map<String, String> getConnectedBleSnapshot() {
        Map<String, String> snap = new LinkedHashMap<>();
        State st = activeState;
        if (st == null) return snap;
        synchronized (st.lock) {
            for (Map.Entry<String, Integer> e : st.bleAddrToId.entrySet()) {
                DeviceEntry de = st.openedDevices.get(e.getValue());
                if (de != null) {
                    snap.put(e.getKey(), de.name);
                }
            }
        }
        return snap;
    }

    public static void openBluetoothDevice(final BluetoothDevice btDevice, final String fallbackName) {
        openBluetoothDeviceInternal(btDevice, fallbackName, 0);
    }

    private static void openBluetoothDeviceInternal(final BluetoothDevice btDevice, final String fallbackName, final int attempt) {
        final State st = activeState;
        if (st == null || !st.started || st.midiManager == null || btDevice == null) {
            BleMidiHelper.emitConnectResult(btDevice != null ? btDevice.getAddress() : "", fallbackName, false, false,
                    "Serviço MIDI do Android ainda não está pronto.");
            return;
        }
        final String mac = btDevice.getAddress();
        if (mac == null || mac.isEmpty()) return;
        final String niceName = (fallbackName != null && !fallbackName.trim().isEmpty()) ? fallbackName.trim() : ("BLE MIDI " + mac);

        synchronized (st.lock) {
            if (st.bleAddrToId.containsKey(mac)) {
                BleMidiHelper.emitConnectResult(mac, niceName, true, false, niceName + " já está conectado via BLE MIDI.");
                refreshAndEmit(st, "ble_connected");
                return;
            }
            if (st.bleOpeningAddrs.contains(mac) && attempt == 0) {
                return;
            }
            st.bleOpeningAddrs.add(mac);
        }

        try {
            st.midiManager.openBluetoothDevice(btDevice, new MidiManager.OnDeviceOpenedListener() {
                @Override
                public void onDeviceOpened(MidiDevice device) {
                    synchronized (st.lock) {
                        st.bleOpeningAddrs.remove(mac);
                    }
                    if (!st.started) {
                        if (device != null) {
                            try { device.close(); } catch (Throwable ignored) {}
                        }
                        return;
                    }
                    if (device == null) {
                        if (attempt < 1) {
                            st.mainHandler.postDelayed(new Runnable() {
                                @Override
                                public void run() {
                                    if (st.started) {
                                        openBluetoothDeviceInternal(btDevice, niceName, attempt + 1);
                                    }
                                }
                            }, 900L);
                            return;
                        }
                        BleMidiHelper.emitConnectResult(mac, niceName, false, false,
                                "Não foi possível abrir BLE MIDI em " + niceName + ". Verifique se o dispositivo suporta MIDI Bluetooth.");
                        return;
                    }

                    MidiDeviceInfo info = device.getInfo();
                    int devId = info != null ? info.getId() : (0x40000000 | (mac.hashCode() & 0x0FFFFFFF));
                    String resolvedName = (info != null) ? formatDeviceName(info) : niceName;
                    if (resolvedName.startsWith("USB MIDI #")) {
                        resolvedName = niceName;
                    }
                    if (!resolvedName.toUpperCase().contains("BLE") && !resolvedName.toUpperCase().contains("BT")) {
                        resolvedName = resolvedName + " (BLE)";
                    }

                    int portCount = info != null ? Math.max(1, info.getOutputPortCount()) : 1;
                    DeviceEntry entry = new DeviceEntry(devId, resolvedName, "ble", mac, info, device);
                    final int finalDevId = devId;
                    for (int p = 0; p < portCount; p++) {
                        try {
                            MidiOutputPort outPort = device.openOutputPort(p);
                            if (outPort != null) {
                                final String sourceLabel = portCount > 1 ? (resolvedName + " P" + (p + 1)) : resolvedName;
                                outPort.connect(new MidiReceiver() {
                                    @Override
                                    public void onSend(byte[] msg, int offset, int count, long timestamp) throws IOException {
                                        if (msg == null || count <= 0) return;
                                        if (!shouldAcceptDevice(st, finalDevId)) return;
                                        try {
                                            st.controller.onEnhancedMidiBytes(sourceLabel, msg, offset, count);
                                        } catch (Throwable t) {
                                            Log.w(TAG, "BLE MIDI dispatch error", t);
                                        }
                                    }
                                });
                                entry.outputPorts.add(outPort);
                            }
                        } catch (Throwable t) {
                            Log.w(TAG, "BLE openOutputPort(" + p + ") failed for " + resolvedName, t);
                        }
                    }

                    if (entry.outputPorts.isEmpty()) {
                        closeEntryQuietly(entry);
                        BleMidiHelper.emitConnectResult(mac, niceName, false, false,
                                niceName + " conectou, mas não expôs porta de saída MIDI.");
                        return;
                    }

                    synchronized (st.lock) {
                        DeviceEntry prev = st.openedDevices.put(devId, entry);
                        st.bleAddrToId.put(mac, devId);
                        if (prev != null && prev != entry) {
                            closeEntryQuietly(prev);
                        }
                    }
                    Log.i(TAG, "BLE MIDI connected: " + resolvedName + " (" + mac + ", ports=" + entry.outputPorts.size() + ")");
                    refreshAndEmit(st, "connected");
                    BleMidiHelper.emitConnectResult(mac, resolvedName, true, false, "BLE MIDI conectado: " + resolvedName);
                }
            }, st.mainHandler);
        } catch (Throwable t) {
            synchronized (st.lock) {
                st.bleOpeningAddrs.remove(mac);
            }
            Log.e(TAG, "openBluetoothDevice threw", t);
            BleMidiHelper.emitConnectResult(mac, niceName, false, false, "Erro ao conectar BLE MIDI: " + t.getMessage());
        }
    }

    public static void disconnectBluetoothDevice(String mac) {
        State st = activeState;
        if (st == null || mac == null) return;
        Integer devId;
        DeviceEntry removed = null;
        synchronized (st.lock) {
            st.bleOpeningAddrs.remove(mac);
            devId = st.bleAddrToId.remove(mac);
            if (devId != null) {
                removed = st.openedDevices.remove(devId);
            }
        }
        if (removed != null) {
            closeEntryQuietly(removed);
            Log.i(TAG, "BLE MIDI disconnected: " + removed.name + " (" + mac + ")");
            refreshAndEmit(st, "disconnected");
            BleMidiHelper.emitConnectResult(mac, removed.name, false, false, "BLE MIDI desconectado: " + removed.name);
        } else {
            BleMidiHelper.emitScanState(false, null);
        }
    }

    // =========================================================================
    // USB MIDI CALLBACKS & HOTPLUG
    // =========================================================================
    private static MidiManager.DeviceCallback createDeviceCallback(final State st) {
        return new MidiManager.DeviceCallback() {
            @Override
            public void onDeviceAdded(MidiDeviceInfo device) {
                if (device == null || !st.started) return;
                if (device.getOutputPortCount() > 0) {
                    openDeviceIdempotent(st, device);
                }
                scheduleRescanBurst(st, "midi_added");
            }

            @Override
            public void onDeviceRemoved(MidiDeviceInfo device) {
                if (device == null) return;
                closeDeviceById(st, device.getId(), "disconnected");
            }
        };
    }

    private static void registerUsbReceiver(final State st) {
        if (st.appCtx == null) return;
        try {
            IntentFilter filter = new IntentFilter();
            filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
            filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
            filter.addAction(ACTION_USB_STATE);

            st.usbReceiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    if (!st.started || intent == null) return;
                    String action = intent.getAction();
                    if (UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(action) || ACTION_USB_STATE.equals(action)) {
                        scanAndOpenAll(st, "usb_attached");
                        scheduleRescanBurst(st, "usb_attached_retry");
                    } else if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(action)) {
                        pruneDisconnectedDevices(st);
                        st.mainHandler.postDelayed(new Runnable() {
                            @Override
                            public void run() {
                                if (st.started) pruneDisconnectedDevices(st);
                            }
                        }, 450L);
                    }
                }
            };

            if (Build.VERSION.SDK_INT >= 33) {
                st.appCtx.registerReceiver(st.usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                st.appCtx.registerReceiver(st.usbReceiver, filter);
            }
        } catch (Throwable t) {
            Log.w(TAG, "registerUsbReceiver failed", t);
        }
    }

    private static void scheduleRescanBurst(final State st, final String reason) {
        long[] delays = new long[] { 350L, 1100L, 2400L };
        for (long d : delays) {
            st.mainHandler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (st.started) {
                        scanAndOpenAll(st, reason);
                    }
                }
            }, d);
        }
    }

    private static Map<Integer, MidiDeviceInfo> collectAllInputDevices(MidiManager mm) {
        Map<Integer, MidiDeviceInfo> found = new LinkedHashMap<>();
        if (mm == null) return found;

        if (Build.VERSION.SDK_INT >= 33) {
            try {
                Set<MidiDeviceInfo> byTransport = mm.getDevicesForTransport(MidiManager.TRANSPORT_MIDI_BYTE_STREAM);
                if (byTransport != null) {
                    for (MidiDeviceInfo info : byTransport) {
                        if (info != null && info.getOutputPortCount() > 0) {
                            found.put(info.getId(), info);
                        }
                    }
                }
            } catch (Throwable t) {
                Log.w(TAG, "getDevicesForTransport failed", t);
            }
        }

        try {
            @SuppressWarnings("deprecation")
            MidiDeviceInfo[] legacy = mm.getDevices();
            if (legacy != null) {
                for (MidiDeviceInfo info : legacy) {
                    if (info != null && info.getOutputPortCount() > 0) {
                        found.putIfAbsent(info.getId(), info);
                    }
                }
            }
        } catch (Throwable t) {
            Log.w(TAG, "getDevices failed", t);
        }
        return found;
    }

    private static void scanAndOpenAll(State st, String reason) {
        if (!st.started || st.midiManager == null) return;
        Map<Integer, MidiDeviceInfo> current = collectAllInputDevices(st.midiManager);

        List<Integer> removedIds = new ArrayList<>();
        synchronized (st.lock) {
            for (Map.Entry<Integer, DeviceEntry> e : st.openedDevices.entrySet()) {
                // Only prune USB devices from MidiManager scan (BLE devices are managed explicitly or via onDeviceRemoved)
                if (!"ble".equals(e.getValue().transport) && !current.containsKey(e.getKey())) {
                    removedIds.add(e.getKey());
                }
            }
        }
        for (Integer id : removedIds) {
            closeDeviceById(st, id, "disconnected");
        }

        for (MidiDeviceInfo info : current.values()) {
            // Skip Bluetooth devices here if already opened via BleMidiHelper
            if (info.getType() == MidiDeviceInfo.TYPE_BLUETOOTH) {
                synchronized (st.lock) {
                    if (st.openedDevices.containsKey(info.getId())) continue;
                }
            }
            openDeviceIdempotent(st, info);
        }
    }

    private static void pruneDisconnectedDevices(State st) {
        if (!st.started || st.midiManager == null) return;
        Map<Integer, MidiDeviceInfo> current = collectAllInputDevices(st.midiManager);
        List<Integer> removedIds = new ArrayList<>();
        synchronized (st.lock) {
            for (Map.Entry<Integer, DeviceEntry> e : st.openedDevices.entrySet()) {
                if (!"ble".equals(e.getValue().transport) && !current.containsKey(e.getKey())) {
                    removedIds.add(e.getKey());
                }
            }
        }
        for (Integer id : removedIds) {
            closeDeviceById(st, id, "disconnected");
        }
    }

    private static void openDeviceIdempotent(final State st, final MidiDeviceInfo info) {
        if (st.midiManager == null || info == null || !st.started) return;
        final int devId = info.getId();
        synchronized (st.lock) {
            if (st.openedDevices.containsKey(devId) || st.openingIds.contains(devId)) {
                return;
            }
            st.openingIds.add(devId);
        }

        final String name = formatDeviceName(info);
        final String transport = info.getType() == MidiDeviceInfo.TYPE_BLUETOOTH ? "ble" : "usb";
        try {
            st.midiManager.openDevice(info, new MidiManager.OnDeviceOpenedListener() {
                @Override
                public void onDeviceOpened(MidiDevice device) {
                    synchronized (st.lock) {
                        st.openingIds.remove(devId);
                    }
                    if (!st.started) {
                        if (device != null) {
                            try { device.close(); } catch (Throwable ignored) {}
                        }
                        return;
                    }
                    if (device == null) {
                        int attempt;
                        synchronized (st.lock) {
                            Integer prev = st.retryCounts.get(devId);
                            attempt = (prev != null ? prev : 0) + 1;
                            st.retryCounts.put(devId, attempt);
                        }
                        if (attempt <= 3) {
                            long delay = attempt * 650L;
                            st.mainHandler.postDelayed(new Runnable() {
                                @Override
                                public void run() {
                                    if (st.started) {
                                        openDeviceIdempotent(st, info);
                                    }
                                }
                            }, delay);
                        }
                        return;
                    }

                    DeviceEntry entry = new DeviceEntry(devId, name, transport, null, info, device);
                    int portCount = Math.max(1, info.getOutputPortCount());
                    for (int p = 0; p < portCount; p++) {
                        try {
                            MidiOutputPort outPort = device.openOutputPort(p);
                            if (outPort != null) {
                                final String sourceLabel = portCount > 1 ? (name + " P" + (p + 1)) : name;
                                outPort.connect(new MidiReceiver() {
                                    @Override
                                    public void onSend(byte[] msg, int offset, int count, long timestamp) throws IOException {
                                        if (msg == null || count <= 0) return;
                                        if (!shouldAcceptDevice(st, devId)) return;
                                        try {
                                            st.controller.onEnhancedMidiBytes(sourceLabel, msg, offset, count);
                                        } catch (Throwable t) {
                                            Log.w(TAG, "MIDI dispatch error", t);
                                        }
                                    }
                                });
                                entry.outputPorts.add(outPort);
                            }
                        } catch (Throwable t) {
                            Log.w(TAG, "openOutputPort(" + p + ") failed for " + name, t);
                        }
                    }

                    synchronized (st.lock) {
                        DeviceEntry prev = st.openedDevices.put(devId, entry);
                        st.retryCounts.remove(devId);
                        if (prev != null && prev != entry) {
                            closeEntryQuietly(prev);
                        }
                    }
                    Log.i(TAG, "MIDI connected: " + name + " (id=" + devId + ", transport=" + transport + ", ports=" + entry.outputPorts.size() + ")");
                    refreshAndEmit(st, "connected");
                }
            }, st.mainHandler);
        } catch (Throwable t) {
            synchronized (st.lock) {
                st.openingIds.remove(devId);
            }
            Log.w(TAG, "openDevice threw for " + name, t);
        }
    }

    private static void closeDeviceById(State st, int devId, String reason) {
        DeviceEntry removed;
        String bleMac = null;
        synchronized (st.lock) {
            st.openingIds.remove(devId);
            st.retryCounts.remove(devId);
            removed = st.openedDevices.remove(devId);
            if (removed != null && removed.bleAddress != null) {
                bleMac = removed.bleAddress;
                st.bleAddrToId.remove(bleMac);
            }
        }
        if (removed != null) {
            closeEntryQuietly(removed);
            Log.i(TAG, "MIDI disconnected: " + removed.name + " (id=" + devId + ")");
            refreshAndEmit(st, reason);
            if (bleMac != null) {
                BleMidiHelper.emitConnectResult(bleMac, removed.name, false, false, "BLE MIDI desconectado: " + removed.name);
            }
        }
    }

    private static void closeEntryQuietly(DeviceEntry entry) {
        if (entry == null) return;
        for (MidiOutputPort p : entry.outputPorts) {
            try {
                p.close();
            } catch (Throwable ignored) {
            }
        }
        entry.outputPorts.clear();
        if (entry.device != null) {
            try {
                entry.device.close();
            } catch (Throwable ignored) {
            }
        }
    }

    private static boolean shouldAcceptDevice(State st, int devId) {
        String sel = st.selectedPortId;
        if (sel == null || sel.isEmpty() || "auto".equals(sel)) {
            return true;
        }
        if ("virtual-p61x".equals(sel)) {
            return false;
        }
        return sel.equals(String.valueOf(devId));
    }

    private static int countOpened(State st) {
        synchronized (st.lock) {
            return st.openedDevices.size();
        }
    }

    private static JSONArray buildPortsArray(State st) {
        JSONArray arr = new JSONArray();
        Map<Integer, MidiDeviceInfo> all = collectAllInputDevices(st.midiManager);
        Set<Integer> seen = new HashSet<>();

        synchronized (st.lock) {
            for (DeviceEntry entry : st.openedDevices.values()) {
                seen.add(entry.id);
                try {
                    JSONObject o = new JSONObject();
                    o.put("id", String.valueOf(entry.id));
                    o.put("name", entry.name);
                    o.put("transport", entry.transport);
                    o.put("connected", true);
                    o.put("port_count", entry.outputPorts.size());
                    if (entry.bleAddress != null) o.put("ble_address", entry.bleAddress);
                    arr.put(o);
                } catch (Throwable ignored) {
                }
            }
        }

        for (MidiDeviceInfo info : all.values()) {
            if (seen.contains(info.getId())) continue;
            try {
                JSONObject o = new JSONObject();
                o.put("id", String.valueOf(info.getId()));
                o.put("name", formatDeviceName(info));
                o.put("transport", info.getType() == MidiDeviceInfo.TYPE_BLUETOOTH ? "ble" : "usb");
                o.put("connected", false);
                o.put("port_count", info.getOutputPortCount());
                arr.put(o);
            } catch (Throwable ignored) {
            }
        }
        return arr;
    }

    private static void refreshAndEmit(State st, String reason) {
        String label = VIRTUAL_LABEL;
        int connectedCount;
        String sel = st.selectedPortId;

        synchronized (st.lock) {
            connectedCount = st.openedDevices.size();
            if ("virtual-p61x".equals(sel)) {
                label = VIRTUAL_LABEL;
            } else if (connectedCount > 0) {
                DeviceEntry matched = null;
                if (sel != null && !"auto".equals(sel) && !sel.isEmpty()) {
                    try {
                        matched = st.openedDevices.get(Integer.parseInt(sel));
                    } catch (Throwable ignored) {
                    }
                }
                if (matched != null) {
                    label = matched.name;
                } else {
                    DeviceEntry first = st.openedDevices.values().iterator().next();
                    label = connectedCount > 1 ? (first.name + " (+" + (connectedCount - 1) + ")") : first.name;
                }
            }
        }

        st.activePortName = label;

        try {
            JSONObject ev = new JSONObject();
            ev.put("event", "port_status");
            ev.put("input_port", label);
            ev.put("output_port", "AAudio Stage Engine");
            ev.put("ports", buildPortsArray(st));
            ev.put("connected_count", connectedCount);
            ev.put("selected_port_id", sel != null ? sel : "auto");
            ev.put("reason", reason != null ? reason : "update");

            if (st.listener != null) {
                st.listener.onMidiUiEvent(ev);
            }
        } catch (Throwable t) {
            Log.w(TAG, "emitRichPortStatus failed", t);
        }
    }

    public static String formatDeviceName(MidiDeviceInfo info) {
        if (info == null) return "USB MIDI";
        Bundle props = info.getProperties();
        if (props != null) {
            String name = props.getString(MidiDeviceInfo.PROPERTY_NAME);
            if (name != null && !name.trim().isEmpty()) {
                return name.trim();
            }
            String mfg = props.getString(MidiDeviceInfo.PROPERTY_MANUFACTURER);
            String prod = props.getString(MidiDeviceInfo.PROPERTY_PRODUCT);
            if (prod != null && !prod.trim().isEmpty()) {
                String p = prod.trim();
                if (mfg != null && !mfg.trim().isEmpty() && !p.toLowerCase().startsWith(mfg.trim().toLowerCase())) {
                    return mfg.trim() + " " + p;
                }
                return p;
            }
            if (mfg != null && !mfg.trim().isEmpty()) {
                return mfg.trim() + " MIDI";
            }
        }
        return "USB MIDI #" + info.getId();
    }
}
