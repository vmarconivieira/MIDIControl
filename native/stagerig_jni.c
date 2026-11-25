/*
 * JNI bridge: com.p61x.keyboard.NativeDsp  ->  stagerig_dsp.c public C API.
 * Method names/signatures mirror the NativeDsp class bundled in classes.dex (do not change them).
 */
#include <jni.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct StageRigDSP StageRigDSP;

extern StageRigDSP *stagerig_create(float sample_rate);
extern void stagerig_destroy(StageRigDSP *dsp);
extern int stagerig_start_stream(StageRigDSP *dsp, const char *device_name, double sample_rate,
                                 unsigned long block_size, double *out_latency_ms);
extern void stagerig_stop_stream(StageRigDSP *dsp);
extern void stagerig_get_stream_stats(StageRigDSP *dsp, int *active, int *aborted, uint64_t *cb_count,
                                      uint64_t *xruns, uint64_t *last_cb_ms_ago);
extern int stagerig_load_soundfont(StageRigDSP *dsp, const char *path);
extern int stagerig_unload_soundfont(StageRigDSP *dsp, int sfid);
extern int stagerig_set_zone_program(StageRigDSP *dsp, int zone_idx, int sfid, int bank, int prog);
extern void stagerig_set_zone_volume(StageRigDSP *dsp, int zone_idx, int vol_cc);
extern void stagerig_set_zone_mute(StageRigDSP *dsp, int zone_idx, int muted);
extern void stagerig_set_zone_solo(StageRigDSP *dsp, int zone_idx, int soloed);
extern void stagerig_set_zone_fx(StageRigDSP *dsp, int zone_idx, int is_delay, int val_cc);
extern void stagerig_set_zone_pan(StageRigDSP *dsp, int zone_idx, int pan_cc);
extern void stagerig_set_zone_tone(StageRigDSP *dsp, int zone_idx, int cutoff_cc);
extern void stagerig_set_zone_filter(StageRigDSP *dsp, int zone_idx, int cutoff_cc, int resonance_cc, int tone_cc);
extern void stagerig_set_zone_chorus(StageRigDSP *dsp, int zone_idx, int chorus_cc);
extern void stagerig_set_zone_envelope(StageRigDSP *dsp, int zone_idx, int attack_cc, int release_cc);
extern void stagerig_set_zone_eq(StageRigDSP *dsp, int zone_idx, float b0, float b1, float b2, float b3, float b4);
extern void stagerig_set_zone_params(StageRigDSP *dsp, int zone_idx, int transpose, int key_low, int key_hi,
                                     int vel_low, int vel_hi, int sustain_enable, int expr_enable);
extern void stagerig_set_bpm(StageRigDSP *dsp, float bpm);
extern void stagerig_set_master_fx(StageRigDSP *dsp, float rev_room, float rev_damp, float rev_level,
                                   float dly_feedback, float dly_level);
extern void stagerig_set_masters_state(StageRigDSP *dsp, int synth_vol, int synth_muted, int pad_vol, int pad_muted);
extern void stagerig_set_pad_layer(StageRigDSP *dsp, int layer_idx, const float *interleaved_lr, int frames);
extern void stagerig_set_pad_layers_ex(StageRigDSP *dsp, int playing, float rate, const int *vols,
                                       const int *mutes, int count);
extern void stagerig_set_drum_pad_sample(StageRigDSP *dsp, int pad_idx, const float *interleaved_lr, int frames);
extern void stagerig_set_drum_pad_params(StageRigDSP *dsp, int pad_idx, int vol_cc, int muted, int loop);
extern void stagerig_trigger_drum_pad(StageRigDSP *dsp, int pad_idx, int velocity, int stop_only);
extern void stagerig_note_on(StageRigDSP *dsp, int note, int velocity);
extern void stagerig_note_off(StageRigDSP *dsp, int note);
extern void stagerig_send_performance_cc(StageRigDSP *dsp, int cc_num, int val);
extern void stagerig_pitch_bend(StageRigDSP *dsp, int bend_val);
extern void stagerig_panic(StageRigDSP *dsp);
extern void stagerig_get_telemetry_v2(StageRigDSP *dsp, float *out_zone_peaks, float *out_pad_peaks,
                                      float *out_drum_peaks, float *out_synth_master_peak,
                                      float *out_pad_master_peak, float *out_master_peak, int *out_voices);

#define DSP(p) ((StageRigDSP *)(intptr_t)(p))
#define JNI_FN(name) JNIEXPORT __attribute__((visibility("default"))) Java_com_p61x_keyboard_NativeDsp_##name

