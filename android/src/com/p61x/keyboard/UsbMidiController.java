package com.p61x.keyboard;

import android.content.Context;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;

public final class UsbMidiController {
    private Context ctx;
    private EventListener listener;

    public interface EventListener {
        void onMidiUiEvent(JSONObject ev);
        void onPortStatusChanged(String portName);
    }

    private synchronized void handleRawPacket(String sourceName, byte[] data, int offset, int count) {}

    void onEnhancedMidiBytes(String sourceName, byte[] data, int offset, int count) {
        handleRawPacket(sourceName, data, offset, count);
    }

    public void start() {
        try {
            UsbMidiEnhanced.start(this, this.ctx, this.listener);
        } catch (Throwable t) {
            Log.w("P61xConsole", "UsbMidiController.start failed", t);
        }
    }

    public void stop() {
        try {
            UsbMidiEnhanced.stop(this);
        } catch (Throwable t) {
            Log.w("P61xConsole", "UsbMidiController.stop failed", t);
        }
    }

    public String getActivePortName() {
        return UsbMidiEnhanced.getActivePortName(this);
    }

    public JSONArray listInputPortsJson() {
        return UsbMidiEnhanced.listInputPortsJson(this);
    }

    public void selectInputPort(String portId) {
        UsbMidiEnhanced.selectInputPort(this, portId);
    }
}