JNIEXPORT jlong JNICALL Java_com_p61x_keyboard_NativeDsp_nativeCreate(JNIEnv *env, jclass c, jfloat sr) {
    (void)env; (void)c;
    return (jlong)(intptr_t)stagerig_create(sr);
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeDestroy(JNIEnv *env, jclass c, jlong p) {
    (void)env; (void)c;
    stagerig_destroy(DSP(p));
}

JNIEXPORT jdouble JNICALL Java_com_p61x_keyboard_NativeDsp_nativeStartStream(JNIEnv *env, jclass c, jlong p,
                                                                             jdouble sr, jint block) {
    (void)env; (void)c;
    double lat = 0.0;
    int rc = stagerig_start_stream(DSP(p), "default", sr, (unsigned long)(block > 0 ? block : 256), &lat);
    return rc == 0 ? (lat > 0.0 ? lat : 1.0) : -1.0;
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeStopStream(JNIEnv *env, jclass c, jlong p) {
    (void)env; (void)c;
    stagerig_stop_stream(DSP(p));
}

JNIEXPORT jint JNICALL Java_com_p61x_keyboard_NativeDsp_nativeLoadSoundfont(JNIEnv *env, jclass c, jlong p,
                                                                            jstring path) {
    (void)c;
    if (!path) return -1;
    const char *cs = (*env)->GetStringUTFChars(env, path, NULL);
    if (!cs) return -1;
    int rc = stagerig_load_soundfont(DSP(p), cs);
    (*env)->ReleaseStringUTFChars(env, path, cs);
    return rc;
}

JNIEXPORT jint JNICALL Java_com_p61x_keyboard_NativeDsp_nativeUnloadSoundfont(JNIEnv *env, jclass c, jlong p,
                                                                              jint sfid) {
    (void)env; (void)c;
    return stagerig_unload_soundfont(DSP(p), sfid);
}

JNIEXPORT jint JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneProgram(JNIEnv *env, jclass c, jlong p, jint z,
                                                                             jint sfid, jint bank, jint prog) {
    (void)env; (void)c;
    return stagerig_set_zone_program(DSP(p), z, sfid, bank, prog);
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneVolume(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_volume(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneMute(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_mute(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneSolo(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_solo(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneFx(JNIEnv *env, jclass c, jlong p, jint z, jint isDelay, jint v) {
    (void)env; (void)c; stagerig_set_zone_fx(DSP(p), z, isDelay, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZonePan(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_pan(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneTone(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_tone(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneFilter(JNIEnv *env, jclass c, jlong p, jint z,
                                                                            jint cutoff, jint res, jint tone) {
    (void)env; (void)c; stagerig_set_zone_filter(DSP(p), z, cutoff, res, tone);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneChorus(JNIEnv *env, jclass c, jlong p, jint z, jint v) {
    (void)env; (void)c; stagerig_set_zone_chorus(DSP(p), z, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneEnvelope(JNIEnv *env, jclass c, jlong p, jint z,
                                                                              jint atk, jint rel) {
    (void)env; (void)c; stagerig_set_zone_envelope(DSP(p), z, atk, rel);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneEq(JNIEnv *env, jclass c, jlong p, jint z,
                                                                        jfloat b0, jfloat b1, jfloat b2, jfloat b3, jfloat b4) {
    (void)env; (void)c; stagerig_set_zone_eq(DSP(p), z, b0, b1, b2, b3, b4);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetZoneParams(JNIEnv *env, jclass c, jlong p, jint z,
                                                                            jint transpose, jint keyLow, jint keyHigh,
                                                                            jint velLow, jint velHigh, jint sustain,
                                                                            jint enabled) {
    (void)env; (void)c;
    stagerig_set_zone_params(DSP(p), z, transpose, keyLow, keyHigh, velLow, velHigh, sustain, enabled);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetBpm(JNIEnv *env, jclass c, jlong p, jfloat bpm) {
    (void)env; (void)c; stagerig_set_bpm(DSP(p), bpm);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetMasterFx(JNIEnv *env, jclass c, jlong p, jfloat room,
                                                                          jfloat damp, jfloat level, jfloat fb, jfloat dly) {
    (void)env; (void)c; stagerig_set_master_fx(DSP(p), room, damp, level, fb, dly);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetMastersState(JNIEnv *env, jclass c, jlong p, jint sv,
                                                                              jint sm, jint pv, jint pm) {
    (void)env; (void)c; stagerig_set_masters_state(DSP(p), sv, sm, pv, pm);
}

/* Large float arrays are copied inside the DSP (malloc+memcpy), so read them without an extra JNI copy. */
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetPadLayer(JNIEnv *env, jclass c, jlong p, jint layer,
                                                                          jfloatArray arr, jint frames) {
    (void)c;
    if (!arr || frames <= 0) return;
    jsize len = (*env)->GetArrayLength(env, arr);
    if ((jlong)len < (jlong)frames * 2) return;
    jfloat *data = (*env)->GetPrimitiveArrayCritical(env, arr, NULL);
    if (!data) return;
    stagerig_set_pad_layer(DSP(p), layer, data, frames);
    (*env)->ReleasePrimitiveArrayCritical(env, arr, data, JNI_ABORT);
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetPadLayersEx(JNIEnv *env, jclass c, jlong p, jint playing,
                                                                             jfloat rate, jintArray vols, jintArray mutes) {
    (void)c;
    int v[5] = {0, 0, 0, 0, 0};
    int m[5] = {0, 0, 0, 0, 0};
    int nv = 0, nm = 0;
    if (vols) {
        nv = (int)(*env)->GetArrayLength(env, vols); if (nv > 5) nv = 5;
        if (nv > 0) (*env)->GetIntArrayRegion(env, vols, 0, nv, (jint *)v);
    }
    if (mutes) {
        nm = (int)(*env)->GetArrayLength(env, mutes); if (nm > 5) nm = 5;
        if (nm > 0) (*env)->GetIntArrayRegion(env, mutes, 0, nm, (jint *)m);
    }
    stagerig_set_pad_layers_ex(DSP(p), playing, rate, nv > 0 ? v : NULL, nm > 0 ? m : NULL, 5);
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetDrumPadSample(JNIEnv *env, jclass c, jlong p, jint pad,
                                                                               jfloatArray arr, jint frames) {
    (void)c;
    if (!arr || frames <= 0) {
        stagerig_set_drum_pad_sample(DSP(p), pad, NULL, 0);
        return;
    }
    jsize len = (*env)->GetArrayLength(env, arr);
    if ((jlong)len < (jlong)frames * 2) return;
    jfloat *data = (*env)->GetPrimitiveArrayCritical(env, arr, NULL);
    if (!data) return;
    stagerig_set_drum_pad_sample(DSP(p), pad, data, frames);
    (*env)->ReleasePrimitiveArrayCritical(env, arr, data, JNI_ABORT);
}

JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSetDrumPadParams(JNIEnv *env, jclass c, jlong p, jint pad,
                                                                               jint vol, jint muted, jint loop) {
    (void)env; (void)c; stagerig_set_drum_pad_params(DSP(p), pad, vol, muted, loop);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeTriggerDrumPad(JNIEnv *env, jclass c, jlong p, jint pad,
                                                                             jint vel, jint stopOnly) {
    (void)env; (void)c; stagerig_trigger_drum_pad(DSP(p), pad, vel, stopOnly);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeNoteOn(JNIEnv *env, jclass c, jlong p, jint note, jint vel) {
    (void)env; (void)c; stagerig_note_on(DSP(p), note, vel);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeNoteOff(JNIEnv *env, jclass c, jlong p, jint note) {
    (void)env; (void)c; stagerig_note_off(DSP(p), note);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeSendPerformanceCc(JNIEnv *env, jclass c, jlong p, jint cc, jint v) {
    (void)env; (void)c; stagerig_send_performance_cc(DSP(p), cc, v);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativePitchBend(JNIEnv *env, jclass c, jlong p, jint bend) {
    (void)env; (void)c; stagerig_pitch_bend(DSP(p), bend);
}
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativePanic(JNIEnv *env, jclass c, jlong p) {
    (void)env; (void)c; stagerig_panic(DSP(p));
}

/*
 * nativeGetTelemetry(ptr, zone[4], pad[5], drum[4], misc[6])
 * misc = { synthMasterPeak, padMasterPeak, masterPeak, activeVoices, streamActive(0/1), xrunCount }
 */
JNIEXPORT void JNICALL Java_com_p61x_keyboard_NativeDsp_nativeGetTelemetry(JNIEnv *env, jclass c, jlong p,
                                                                           jfloatArray zone, jfloatArray pad,
                                                                           jfloatArray drum, jfloatArray misc) {
    (void)c;
    StageRigDSP *dsp = DSP(p);
    if (!dsp) return;
    float zp[4] = {0}, pp[5] = {0}, dp[4] = {0};
    float smp = 0.0f, pmp = 0.0f, mp = 0.0f;
    int voices = 0;
    stagerig_get_telemetry_v2(dsp, zp, pp, dp, &smp, &pmp, &mp, &voices);

    int active = 0, aborted = 0;
    uint64_t cbs = 0, xr = 0, ago = 0;
    stagerig_get_stream_stats(dsp, &active, &aborted, &cbs, &xr, &ago);

    if (zone) (*env)->SetFloatArrayRegion(env, zone, 0, 4, zp);
    if (pad) (*env)->SetFloatArrayRegion(env, pad, 0, 5, pp);
    if (drum) (*env)->SetFloatArrayRegion(env, drum, 0, 4, dp);
    if (misc) {
        float m[6];
        m[0] = smp;
        m[1] = pmp;
        m[2] = mp;
        m[3] = (float)voices;
        m[4] = (active && !aborted) ? 1.0f : 0.0f;
        m[5] = (float)xr;
        (*env)->SetFloatArrayRegion(env, misc, 0, 6, m);
    }
}
