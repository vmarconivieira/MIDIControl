/*
 * P61x Console / NumaStandalonePlayer - Native C Real-Time 4-Zone Synth, 5-Layer Worship Pad,
 * 4-Slot Stereo Drum Pads & Studio FX DSP Core (stagerig_dsp.c — v1.3.3)
 *
 * Linked directly against libfluidsynth-3.dll / libfluidsynth.so.3 and portaudio_x64.dll / libportaudio.so.2
 * (Android: libfluidsynth.so + AAudio, see the __ANDROID__ sections and stagerig_jni.c).
 * Features:
 * - Zero-GIL pure C PortAudio real-time callback (WASAPI on Windows / PipeWire-ALSA on Linux)
 * - Wait-free MIDI & Drum trigger event ring buffer
 * - SSE FTZ/DAZ hardware denormal protection + finite/bounds DSP sanitization
 * - Renders 4 independent stereo FluidSynth instrument zones (Zone 1..4) in a single pass
 * - Per-zone 5-Band Studio Biquad EQ (Grave 90Hz, Med-Grave 280Hz, Medio 1kHz, Med-Agudo 3.2kHz, Agudo 8.5kHz)
 * - Per-zone Resonant 2-Pole Low-Pass Cutoff + Resonance + Musical Tone Tilt Shelf
 * - Per-zone Stereo Quadrature LFO Chorus + SoundFont Attack/Release Envelope (CC 73 / CC 72)
 * - Per-zone Equal-Power/Balance Stereo Pan (0..127, 64 = center)
 * - Per-zone Octave/Transpose (-36..+36), Key Split Range, Velocity Range, Mute/Solo
 * - 5-Layer RAM-resident Continuous Worship Pad mixer + seamless pitch crossfade
 * - 4-Slot Stereo Drum Pads (16-voice polyphonic one-shot & loop engine)
 * - Independent Synth Master & Pad Master faders/mutes + atomic VU telemetry
 * - Lush Stereo Cathedral Hall Reverb + BPM-Synced Stereo Ping-Pong Tape Delay + C1 Soft-Knee Master Limiter
 */

#define _GNU_SOURCE
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__)
#include <pmmintrin.h>
#include <xmmintrin.h>
#define STAGERIG_X86 1
#endif

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#define DSP_EXPORT __declspec(dllexport)

/* Minimal self-contained FluidSynth & PortAudio ABI declarations for MinGW-w64 direct DLL linking */
typedef struct _fluid_hashtable_t fluid_settings_t;
typedef struct _fluid_synth_t fluid_synth_t;
enum fluid_log_level { FLUID_PANIC = 0, FLUID_ERR, FLUID_WARN, FLUID_INFO, FLUID_DBG };
typedef void (*fluid_log_function_t)(int level, const char *message, void *data);

fluid_settings_t *new_fluid_settings(void);
void delete_fluid_settings(fluid_settings_t *settings);
int fluid_settings_setnum(fluid_settings_t *settings, const char *name, double val);
int fluid_settings_setint(fluid_settings_t *settings, const char *name, int val);
fluid_log_function_t fluid_set_log_function(int level, fluid_log_function_t fun, void *data);

fluid_synth_t *new_fluid_synth(fluid_settings_t *settings);
void delete_fluid_synth(fluid_synth_t *synth);
int fluid_synth_sfload(fluid_synth_t *synth, const char *filename, int reset_presets);
int fluid_synth_sfunload(fluid_synth_t *synth, int id, int reset_presets);
int fluid_synth_program_select(fluid_synth_t *synth, int chan, int sfont_id, unsigned int bank_num, unsigned int preset_num);
int fluid_synth_cc(fluid_synth_t *synth, int chan, int num, int val);
int fluid_synth_noteon(fluid_synth_t *synth, int chan, int key, int vel);
int fluid_synth_noteoff(fluid_synth_t *synth, int chan, int key);
int fluid_synth_pitch_bend(fluid_synth_t *synth, int chan, int val);
int fluid_synth_all_notes_off(fluid_synth_t *synth, int chan);
int fluid_synth_all_sounds_off(fluid_synth_t *synth, int chan);
int fluid_synth_process(fluid_synth_t *synth, int len, int nfx, float *fx[], int nout, float *out[]);
int fluid_synth_get_active_voice_count(fluid_synth_t *synth);
int fluid_synth_set_interp_method(fluid_synth_t *synth, int chan, int interp_method);
int fluid_synth_set_polyphony(fluid_synth_t *synth, int polyphony);
void fluid_synth_set_sample_rate(fluid_synth_t *synth, float sample_rate);

typedef int PaError;
typedef int PaDeviceIndex;
typedef int PaHostApiIndex;
typedef double PaTime;
typedef unsigned long PaSampleFormat;
typedef unsigned long PaStreamFlags;
typedef unsigned long PaStreamCallbackFlags;
typedef void PaStream;

#define paNoError (0)
#define paNoDevice ((PaDeviceIndex)-1)
#define paFloat32 ((PaSampleFormat)0x00000001)
#define paNoFlag ((PaStreamFlags)0)
#define paOutputUnderflow ((PaStreamCallbackFlags)0x00000004)
#define paOutputOverflow ((PaStreamCallbackFlags)0x00000008)
#define paContinue (0)

typedef struct PaDeviceInfo {
    int structVersion;
    const char *name;
    PaHostApiIndex hostApi;
    int maxInputChannels;
    int maxOutputChannels;
    PaTime defaultLowInputLatency;
    PaTime defaultLowOutputLatency;
    PaTime defaultHighInputLatency;
    PaTime defaultHighOutputLatency;
    double defaultSampleRate;
} PaDeviceInfo;

typedef struct PaStreamParameters {
    PaDeviceIndex device;
    int channelCount;
    PaSampleFormat sampleFormat;
    PaTime suggestedLatency;
    void *hostApiSpecificStreamInfo;
} PaStreamParameters;

typedef struct PaStreamCallbackTimeInfo {
    PaTime inputBufferAdcTime;
    PaTime currentTime;
    PaTime outputBufferDacTime;
} PaStreamCallbackTimeInfo;

typedef struct PaStreamInfo {
    int structVersion;
    PaTime inputLatency;
    PaTime outputLatency;
    double sampleRate;
} PaStreamInfo;

typedef int PaStreamCallback(
    const void *input,
    void *output,
    unsigned long frameCount,
    const PaStreamCallbackTimeInfo *timeInfo,
    PaStreamCallbackFlags statusFlags,
    void *userData
);
typedef void PaStreamFinishedCallback(void *userData);

PaError Pa_Initialize(void);
PaError Pa_Terminate(void);
PaDeviceIndex Pa_GetDeviceCount(void);
PaDeviceIndex Pa_GetDefaultOutputDevice(void);
const PaDeviceInfo *Pa_GetDeviceInfo(PaDeviceIndex device);
PaError Pa_OpenStream(
    PaStream **stream,
    const PaStreamParameters *inputParameters,
    const PaStreamParameters *outputParameters,
    double sampleRate,
    unsigned long framesPerBuffer,
    PaStreamFlags streamFlags,
    PaStreamCallback *streamCallback,
    void *userData
);
PaError Pa_SetStreamFinishedCallback(PaStream *stream, PaStreamFinishedCallback *streamFinishedCallback);
PaError Pa_StartStream(PaStream *stream);
PaError Pa_AbortStream(PaStream *stream);
PaError Pa_CloseStream(PaStream *stream);
PaError Pa_IsStreamActive(PaStream *stream);
const PaStreamInfo *Pa_GetStreamInfo(PaStream *stream);

typedef CRITICAL_SECTION rig_mutex_t;
#define rig_mutex_init(m, ...) InitializeCriticalSection(m)
#define rig_mutex_lock(m) EnterCriticalSection(m)
#define rig_mutex_unlock(m) LeaveCriticalSection(m)
#define rig_mutex_destroy(m) DeleteCriticalSection(m)
#define rig_mutex_trylock(m) (TryEnterCriticalSection(m) != 0 ? 0 : -1)

static SRWLOCK g_pa_init_lock = SRWLOCK_INIT;
#define global_lock_acquire() AcquireSRWLockExclusive(&g_pa_init_lock)
#define global_lock_release() ReleaseSRWLockExclusive(&g_pa_init_lock)

static inline uint64_t mono_ns_now(void) {
    static LARGE_INTEGER freq;
    static int freq_inited = 0;
    if (!freq_inited) {
        QueryPerformanceFrequency(&freq);
        freq_inited = 1;
    }
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return (uint64_t)((counter.QuadPart * 1000000000ULL) / freq.QuadPart);
}
#elif defined(__ANDROID__)
#include <android/log.h>
#include <dlfcn.h>
#include <aaudio/AAudio.h>
#include <pthread.h>
#include <sched.h>
#define DSP_EXPORT __attribute__((visibility("default")))
#define STAGERIG_LOGW(...) __android_log_print(ANDROID_LOG_WARN, "P61xDSP", __VA_ARGS__)
#define STAGERIG_LOGI(...) __android_log_print(ANDROID_LOG_INFO, "P61xDSP", __VA_ARGS__)

/* Minimal self-contained FluidSynth ABI declarations (links against the bundled libfluidsynth.so) */
typedef struct _fluid_hashtable_t fluid_settings_t;
typedef struct _fluid_synth_t fluid_synth_t;
enum fluid_log_level { FLUID_PANIC = 0, FLUID_ERR, FLUID_WARN, FLUID_INFO, FLUID_DBG };
typedef void (*fluid_log_function_t)(int level, const char *message, void *data);

fluid_settings_t *new_fluid_settings(void);
void delete_fluid_settings(fluid_settings_t *settings);
int fluid_settings_setnum(fluid_settings_t *settings, const char *name, double val);
int fluid_settings_setint(fluid_settings_t *settings, const char *name, int val);
fluid_log_function_t fluid_set_log_function(int level, fluid_log_function_t fun, void *data);

fluid_synth_t *new_fluid_synth(fluid_settings_t *settings);
void delete_fluid_synth(fluid_synth_t *synth);
int fluid_synth_sfload(fluid_synth_t *synth, const char *filename, int reset_presets);
int fluid_synth_sfunload(fluid_synth_t *synth, int id, int reset_presets);
int fluid_synth_program_select(fluid_synth_t *synth, int chan, int sfont_id, unsigned int bank_num, unsigned int preset_num);
int fluid_synth_cc(fluid_synth_t *synth, int chan, int num, int val);
int fluid_synth_noteon(fluid_synth_t *synth, int chan, int key, int vel);
int fluid_synth_noteoff(fluid_synth_t *synth, int chan, int key);
int fluid_synth_pitch_bend(fluid_synth_t *synth, int chan, int val);
int fluid_synth_all_notes_off(fluid_synth_t *synth, int chan);
int fluid_synth_all_sounds_off(fluid_synth_t *synth, int chan);
int fluid_synth_process(fluid_synth_t *synth, int len, int nfx, float *fx[], int nout, float *out[]);
int fluid_synth_get_active_voice_count(fluid_synth_t *synth);
int fluid_synth_set_interp_method(fluid_synth_t *synth, int chan, int interp_method);
int fluid_synth_set_polyphony(fluid_synth_t *synth, int polyphony);
void fluid_synth_set_sample_rate(fluid_synth_t *synth, float sample_rate);

typedef AAudioStream PaStream;
typedef pthread_mutex_t rig_mutex_t;
#define rig_mutex_init(m, ...) pthread_mutex_init(m, NULL)
#define rig_mutex_lock(m) pthread_mutex_lock(m)
#define rig_mutex_unlock(m) pthread_mutex_unlock(m)
#define rig_mutex_destroy(m) pthread_mutex_destroy(m)
#define rig_mutex_trylock(m) pthread_mutex_trylock(m)
#define global_lock_acquire() ((void)0)
#define global_lock_release() ((void)0)

static inline uint64_t mono_ns_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
#else
#include <fluidsynth.h>
#include <portaudio.h>
#define DSP_EXPORT __attribute__((visibility("default")))
#include <pthread.h>
#include <sched.h>
#ifdef __APPLE__
#include <pthread/qos.h>
#endif
typedef pthread_mutex_t rig_mutex_t;
#define rig_mutex_init(m, ...) pthread_mutex_init(m, NULL)
#define rig_mutex_lock(m) pthread_mutex_lock(m)
#define rig_mutex_unlock(m) pthread_mutex_unlock(m)
#define rig_mutex_destroy(m) pthread_mutex_destroy(m)
#define rig_mutex_trylock(m) pthread_mutex_trylock(m)

static pthread_mutex_t g_pa_init_lock = PTHREAD_MUTEX_INITIALIZER;
#define global_lock_acquire() pthread_mutex_lock(&g_pa_init_lock)
#define global_lock_release() pthread_mutex_unlock(&g_pa_init_lock)

static inline uint64_t mono_ns_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define NUM_ZONES 4
#define NUM_EQ_BANDS 5
#define NUM_PAD_LAYERS 5
#define NUM_DRUM_PADS 4
#define MAX_DRUM_VOICES 16
#define CHORUS_BUF_SIZE 2048
#define CHORUS_BUF_MASK (CHORUS_BUF_SIZE - 1)
#define MAX_BLOCK_FRAMES 4096
#define LIMITER_THRESH 0.92f
#define DELAY_BUF_SIZE 131072 /* ~2.97 seconds at 44.1kHz per stereo channel */
#define DELAY_BUF_MASK (DELAY_BUF_SIZE - 1)
#define EVENT_RING_CAP 2048
#define EVENT_RING_MASK (EVENT_RING_CAP - 1)

/* Freeverb-style Stereo Cathedral Hall Reverb constants (tuned for 44.1kHz) */
#define NUM_COMBS 8
#define NUM_ALLPASS 4
#define MAX_COMB_SIZE 2048
#define MAX_ALLPASS_SIZE 1024

static const int COMB_TUNINGS_L[NUM_COMBS] = {1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617};
static const int COMB_TUNINGS_R[NUM_COMBS] = {1139, 1211, 1300, 1379, 1445, 1514, 1580, 1640};
static const int ALLPASS_TUNINGS_L[NUM_ALLPASS] = {556, 441, 341, 225};
static const int ALLPASS_TUNINGS_R[NUM_ALLPASS] = {579, 464, 364, 248};

/* 5-Band EQ center frequencies (Hz): Grave, Med-Grave, Medio, Med-Agudo, Agudo */
static const double EQ_BAND_FREQS[NUM_EQ_BANDS] = {90.0, 280.0, 1000.0, 3200.0, 8500.0};

typedef enum {
    EVT_NOTE_ON = 1,
    EVT_NOTE_OFF = 2,
    EVT_PERF_CC = 3,
    EVT_PITCH_BEND = 4,
    EVT_PANIC = 5,
    EVT_ZONE_FLUSH_NOTES = 6,
    EVT_DRUM_TRIGGER = 7
} MidiEventType;

typedef struct {
    uint8_t type;
    uint8_t ch;
    int16_t data1;
    int16_t data2;
} MidiEvent;

typedef struct {
    float buf[MAX_COMB_SIZE];
    int size;
    int idx;
    float filterstore;
} CombFilter;

typedef struct {
    float buf[MAX_ALLPASS_SIZE];
    int size;
    int idx;
} AllpassFilter;

typedef struct {
    float b0, b1, b2, a1, a2;
    float z1_l, z2_l;
    float z1_r, z2_r;
    int active;
} StereoBiquad;

typedef struct {
    int enabled;
    int muted;
    int soloed;
    int volume_cc;      /* 0..127 */
    int reverb_cc;      /* 0..127 */
    int delay_cc;       /* 0..127 */
    int chorus_cc;      /* 0..127 */
    int pan_cc;         /* 0..127 (64 = center) */
    int cutoff_cc;      /* 0..127 (127 = wide open) */
    int resonance_cc;   /* 0..127 (0 = flat Q=0.707) */
    int tone_cc;        /* 0..127 (64 = neutral) */
    int attack_cc;      /* 0..127 */
    int release_cc;     /* 0..127 */
    int eq_tenths_db[NUM_EQ_BANDS]; /* -120 .. +120 (tenths of dB) */
    int filters_dirty;

    int transpose;      /* -36..+36 semitones */
    int key_low;        /* 0..127 */
    int key_hi;         /* 0..127 */
    int vel_low;        /* 0..127 */
    int vel_hi;         /* 0..127 */
    int sustain_enable; /* 0 or 1 */
    int expr_enable;    /* 0 or 1 */

    int sfid;
    int bank;
    int prog;

    float cur_gain;
    float cur_rev_send;
    float cur_dly_send;
    float cur_chorus_mix;
    float cur_pan_l;
    float cur_pan_r;

    float chorus_buf_l[CHORUS_BUF_SIZE];
    float chorus_buf_r[CHORUS_BUF_SIZE];
    int chorus_idx;
    double chorus_phase;

    StereoBiquad eq_biquads[NUM_EQ_BANDS];
    StereoBiquad lpf_biquad;
    StereoBiquad tone_biquad;

    uint32_t peak_vu_bits;

    /* Owned by RT audio consumer thread */
    int8_t active_notes[128];
} ZoneState;

typedef struct {
    int active;
    int pad_idx;
    int pos;
    float vel_gain;
} DrumVoice;

typedef struct {
    /* Non-RT serialization (SF2 loads, stream open/close, ring producer lock, drum sample swap lock) */
    rig_mutex_t sf_lock;
    rig_mutex_t stream_lock;
    rig_mutex_t event_q_lock;
    rig_mutex_t drum_lock;

    fluid_settings_t *settings;
    fluid_synth_t *synth;
    float sample_rate;

    /* Wait-free MIDI event ring consumed on audio render thread */
    MidiEvent event_ring[EVENT_RING_CAP];
    uint32_t event_head;
    uint32_t event_tail;

    ZoneState zones[NUM_ZONES];
    int any_solo;

    /* Scratch buffers for fluid_synth_process 4 stereo buses (8 mono float buffers) */
    float zone_bufs[NUM_ZONES * 2][MAX_BLOCK_FRAMES];

    /* Lush Stereo Cathedral Reverb State */
    CombFilter combs_l[NUM_COMBS];
    CombFilter combs_r[NUM_COMBS];
    AllpassFilter allpass_l[NUM_ALLPASS];
    AllpassFilter allpass_r[NUM_ALLPASS];
    uint32_t rev_room_bits;
    uint32_t rev_damp_bits;
    uint32_t rev_level_bits;

    /* BPM-Synced Stereo Ping-Pong Tape Delay State */
    float delay_buf_l[DELAY_BUF_SIZE];
    float delay_buf_r[DELAY_BUF_SIZE];
    int delay_write_idx;
    float bpm;
    int delay_samples_l;
    int delay_samples_r;
    uint32_t dly_fb_bits;
    uint32_t dly_lvl_bits;
    float delay_lp_l;
    float delay_lp_r;

    /* RAM-Resident 5-Layer Continuous Worship Pad & Dual Master State */
    float *pad_bufs[NUM_PAD_LAYERS];
    int pad_lengths[NUM_PAD_LAYERS];
    int pad_playing;
    int pad_layer_vols[NUM_PAD_LAYERS];
    int pad_layer_mutes[NUM_PAD_LAYERS];
    uint32_t pad_rate_bits;
    uint32_t pad_rate_ver;
    uint32_t seen_pad_rate_ver;

    double pad_pos_a;
    double pad_pos_b;
    double pad_rate_a;
    double pad_rate_b;
    float pad_xfade_mix;
    float pad_env;
    float cur_pad_gains[NUM_PAD_LAYERS];

    /* 4-Slot Stereo Drum Pads */
    float *drum_bufs[NUM_DRUM_PADS];
    int drum_lengths[NUM_DRUM_PADS];
    int drum_vols[NUM_DRUM_PADS];
    int drum_mutes[NUM_DRUM_PADS];
    int drum_loops[NUM_DRUM_PADS];
    DrumVoice drum_voices[MAX_DRUM_VOICES];
    uint32_t drum_peak_bits[NUM_DRUM_PADS];

    /* Independent Synth & Pad Masters */
    int synth_master_vol;
    int synth_master_muted;
    int pad_master_vol;
    int pad_master_muted;
    float cur_synth_mg;
    float cur_pad_mg;

    /* Atomic telemetry & stream health metrics */
    uint32_t pad_peak_bits[NUM_PAD_LAYERS];
    uint32_t synth_master_peak_bits;
    uint32_t pad_master_peak_bits;
    uint32_t master_peak_bits;
    int active_voices;

    PaStream *pa_stream;
    int stream_active;
    int stream_aborted;
    int shutting_down;
    int rt_thread_inited;
    uint64_t callback_count;
    uint64_t xrun_count;
    uint64_t stream_started_ns;
    uint64_t last_callback_ns;

    /* Stream tuning / adaptive quality governor (Android AAudio path) */
    int req_sample_rate;
    double pad_sr_comp;          /* pad buffers were decoded at req_sample_rate */
    int aa_burst;
    int aa_capacity;
    int aa_max_buf;
    int aa_last_xruns;
    float load_ema;              /* render time / available time, 0..1+ */
    int high_load_cbs;
    int degrade_req;
    int quality_level;           /* 0 = best, 1 = linear interpolation + reduced polyphony */

    /* Master peak limiter state (audio thread only) */
    float lim_gain;
} StageRigDSP;

/* Global PortAudio initialization refcount */
static int g_pa_refcount = 0;

static inline uint32_t f2u(float f) {
    uint32_t u;
    memcpy(&u, &f, sizeof(u));
    return u;
}

static inline float u2f(uint32_t u) {
    float f;
    memcpy(&f, &u, sizeof(f));
    return f;
}

static void atomic_max_float_bits(uint32_t *bits_ptr, float val) {
    uint32_t expected = __atomic_load_n(bits_ptr, __ATOMIC_RELAXED);
    for (;;) {
        float cur = u2f(expected);
        if (val <= cur) return;
        uint32_t desired = f2u(val);
        if (__atomic_compare_exchange_n(bits_ptr, &expected, desired, 0, __ATOMIC_RELEASE, __ATOMIC_RELAXED)) {
            return;
        }
    }
}

/* =========================================================================
 * FINITE / ANTI-DENORMAL / FAILSAFE AUDIO GUARDS
 * ========================================================================= */

static inline void enable_rt_thread_mode(void) {
#if defined(STAGERIG_X86)
    _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON);
    _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_ON);
#elif defined(__aarch64__) || defined(__arm64__)
    {
        uint64_t fpcr;
        __asm__ __volatile__("mrs %0, fpcr" : "=r"(fpcr));
        fpcr |= (1ULL << 24); /* FZ: flush-to-zero */
        __asm__ __volatile__("msr fpcr, %0" : : "r"(fpcr));
    }
#endif
#ifdef _WIN32
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);
#elif defined(__APPLE__)
    (void)pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
#elif defined(__ANDROID__)
    /* AAudio already runs the data callback on a high-priority thread; FTZ above is what matters. */
#else
    struct sched_param sp;
    memset(&sp, 0, sizeof(sp));
    sp.sched_priority = 5;
    (void)pthread_setschedparam(pthread_self(), SCHED_RR, &sp);
#endif
}

static inline float sanitize_audio(float x, float limit) {
    if (!isfinite(x)) return 0.0f;
    if (x > limit) return limit;
    if (x < -limit) return -limit;
    return (fabsf(x) < 1e-18f) ? 0.0f : x;
}

/* =========================================================================
 * RBJ BIQUAD COEFFICIENT CALCULATORS (DOUBLE PRECISION -> FLOAT)
 * ========================================================================= */

static void biquad_reset_state(StereoBiquad *bq) {
    bq->z1_l = bq->z2_l = 0.0f;
    bq->z1_r = bq->z2_r = 0.0f;
}

static void biquad_commit(StereoBiquad *bq, double b0, double b1, double b2, double a0, double a1, double a2) {
    if (!isfinite(a0) || fabs(a0) < 1e-12) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    float fb0 = (float)(b0 / a0);
    float fb1 = (float)(b1 / a0);
    float fb2 = (float)(b2 / a0);
    float fa1 = (float)(a1 / a0);
    float fa2 = (float)(a2 / a0);
    if (!isfinite(fb0) || !isfinite(fb1) || !isfinite(fb2) || !isfinite(fa1) || !isfinite(fa2)) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    bq->b0 = fb0;
    bq->b1 = fb1;
    bq->b2 = fb2;
    bq->a1 = fa1;
    bq->a2 = fa2;
    bq->active = 1;
}

static void biquad_set_low_shelf(StereoBiquad *bq, double sr, double freq, double gain_db, double slope) {
    if (fabs(gain_db) < 0.1 || sr < 8000.0) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    if (freq < 20.0) freq = 20.0;
    if (freq > sr * 0.42) freq = sr * 0.42;
    double A = pow(10.0, gain_db / 40.0);
    double w0 = 2.0 * M_PI * freq / sr;
    double cosw0 = cos(w0);
    double sinw0 = sin(w0);
    double alpha = (sinw0 / 2.0) * sqrt(fmax(0.01, (A + 1.0 / A) * (1.0 / slope - 1.0) + 2.0));
    double sqA2a = 2.0 * sqrt(A) * alpha;

    double b0 = A * ((A + 1.0) - (A - 1.0) * cosw0 + sqA2a);
    double b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cosw0);
    double b2 = A * ((A + 1.0) - (A - 1.0) * cosw0 - sqA2a);
    double a0 = (A + 1.0) + (A - 1.0) * cosw0 + sqA2a;
    double a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cosw0);
    double a2 = (A + 1.0) + (A - 1.0) * cosw0 - sqA2a;
    biquad_commit(bq, b0, b1, b2, a0, a1, a2);
}

static void biquad_set_high_shelf(StereoBiquad *bq, double sr, double freq, double gain_db, double slope) {
    if (fabs(gain_db) < 0.1 || sr < 8000.0) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    if (freq < 20.0) freq = 20.0;
    if (freq > sr * 0.42) freq = sr * 0.42;
    double A = pow(10.0, gain_db / 40.0);
    double w0 = 2.0 * M_PI * freq / sr;
    double cosw0 = cos(w0);
    double sinw0 = sin(w0);
    double alpha = (sinw0 / 2.0) * sqrt(fmax(0.01, (A + 1.0 / A) * (1.0 / slope - 1.0) + 2.0));
    double sqA2a = 2.0 * sqrt(A) * alpha;

    double b0 = A * ((A + 1.0) + (A - 1.0) * cosw0 + sqA2a);
    double b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cosw0);
    double b2 = A * ((A + 1.0) + (A - 1.0) * cosw0 - sqA2a);
    double a0 = (A + 1.0) - (A - 1.0) * cosw0 + sqA2a;
    double a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cosw0);
    double a2 = (A + 1.0) - (A - 1.0) * cosw0 - sqA2a;
    biquad_commit(bq, b0, b1, b2, a0, a1, a2);
}

static void biquad_set_peaking(StereoBiquad *bq, double sr, double freq, double gain_db, double q) {
    if (fabs(gain_db) < 0.1 || sr < 8000.0) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    if (freq < 20.0) freq = 20.0;
    if (freq > sr * 0.42) freq = sr * 0.42;
    double A = pow(10.0, gain_db / 40.0);
    double w0 = 2.0 * M_PI * freq / sr;
    double cosw0 = cos(w0);
    double sinw0 = sin(w0);
    double alpha = sinw0 / (2.0 * q);

    double b0 = 1.0 + alpha * A;
    double b1 = -2.0 * cosw0;
    double b2 = 1.0 - alpha * A;
    double a0 = 1.0 + alpha / A;
    double a1 = -2.0 * cosw0;
    double a2 = 1.0 - alpha / A;
    biquad_commit(bq, b0, b1, b2, a0, a1, a2);
}

static void biquad_set_lowpass(StereoBiquad *bq, double sr, int cutoff_cc, int res_cc) {
    if ((cutoff_cc >= 125 && res_cc <= 10) || sr < 8000.0) {
        bq->active = 0;
        biquad_reset_state(bq);
        return;
    }
    double norm_c = (double)cutoff_cc / 127.0;
    double freq = 160.0 * pow(115.0, norm_c); /* 160 Hz .. 18.4 kHz */
    if (freq > sr * 0.42) freq = sr * 0.42;
    double q = 0.707 + ((double)res_cc / 127.0) * 3.8;

    double w0 = 2.0 * M_PI * freq / sr;
    double cosw0 = cos(w0);
    double sinw0 = sin(w0);
    double alpha = sinw0 / (2.0 * q);

    double b0 = (1.0 - cosw0) * 0.5;
    double b1 = 1.0 - cosw0;
    double b2 = (1.0 - cosw0) * 0.5;
    double a0 = 1.0 + alpha;
    double a1 = -2.0 * cosw0;
    double a2 = 1.0 - alpha;
    biquad_commit(bq, b0, b1, b2, a0, a1, a2);
}

static void update_zone_filters(ZoneState *zs, double sr) {
    for (int b = 0; b < NUM_EQ_BANDS; b++) {
        double db = (double)__atomic_load_n(&zs->eq_tenths_db[b], __ATOMIC_ACQUIRE) * 0.1;
        if (b == 0) {
            biquad_set_low_shelf(&zs->eq_biquads[b], sr, EQ_BAND_FREQS[b], db, 0.85);
        } else if (b == NUM_EQ_BANDS - 1) {
            biquad_set_high_shelf(&zs->eq_biquads[b], sr, EQ_BAND_FREQS[b], db, 0.85);
        } else {
            biquad_set_peaking(&zs->eq_biquads[b], sr, EQ_BAND_FREQS[b], db, 1.05);
        }
    }

    int cut_cc = __atomic_load_n(&zs->cutoff_cc, __ATOMIC_ACQUIRE);
    int res_cc = __atomic_load_n(&zs->resonance_cc, __ATOMIC_ACQUIRE);
    biquad_set_lowpass(&zs->lpf_biquad, sr, cut_cc, res_cc);

    int tone_cc = __atomic_load_n(&zs->tone_cc, __ATOMIC_ACQUIRE);
    if (abs(tone_cc - 64) <= 1) {
        zs->tone_biquad.active = 0;
        biquad_reset_state(&zs->tone_biquad);
    } else {
        double tone_norm = (double)(tone_cc - 64) / 63.0; /* -1.0 .. +1.0 */
        double tone_db = (tone_norm < 0.0) ? (tone_norm * 9.5) : (tone_norm * 7.5);
        biquad_set_high_shelf(&zs->tone_biquad, sr, 2200.0, tone_db, 0.75);
    }
}

static inline void process_stereo_biquad(StereoBiquad *bq, float *l, float *r) {
    float xl = isfinite(*l) ? *l : 0.0f;
    float yl = bq->b0 * xl + bq->z1_l;
    bq->z1_l = bq->b1 * xl - bq->a1 * yl + bq->z2_l;
    bq->z2_l = bq->b2 * xl - bq->a2 * yl;
    if (!isfinite(yl) || !isfinite(bq->z1_l) || !isfinite(bq->z2_l) || fabsf(yl) > 16.0f) {
        yl = xl;
        bq->z1_l = bq->z2_l = 0.0f;
    } else {
        if (fabsf(bq->z1_l) < 1e-18f) bq->z1_l = 0.0f;
        if (fabsf(bq->z2_l) < 1e-18f) bq->z2_l = 0.0f;
    }
    *l = yl;

    float xr = isfinite(*r) ? *r : 0.0f;
    float yr = bq->b0 * xr + bq->z1_r;
    bq->z1_r = bq->b1 * xr - bq->a1 * yr + bq->z2_r;
    bq->z2_r = bq->b2 * xr - bq->a2 * yr;
    if (!isfinite(yr) || !isfinite(bq->z1_r) || !isfinite(bq->z2_r) || fabsf(yr) > 16.0f) {
        yr = xr;
        bq->z1_r = bq->z2_r = 0.0f;
    } else {
        if (fabsf(bq->z1_r) < 1e-18f) bq->z1_r = 0.0f;
        if (fabsf(bq->z2_r) < 1e-18f) bq->z2_r = 0.0f;
    }
    *r = yr;
}

static void clear_reverb_buffers(StageRigDSP *dsp) {
    for (int i = 0; i < NUM_COMBS; i++) {
        memset(dsp->combs_l[i].buf, 0, sizeof(dsp->combs_l[i].buf));
        dsp->combs_l[i].size = COMB_TUNINGS_L[i];
        dsp->combs_l[i].idx = 0;
        dsp->combs_l[i].filterstore = 0.0f;

        memset(dsp->combs_r[i].buf, 0, sizeof(dsp->combs_r[i].buf));
        dsp->combs_r[i].size = COMB_TUNINGS_R[i];
        dsp->combs_r[i].idx = 0;
        dsp->combs_r[i].filterstore = 0.0f;
    }
    for (int i = 0; i < NUM_ALLPASS; i++) {
        memset(dsp->allpass_l[i].buf, 0, sizeof(dsp->allpass_l[i].buf));
        dsp->allpass_l[i].size = ALLPASS_TUNINGS_L[i];
        dsp->allpass_l[i].idx = 0;

        memset(dsp->allpass_r[i].buf, 0, sizeof(dsp->allpass_r[i].buf));
        dsp->allpass_r[i].size = ALLPASS_TUNINGS_R[i];
        dsp->allpass_r[i].idx = 0;
    }
}

static void init_reverb(StageRigDSP *dsp) {
    __atomic_store_n(&dsp->rev_room_bits, f2u(0.84f), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->rev_damp_bits, f2u(0.28f), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->rev_level_bits, f2u(1.10f), __ATOMIC_RELEASE);
    clear_reverb_buffers(dsp);
}

static void update_delay_timing(StageRigDSP *dsp, float bpm) {
    if (bpm < 30.0f) bpm = 30.0f;
    if (bpm > 260.0f) bpm = 260.0f;
    dsp->bpm = bpm;
    float quarter_sec = 60.0f / bpm;
    int samp_l = (int)(quarter_sec * 0.75f * dsp->sample_rate);
    int samp_r = (int)(quarter_sec * 1.00f * dsp->sample_rate);
    if (samp_l < 1024) samp_l = 1024;
    if (samp_l >= DELAY_BUF_SIZE - 256) samp_l = DELAY_BUF_SIZE - 256;
    if (samp_r < 1024) samp_r = 1024;
    if (samp_r >= DELAY_BUF_SIZE - 256) samp_r = DELAY_BUF_SIZE - 256;
    __atomic_store_n(&dsp->delay_samples_l, samp_l, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->delay_samples_r, samp_r, __ATOMIC_RELEASE);
}

static void refresh_any_solo(StageRigDSP *dsp) {
    int s = 0;
    for (int z = 0; z < NUM_ZONES; z++) {
        if (__atomic_load_n(&dsp->zones[z].soloed, __ATOMIC_ACQUIRE)) {
            s = 1;
            break;
        }
    }
    __atomic_store_n(&dsp->any_solo, s, __ATOMIC_RELEASE);
}

/* =========================================================================
 * WAIT-FREE MIDI EVENT RING PRODUCER & AUDIO-THREAD CONSUMER
 * ========================================================================= */

static void rt_enqueue_event(StageRigDSP *dsp, uint8_t type, uint8_t ch, int16_t d1, int16_t d2) {
    if (!dsp || __atomic_load_n(&dsp->shutting_down, __ATOMIC_ACQUIRE)) return;
    rig_mutex_lock(&dsp->event_q_lock);
    uint32_t head = __atomic_load_n(&dsp->event_head, __ATOMIC_RELAXED);
    uint32_t tail = __atomic_load_n(&dsp->event_tail, __ATOMIC_ACQUIRE);
    if ((head - tail) < EVENT_RING_CAP) {
        dsp->event_ring[head & EVENT_RING_MASK].type = type;
        dsp->event_ring[head & EVENT_RING_MASK].ch = ch;
        dsp->event_ring[head & EVENT_RING_MASK].data1 = d1;
        dsp->event_ring[head & EVENT_RING_MASK].data2 = d2;
        __atomic_store_n(&dsp->event_head, head + 1U, __ATOMIC_RELEASE);
    }
    rig_mutex_unlock(&dsp->event_q_lock);
}

static void flush_zone_notes_on_rt(StageRigDSP *dsp, int z) {
    if (z < 0 || z >= NUM_ZONES || !dsp->synth) return;
    ZoneState *zs = &dsp->zones[z];
    fluid_synth_cc(dsp->synth, z, 64, 0);
    for (int k = 0; k < 128; k++) {
        if (zs->active_notes[k] >= 0) {
            fluid_synth_noteoff(dsp->synth, z, zs->active_notes[k]);
            zs->active_notes[k] = -1;
        }
    }
}

static void drain_event_ring(StageRigDSP *dsp) {
    uint32_t head = __atomic_load_n(&dsp->event_head, __ATOMIC_ACQUIRE);
    uint32_t tail = dsp->event_tail;
    while (tail != head) {
        MidiEvent e = dsp->event_ring[tail & EVENT_RING_MASK];
        tail++;

        switch (e.type) {
            case EVT_NOTE_ON: {
                int note = e.data1;
                int velocity = e.data2;
                if (note < 0 || note > 127) break;
                if (velocity <= 0) {
                    for (int z = 0; z < NUM_ZONES; z++) {
                        int8_t played = dsp->zones[z].active_notes[note];
                        if (played >= 0) {
                            fluid_synth_noteoff(dsp->synth, z, played);
                            dsp->zones[z].active_notes[note] = -1;
                        }
                    }
                    break;
                }
                if (velocity > 127) velocity = 127;
                for (int z = 0; z < NUM_ZONES; z++) {
                    ZoneState *zs = &dsp->zones[z];
                    int sfid = __atomic_load_n(&zs->sfid, __ATOMIC_ACQUIRE);
                    if (sfid <= 0) continue;
                    int kl = __atomic_load_n(&zs->key_low, __ATOMIC_ACQUIRE);
                    int kh = __atomic_load_n(&zs->key_hi, __ATOMIC_ACQUIRE);
                    int vl = __atomic_load_n(&zs->vel_low, __ATOMIC_ACQUIRE);
                    int vh = __atomic_load_n(&zs->vel_hi, __ATOMIC_ACQUIRE);
                    if (note < kl || note > kh) continue;
                    if (velocity < vl || velocity > vh) continue;

                    if (zs->active_notes[note] >= 0) {
                        fluid_synth_noteoff(dsp->synth, z, zs->active_notes[note]);
                        zs->active_notes[note] = -1;
                    }
                    int tr = __atomic_load_n(&zs->transpose, __ATOMIC_ACQUIRE);
                    int target_note = note + tr;
                    if (target_note >= 0 && target_note <= 127) {
                        fluid_synth_noteon(dsp->synth, z, target_note, velocity);
                        zs->active_notes[note] = (int8_t)target_note;
                    }
                }
                break;
            }
            case EVT_NOTE_OFF: {
                int note = e.data1;
                if (note < 0 || note > 127) break;
                for (int z = 0; z < NUM_ZONES; z++) {
                    ZoneState *zs = &dsp->zones[z];
                    int8_t played = zs->active_notes[note];
                    if (played >= 0) {
                        fluid_synth_noteoff(dsp->synth, z, played);
                        zs->active_notes[note] = -1;
                    } else {
                        int fallback = note + __atomic_load_n(&zs->transpose, __ATOMIC_ACQUIRE);
                        if (fallback >= 0 && fallback <= 127) {
                            fluid_synth_noteoff(dsp->synth, z, fallback);
                        }
                    }
                }
                break;
            }
            case EVT_PERF_CC: {
                int cc_num = e.data1;
                int val = e.data2;
                if (val < 0) val = 0;
                if (val > 127) val = 127;
                for (int z = 0; z < NUM_ZONES; z++) {
                    ZoneState *zs = &dsp->zones[z];
                    if (cc_num == 64 && !__atomic_load_n(&zs->sustain_enable, __ATOMIC_ACQUIRE)) continue;
                    if (cc_num == 11 && !__atomic_load_n(&zs->expr_enable, __ATOMIC_ACQUIRE)) continue;
                    fluid_synth_cc(dsp->synth, z, cc_num, val);
                }
                break;
            }
            case EVT_PITCH_BEND: {
                int bend = e.data1;
                if (bend < 0) bend = 0;
                if (bend > 16383) bend = 16383;
                for (int z = 0; z < NUM_ZONES; z++) {
                    fluid_synth_pitch_bend(dsp->synth, z, bend);
                }
                break;
            }
            case EVT_ZONE_FLUSH_NOTES: {
                flush_zone_notes_on_rt(dsp, (int)e.ch);
                break;
            }
            case EVT_DRUM_TRIGGER: {
                int pad_idx = (int)e.ch;
                int vel = (int)e.data1;
                int stop_only = (int)e.data2;
                if (pad_idx < 0 || pad_idx >= NUM_DRUM_PADS) break;
                for (int v = 0; v < MAX_DRUM_VOICES; v++) {
                    if (dsp->drum_voices[v].active && dsp->drum_voices[v].pad_idx == pad_idx) {
                        dsp->drum_voices[v].active = 0;
                    }
                }
                if (!stop_only && vel > 0 && !__atomic_load_n(&dsp->drum_mutes[pad_idx], __ATOMIC_ACQUIRE)) {
                    int slot = 0;
                    for (int v = 0; v < MAX_DRUM_VOICES; v++) {
                        if (!dsp->drum_voices[v].active) {
                            slot = v;
                            break;
                        }
                    }
                    dsp->drum_voices[slot].active = 1;
                    dsp->drum_voices[slot].pad_idx = pad_idx;
                    dsp->drum_voices[slot].pos = 0;
                    dsp->drum_voices[slot].vel_gain = powf((float)vel / 127.0f, 0.85f);
                }
                break;
            }
            case EVT_PANIC: {
                for (int z = 0; z < NUM_ZONES; z++) {
                    fluid_synth_cc(dsp->synth, z, 64, 0);
                    fluid_synth_cc(dsp->synth, z, 66, 0);
                    fluid_synth_cc(dsp->synth, z, 67, 0);
                    fluid_synth_cc(dsp->synth, z, 1, 0);
                    fluid_synth_cc(dsp->synth, z, 7, 127);
                    fluid_synth_cc(dsp->synth, z, 11, 127);
                    fluid_synth_all_notes_off(dsp->synth, z);
                    fluid_synth_all_sounds_off(dsp->synth, z);
                    fluid_synth_pitch_bend(dsp->synth, z, 8192);
                    memset(dsp->zones[z].active_notes, -1, sizeof(dsp->zones[z].active_notes));
                    for (int b = 0; b < NUM_EQ_BANDS; b++) biquad_reset_state(&dsp->zones[z].eq_biquads[b]);
                    biquad_reset_state(&dsp->zones[z].lpf_biquad);
                    biquad_reset_state(&dsp->zones[z].tone_biquad);
                }
                for (int v = 0; v < MAX_DRUM_VOICES; v++) {
                    dsp->drum_voices[v].active = 0;
                }
                memset(dsp->delay_buf_l, 0, sizeof(dsp->delay_buf_l));
                memset(dsp->delay_buf_r, 0, sizeof(dsp->delay_buf_r));
                dsp->delay_lp_l = 0.0f;
                dsp->delay_lp_r = 0.0f;
                clear_reverb_buffers(dsp);
                break;
            }
            default:
                break;
        }
    }
    __atomic_store_n(&dsp->event_tail, tail, __ATOMIC_RELEASE);
}

/* =========================================================================
 * PUBLIC C API EXPOSED TO PYTHON CTYPES / JNI
 * ========================================================================= */

DSP_EXPORT void stagerig_render_block(StageRigDSP *dsp, float *out_interleaved_lr, int frames);

#ifdef __ANDROID__
/* =========================================================================
 * ANDROID AAUDIO STREAM (replaces PortAudio)
 * ========================================================================= */
#define ensure_pa_init() ((void)0)
#define release_pa_init() ((void)0)

static void aa_error_cb(AAudioStream *stream, void *userData, aaudio_result_t error) {
    (void)stream;
    StageRigDSP *dsp = (StageRigDSP *)userData;
    if (!dsp) return;
    STAGERIG_LOGW("AAudio error callback: %d", (int)error);
    __atomic_store_n(&dsp->stream_aborted, 1, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
}

static aaudio_data_callback_result_t aa_data_cb(AAudioStream *stream, void *userData, void *audioData, int32_t numFrames) {
    StageRigDSP *dsp = (StageRigDSP *)userData;
    float *out = (float *)audioData;
    if (!dsp || !out || numFrames <= 0) return AAUDIO_CALLBACK_RESULT_CONTINUE;
    if (__atomic_load_n(&dsp->shutting_down, __ATOMIC_ACQUIRE)) {
        memset(out, 0, (size_t)numFrames * 2 * sizeof(float));
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    }
    if (!__atomic_exchange_n(&dsp->rt_thread_inited, 1, __ATOMIC_ACQ_REL)) {
        enable_rt_thread_mode();
    }

    uint64_t t0 = mono_ns_now();
    __atomic_store_n(&dsp->last_callback_ns, t0, __ATOMIC_RELEASE);
    __atomic_add_fetch(&dsp->callback_count, 1ULL, __ATOMIC_RELAXED);

    stagerig_render_block(dsp, out, (int)numFrames);

    /* CPU load of this callback (render time / time budget) */
    uint64_t t1 = mono_ns_now();
    float budget_ns = ((float)numFrames / dsp->sample_rate) * 1.0e9f;
    float load = (budget_ns > 1.0f) ? ((float)(t1 - t0) / budget_ns) : 0.0f;
    dsp->load_ema += 0.05f * (load - dsp->load_ema);
    if (load > 0.85f) {
        if (dsp->high_load_cbs < 4096) dsp->high_load_cbs++;
    } else if (dsp->high_load_cbs > 0) {
        dsp->high_load_cbs--;
    }
    if (dsp->high_load_cbs > 48) {
        __atomic_store_n(&dsp->degrade_req, 1, __ATOMIC_RELEASE);
    }

    /* Under-run governor: every new xrun grows the AAudio buffer (up to aa_max_buf). */
    int32_t xr = AAudioStream_getXRunCount(stream);
    if (xr > dsp->aa_last_xruns) {
        __atomic_add_fetch(&dsp->xrun_count, (uint64_t)(xr - dsp->aa_last_xruns), __ATOMIC_RELAXED);
        dsp->aa_last_xruns = xr;
        int32_t cur = AAudioStream_getBufferSizeInFrames(stream);
        int32_t want = cur + (dsp->aa_burst > 0 ? dsp->aa_burst : 192);
        if (want > dsp->aa_max_buf) want = dsp->aa_max_buf;
        if (want > cur) {
            (void)AAudioStream_setBufferSizeInFrames(stream, want);
        }
    }
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

/* Called from a non-realtime thread (telemetry poll): applies one-way quality reduction when the CPU is saturated. */
static void maintain_quality(StageRigDSP *dsp) {
    if (!dsp || !__atomic_load_n(&dsp->degrade_req, __ATOMIC_ACQUIRE)) return;
    if (dsp->quality_level >= 2) {
        __atomic_store_n(&dsp->degrade_req, 0, __ATOMIC_RELEASE);
        return;
    }
    if (rig_mutex_trylock(&dsp->sf_lock) != 0) return;
    if (dsp->synth) {
        (void)fluid_synth_set_polyphony(dsp->synth, 72);
        dsp->quality_level = 2;
        STAGERIG_LOGW("CPU saturated: reducing polyphony to 72");
    }
    rig_mutex_unlock(&dsp->sf_lock);
    dsp->high_load_cbs = 0;
    __atomic_store_n(&dsp->degrade_req, 0, __ATOMIC_RELEASE);
}
#else
static void pa_stream_finished_cb(void *userData) {
    StageRigDSP *dsp = (StageRigDSP *)userData;
    if (!dsp) return;
    __atomic_store_n(&dsp->stream_aborted, 1, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
}

static int stagerig_pa_callback(
    const void *inputBuffer,
    void *outputBuffer,
    unsigned long framesPerBuffer,
    const PaStreamCallbackTimeInfo *timeInfo,
    PaStreamCallbackFlags statusFlags,
    void *userData
) {
    (void)inputBuffer;
    (void)timeInfo;
    StageRigDSP *dsp = (StageRigDSP *)userData;
    float *out = (float *)outputBuffer;
    if (!dsp || __atomic_load_n(&dsp->shutting_down, __ATOMIC_ACQUIRE)) {
        if (out && framesPerBuffer > 0) {
            memset(out, 0, (size_t)framesPerBuffer * 2 * sizeof(float));
        }
        return paContinue;
    }

    if (!__atomic_exchange_n(&dsp->rt_thread_inited, 1, __ATOMIC_ACQ_REL)) {
        enable_rt_thread_mode();
    }

    __atomic_store_n(&dsp->last_callback_ns, mono_ns_now(), __ATOMIC_RELEASE);
    __atomic_add_fetch(&dsp->callback_count, 1ULL, __ATOMIC_RELAXED);
    if (statusFlags & (paOutputUnderflow | paOutputOverflow)) {
        __atomic_add_fetch(&dsp->xrun_count, 1ULL, __ATOMIC_RELAXED);
    }

    stagerig_render_block(dsp, out, (int)framesPerBuffer);
    return paContinue;
}

static void ensure_pa_init(void) {
    global_lock_acquire();
    if (g_pa_refcount == 0) {
        if (Pa_Initialize() == paNoError) {
            g_pa_refcount = 1;
        }
    } else {
        g_pa_refcount++;
    }
    global_lock_release();
}

static void release_pa_init(void) {
    global_lock_acquire();
    if (g_pa_refcount > 0) {
        g_pa_refcount--;
        if (g_pa_refcount == 0) {
            Pa_Terminate();
        }
    }
    global_lock_release();
}

#endif

DSP_EXPORT StageRigDSP *stagerig_create(float sample_rate) {
    StageRigDSP *dsp = (StageRigDSP *)calloc(1, sizeof(StageRigDSP));
    if (!dsp) return NULL;

    rig_mutex_init(&dsp->sf_lock, NULL);
    rig_mutex_init(&dsp->stream_lock, NULL);
    rig_mutex_init(&dsp->event_q_lock, NULL);
    rig_mutex_init(&dsp->drum_lock, NULL);
    ensure_pa_init();

    dsp->sample_rate = (sample_rate > 8000.0f) ? sample_rate : 44100.0f;

    fluid_set_log_function(FLUID_WARN, NULL, NULL);
    fluid_set_log_function(FLUID_INFO, NULL, NULL);

    dsp->settings = new_fluid_settings();
    fluid_settings_setnum(dsp->settings, "synth.sample-rate", (double)dsp->sample_rate);
#ifdef __ANDROID__
    fluid_settings_setint(dsp->settings, "synth.polyphony", 128);
#else
    fluid_settings_setint(dsp->settings, "synth.polyphony", 384);
#endif
    fluid_settings_setint(dsp->settings, "synth.audio-channels", NUM_ZONES);
    fluid_settings_setint(dsp->settings, "synth.audio-groups", NUM_ZONES);
    fluid_settings_setint(dsp->settings, "synth.reverb.active", 0);
    fluid_settings_setint(dsp->settings, "synth.chorus.active", 0);
    fluid_settings_setnum(dsp->settings, "synth.gain", 0.62);
    fluid_settings_setint(dsp->settings, "synth.threadsafe-api", 1);
    fluid_settings_setint(dsp->settings, "synth.cpu-cores", 1);
#ifdef __ANDROID__
    fluid_settings_setint(dsp->settings, "synth.dynamic-sample-loading", 1);
    fluid_settings_setint(dsp->settings, "synth.effects-groups", NUM_ZONES);
#else
    fluid_settings_setint(dsp->settings, "synth.dynamic-sample-loading", 0);
#endif

    dsp->synth = new_fluid_synth(dsp->settings);
#ifdef __ANDROID__
    /* Linear interpolation: ~2.5x cheaper voices than the 4th-order default, essential on Cortex-A55 class devices. */
    if (dsp->synth) fluid_synth_set_interp_method(dsp->synth, -1, 1);
    dsp->quality_level = 1;
#endif
    dsp->lim_gain = 1.0f;
    dsp->pad_sr_comp = 1.0;
    dsp->req_sample_rate = (int)dsp->sample_rate;

    init_reverb(dsp);
    __atomic_store_n(&dsp->dly_fb_bits, f2u(0.36f), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->dly_lvl_bits, f2u(0.52f), __ATOMIC_RELEASE);
    update_delay_timing(dsp, 72.0f);

    /* 5-Layer Pad, 4-Slot Drum & Dual Master defaults */
    int def_pad_vols[NUM_PAD_LAYERS] = {100, 85, 75, 80, 75};
    for (int i = 0; i < NUM_PAD_LAYERS; i++) {
        dsp->pad_layer_vols[i] = def_pad_vols[i];
        dsp->pad_layer_mutes[i] = 0;
        dsp->cur_pad_gains[i] = (float)def_pad_vols[i] / 127.0f;
    }
    for (int d = 0; d < NUM_DRUM_PADS; d++) {
        dsp->drum_vols[d] = 112;
        dsp->drum_mutes[d] = 0;
        dsp->drum_loops[d] = 0;
    }
    dsp->pad_rate_bits = f2u(1.0f);
    dsp->pad_rate_a = 1.0;
    dsp->pad_rate_b = 1.0;
    dsp->synth_master_vol = 110;
    dsp->synth_master_muted = 0;
    dsp->pad_master_vol = 110;
    dsp->pad_master_muted = 0;
    float nom_mg = powf(110.0f / 127.0f, 1.25f);
    dsp->cur_synth_mg = nom_mg;
    dsp->cur_pad_mg = nom_mg;

    for (int z = 0; z < NUM_ZONES; z++) {
        ZoneState *zs = &dsp->zones[z];
        zs->enabled = 1;
        zs->muted = 0;
        zs->soloed = 0;
        zs->volume_cc = 100;
        zs->reverb_cc = 65;
        zs->delay_cc = 40;
        zs->chorus_cc = 0;
        zs->pan_cc = 64;
        zs->cutoff_cc = 127;
        zs->resonance_cc = 0;
        zs->tone_cc = 64;
        zs->attack_cc = 0;
        zs->release_cc = 64;
        for (int b = 0; b < NUM_EQ_BANDS; b++) zs->eq_tenths_db[b] = 0;
        zs->filters_dirty = 1;
        zs->transpose = 0;
        zs->key_low = 0;
        zs->key_hi = 127;
        zs->vel_low = 0;
        zs->vel_hi = 127;
        zs->sustain_enable = 1;
        zs->expr_enable = 1;
        zs->sfid = -1;
        zs->bank = 0;
        zs->prog = 0;
        zs->cur_gain = 0.75f;
        zs->cur_rev_send = 0.4f;
        zs->cur_dly_send = 0.25f;
        zs->cur_chorus_mix = 0.0f;
        zs->cur_pan_l = 1.0f;
        zs->cur_pan_r = 1.0f;
        zs->chorus_idx = 0;
        zs->chorus_phase = (double)z * 1.57;
        zs->peak_vu_bits = 0;
        memset(zs->active_notes, -1, sizeof(zs->active_notes));

        fluid_synth_cc(dsp->synth, z, 7, 127);
        fluid_synth_cc(dsp->synth, z, 11, 127);
    }

    return dsp;
}

#ifdef __ANDROID__
DSP_EXPORT void stagerig_stop_stream(StageRigDSP *dsp) {
    if (!dsp) return;
    rig_mutex_lock(&dsp->stream_lock);
    if (dsp->pa_stream) {
        (void)AAudioStream_requestStop(dsp->pa_stream);
        (void)AAudioStream_close(dsp->pa_stream);
        dsp->pa_stream = NULL;
    }
    __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
    rig_mutex_unlock(&dsp->stream_lock);
}
#else
DSP_EXPORT void stagerig_stop_stream(StageRigDSP *dsp) {
    if (!dsp) return;
    rig_mutex_lock(&dsp->stream_lock);
    if (dsp->pa_stream) {
        Pa_AbortStream(dsp->pa_stream);
        Pa_CloseStream(dsp->pa_stream);
        dsp->pa_stream = NULL;
    }
    __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
    rig_mutex_unlock(&dsp->stream_lock);
}

#endif

DSP_EXPORT void stagerig_destroy(StageRigDSP *dsp) {
    if (!dsp) return;
    __atomic_store_n(&dsp->shutting_down, 1, __ATOMIC_RELEASE);
    stagerig_stop_stream(dsp);

    rig_mutex_lock(&dsp->sf_lock);
    if (dsp->synth) {
        delete_fluid_synth(dsp->synth);
        dsp->synth = NULL;
    }
    if (dsp->settings) {
        delete_fluid_settings(dsp->settings);
        dsp->settings = NULL;
    }
    for (int i = 0; i < NUM_PAD_LAYERS; i++) {
        free(dsp->pad_bufs[i]);
        dsp->pad_bufs[i] = NULL;
        dsp->pad_lengths[i] = 0;
    }
    rig_mutex_unlock(&dsp->sf_lock);

    rig_mutex_lock(&dsp->drum_lock);
    for (int d = 0; d < NUM_DRUM_PADS; d++) {
        free(dsp->drum_bufs[d]);
        dsp->drum_bufs[d] = NULL;
        dsp->drum_lengths[d] = 0;
    }
    rig_mutex_unlock(&dsp->drum_lock);

    release_pa_init();
    rig_mutex_destroy(&dsp->sf_lock);
    rig_mutex_destroy(&dsp->stream_lock);
    rig_mutex_destroy(&dsp->event_q_lock);
    rig_mutex_destroy(&dsp->drum_lock);
    free(dsp);
}

static void sync_dsp_sample_rate(StageRigDSP *dsp, double actual_sr, double req_sr) {
    if (!dsp || actual_sr < 8000.0) return;
    if ((int)actual_sr != (int)dsp->sample_rate) {
        dsp->sample_rate = (float)actual_sr;
        rig_mutex_lock(&dsp->sf_lock);
        if (dsp->settings) {
            fluid_settings_setnum(dsp->settings, "synth.sample-rate", actual_sr);
        }
        if (dsp->synth) {
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
            fluid_synth_set_sample_rate(dsp->synth, (float)actual_sr);
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif
        }
        rig_mutex_unlock(&dsp->sf_lock);
        for (int z = 0; z < NUM_ZONES; z++) {
            __atomic_store_n(&dsp->zones[z].filters_dirty, 1, __ATOMIC_RELEASE);
        }
        update_delay_timing(dsp, dsp->bpm > 0.0f ? dsp->bpm : 120.0f);
    }
    dsp->req_sample_rate = (int)(req_sr >= 8000.0 ? req_sr : actual_sr);
    dsp->pad_sr_comp = (req_sr >= 8000.0) ? (req_sr / actual_sr) : 1.0;
    if (dsp->pad_sr_comp < 0.5 || dsp->pad_sr_comp > 2.0) dsp->pad_sr_comp = 1.0;
}

#ifdef __ANDROID__
DSP_EXPORT int stagerig_pa_device_count(void) { return 1; }

DSP_EXPORT int stagerig_pa_get_device_info(
    int idx, char *name_out, int name_cap, int *max_out_ch, double *default_sr, double *low_lat, int *is_default
) {
    if (idx != 0) return -1;
    if (name_out && name_cap > 0) snprintf(name_out, (size_t)name_cap, "%s", "Android AAudio Output");
    if (max_out_ch) *max_out_ch = 2;
    if (default_sr) *default_sr = 48000.0;
    if (low_lat) *low_lat = 0.010;
    if (is_default) *is_default = 1;
    return 0;
}

static AAudioStream *open_android_aaudio(StageRigDSP *dsp, int32_t req_sr, int32_t cb_frames) {
    AAudioStreamBuilder *builder = NULL;
    if (AAudio_createStreamBuilder(&builder) != AAUDIO_OK || !builder) return NULL;

    AAudioStreamBuilder_setDirection(builder, AAUDIO_DIRECTION_OUTPUT);
    AAudioStreamBuilder_setFormat(builder, AAUDIO_FORMAT_PCM_FLOAT);
    AAudioStreamBuilder_setChannelCount(builder, 2);
    if (req_sr > 0) AAudioStreamBuilder_setSampleRate(builder, req_sr);
    AAudioStreamBuilder_setPerformanceMode(builder, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    AAudioStreamBuilder_setSharingMode(builder, AAUDIO_SHARING_MODE_SHARED);
    /* Usage/content type exist only on API 28+: resolve at runtime so the .so still loads on API 27. */
    {
        typedef void (*set_i32_fn)(AAudioStreamBuilder *, int32_t);
        set_i32_fn f_usage = (set_i32_fn)dlsym(RTLD_DEFAULT, "AAudioStreamBuilder_setUsage");
        set_i32_fn f_content = (set_i32_fn)dlsym(RTLD_DEFAULT, "AAudioStreamBuilder_setContentType");
        if (f_usage) f_usage(builder, 1 /* AAUDIO_USAGE_MEDIA */);
        if (f_content) f_content(builder, 2 /* AAUDIO_CONTENT_TYPE_MUSIC */);
    }
    if (cb_frames > 0) {
        AAudioStreamBuilder_setFramesPerDataCallback(builder, cb_frames);
    }
    AAudioStreamBuilder_setDataCallback(builder, aa_data_cb, dsp);
    AAudioStreamBuilder_setErrorCallback(builder, aa_error_cb, dsp);

    AAudioStream *stream = NULL;
    aaudio_result_t res = AAudioStreamBuilder_openStream(builder, &stream);
    AAudioStreamBuilder_delete(builder);
    if (res != AAUDIO_OK || !stream) {
        STAGERIG_LOGW("openStream failed (sr=%d cb=%d): %d", (int)req_sr, (int)cb_frames, (int)res);
        return NULL;
    }
    return stream;
}

DSP_EXPORT int stagerig_start_stream(
    StageRigDSP *dsp,
    const char *device_name,
    double sample_rate,
    unsigned long block_size,
    double *out_latency_ms
) {
    (void)device_name;
    if (!dsp || __atomic_load_n(&dsp->shutting_down, __ATOMIC_ACQUIRE)) return -1;
    if (sample_rate < 8000.0) sample_rate = 48000.0;
    if (block_size < 128) block_size = 128;
    if (block_size > 1024) block_size = 1024;

    rig_mutex_lock(&dsp->stream_lock);
    if (dsp->pa_stream) {
        if (AAudioStream_getState(dsp->pa_stream) == AAUDIO_STREAM_STATE_STARTED &&
            !__atomic_load_n(&dsp->stream_aborted, __ATOMIC_ACQUIRE)) {
            if (out_latency_ms) {
                *out_latency_ms = ((double)AAudioStream_getBufferSizeInFrames(dsp->pa_stream) / (double)dsp->sample_rate) * 1000.0;
            }
            __atomic_store_n(&dsp->stream_active, 1, __ATOMIC_RELEASE);
            rig_mutex_unlock(&dsp->stream_lock);
            return 0;
        }
        (void)AAudioStream_requestStop(dsp->pa_stream);
        (void)AAudioStream_close(dsp->pa_stream);
        dsp->pa_stream = NULL;
    }

    int opened_ok = 0;
    /* Attempt 0: requested rate; Attempt 1: device native rate.
     * Open first with unspecified callback size to read the exact hardware burst, then align
     * framesPerDataCallback to a clean integer multiple of burst (prevents MediaTek/AAudio HAL glitches). */
    for (int attempt = 0; attempt < 2 && !opened_ok; attempt++) {
        int32_t ask_sr = (attempt == 0) ? (int32_t)sample_rate : 0;

        __atomic_store_n(&dsp->stream_aborted, 0, __ATOMIC_RELEASE);
        __atomic_store_n(&dsp->rt_thread_inited, 0, __ATOMIC_RELEASE);
        uint64_t now = mono_ns_now();
        __atomic_store_n(&dsp->stream_started_ns, now, __ATOMIC_RELEASE);
        __atomic_store_n(&dsp->last_callback_ns, now, __ATOMIC_RELEASE);

        AAudioStream *stream = open_android_aaudio(dsp, ask_sr, 0);
        if (!stream) continue;

        int32_t actual_sr = AAudioStream_getSampleRate(stream);
        int32_t burst = AAudioStream_getFramesPerBurst(stream);
        int32_t capacity = AAudioStream_getBufferCapacityInFrames(stream);
        if (burst < 32) burst = 192;

        int32_t mult = ((int32_t)block_size + burst - 1) / burst;
        if (mult < 1) mult = 1;
        int32_t want_cb = burst * mult;
        while (want_cb > 1024 && mult > 1) { mult--; want_cb = burst * mult; }
        if (capacity > 0) {
            while (want_cb > capacity / 2 && mult > 1) { mult--; want_cb = burst * mult; }
        }

        if (want_cb > burst && mult > 1) {
            AAudioStream *aligned = open_android_aaudio(dsp, actual_sr > 0 ? actual_sr : ask_sr, want_cb);
            if (aligned) {
                (void)AAudioStream_close(stream);
                stream = aligned;
                actual_sr = AAudioStream_getSampleRate(stream);
                burst = AAudioStream_getFramesPerBurst(stream);
                capacity = AAudioStream_getBufferCapacityInFrames(stream);
                if (burst < 32) burst = 192;
            } else {
                want_cb = burst;
            }
        } else {
            want_cb = burst;
        }

        int32_t buf = (want_cb * 2 > burst * 4) ? want_cb * 2 : burst * 4;
        int32_t max_buf = (buf * 4 > want_cb * 6) ? buf * 4 : want_cb * 6;
        if (capacity > 0) {
            if (buf > capacity) buf = capacity;
            if (max_buf > capacity) max_buf = capacity;
        }
        (void)AAudioStream_setBufferSizeInFrames(stream, buf);

        if (actual_sr >= 8000 && actual_sr != (int32_t)dsp->sample_rate) {
            STAGERIG_LOGW("Sample rate mismatch: engine %d vs stream %d", (int)dsp->sample_rate, (int)actual_sr);
        }
        sync_dsp_sample_rate(dsp, (double)(actual_sr >= 8000 ? actual_sr : 48000), sample_rate);

        dsp->aa_burst = burst;
        dsp->aa_capacity = capacity;
        dsp->aa_max_buf = max_buf;
        dsp->aa_last_xruns = 0;
        dsp->load_ema = 0.0f;
        dsp->high_load_cbs = 0;

        aaudio_result_t res = AAudioStream_requestStart(stream);
        if (res != AAUDIO_OK) {
            STAGERIG_LOGW("requestStart failed: %d", (int)res);
            (void)AAudioStream_close(stream);
            continue;
        }
        dsp->pa_stream = stream;
        __atomic_store_n(&dsp->stream_active, 1, __ATOMIC_RELEASE);
        if (out_latency_ms) {
            *out_latency_ms = ((double)AAudioStream_getBufferSizeInFrames(stream) / (double)dsp->sample_rate) * 1000.0;
        }
        STAGERIG_LOGI("AAudio started: sr=%d burst=%d cb=%d buf=%d cap=%d maxbuf=%d", (int)actual_sr, (int)burst, (int)want_cb, (int)buf, (int)capacity, (int)max_buf);
        opened_ok = 1;
    }

    if (!opened_ok) {
        __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
    }
    rig_mutex_unlock(&dsp->stream_lock);
    return opened_ok ? 0 : -1;
}

DSP_EXPORT void stagerig_simulate_stream_abort(StageRigDSP *dsp) {
    if (!dsp) return;
    __atomic_store_n(&dsp->stream_aborted, 1, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_get_stream_stats(
    StageRigDSP *dsp,
    int *active,
    int *aborted,
    uint64_t *cb_count,
    uint64_t *xruns,
    uint64_t *last_cb_ms_ago
) {
    if (!dsp) return;
    int is_aborted = __atomic_load_n(&dsp->stream_aborted, __ATOMIC_ACQUIRE);
    int is_active = 0;
    if (rig_mutex_trylock(&dsp->stream_lock) == 0) {
        is_active = (dsp->pa_stream && !is_aborted &&
                     AAudioStream_getState(dsp->pa_stream) == AAUDIO_STREAM_STATE_STARTED) ? 1 : 0;
        rig_mutex_unlock(&dsp->stream_lock);
    } else {
        is_active = (__atomic_load_n(&dsp->stream_active, __ATOMIC_ACQUIRE) && !is_aborted) ? 1 : 0;
    }
    uint64_t started = __atomic_load_n(&dsp->stream_started_ns, __ATOMIC_ACQUIRE);
    uint64_t last_cb = __atomic_load_n(&dsp->last_callback_ns, __ATOMIC_ACQUIRE);
    uint64_t ref = (last_cb > started) ? last_cb : started;
    uint64_t now = mono_ns_now();
    uint64_t ago_ms = (ref > 0 && now > ref) ? ((now - ref) / 1000000ULL) : 0ULL;
    if (active) *active = is_active;
    if (aborted) *aborted = is_aborted;
    if (cb_count) *cb_count = __atomic_load_n(&dsp->callback_count, __ATOMIC_RELAXED);
    if (xruns) *xruns = __atomic_load_n(&dsp->xrun_count, __ATOMIC_RELAXED);
    if (last_cb_ms_ago) *last_cb_ms_ago = ago_ms;
}
#else
DSP_EXPORT int stagerig_pa_device_count(void) {
    ensure_pa_init();
    int cnt = (int)Pa_GetDeviceCount();
    release_pa_init();
    return cnt;
}

DSP_EXPORT int stagerig_pa_get_device_info(
    int idx,
    char *name_out,
    int name_cap,
    int *max_out_ch,
    double *default_sr,
    double *low_lat,
    int *is_default
) {
    ensure_pa_init();
    int cnt = (int)Pa_GetDeviceCount();
    if (idx < 0 || idx >= cnt) {
        release_pa_init();
        return -1;
    }
    const PaDeviceInfo *info = Pa_GetDeviceInfo((PaDeviceIndex)idx);
    PaDeviceIndex def_idx = Pa_GetDefaultOutputDevice();
    if (!info) {
        release_pa_init();
        return -1;
    }
    if (name_out && name_cap > 0) {
        snprintf(name_out, (size_t)name_cap, "%s", info->name ? info->name : "");
    }
    if (max_out_ch) *max_out_ch = info->maxOutputChannels;
    if (default_sr) *default_sr = info->defaultSampleRate;
    if (low_lat) *low_lat = info->defaultLowOutputLatency;
    if (is_default) *is_default = (idx == (int)def_idx) ? 1 : 0;
    release_pa_init();
    return 0;
}

DSP_EXPORT int stagerig_start_stream(
    StageRigDSP *dsp,
    const char *device_name,
    double sample_rate,
    unsigned long block_size,
    double *out_latency_ms
) {
    if (!dsp || __atomic_load_n(&dsp->shutting_down, __ATOMIC_ACQUIRE)) return -1;
    if (sample_rate < 8000.0) sample_rate = 44100.0;
    if (block_size < 64) block_size = 256;

    rig_mutex_lock(&dsp->stream_lock);
    if (dsp->pa_stream) {
        if (Pa_IsStreamActive(dsp->pa_stream) == 1 && !__atomic_load_n(&dsp->stream_aborted, __ATOMIC_ACQUIRE)) {
            const PaStreamInfo *si = Pa_GetStreamInfo(dsp->pa_stream);
            if (out_latency_ms) {
                *out_latency_ms = (si && si->outputLatency > 0.0) ? (si->outputLatency * 1000.0) : (((double)block_size / sample_rate) * 1000.0);
            }
            __atomic_store_n(&dsp->stream_active, 1, __ATOMIC_RELEASE);
            rig_mutex_unlock(&dsp->stream_lock);
            return 0;
        }
        Pa_AbortStream(dsp->pa_stream);
        Pa_CloseStream(dsp->pa_stream);
        dsp->pa_stream = NULL;
    }

    int count = (int)Pa_GetDeviceCount();
    PaDeviceIndex target_dev = Pa_GetDefaultOutputDevice();
    if (device_name && device_name[0] != '\0' && strcmp(device_name, "default") != 0) {
        for (int i = 0; i < count; i++) {
            const PaDeviceInfo *d = Pa_GetDeviceInfo((PaDeviceIndex)i);
            if (d && d->maxOutputChannels >= 2 && d->name && strcmp(d->name, device_name) == 0) {
                target_dev = (PaDeviceIndex)i;
                break;
            }
        }
    }

    PaDeviceIndex attempts[2] = {target_dev, Pa_GetDefaultOutputDevice()};
    int n_attempts = (attempts[0] != attempts[1] && attempts[1] != paNoDevice) ? 2 : 1;
    int opened_ok = 0;

    for (int a = 0; a < n_attempts && !opened_ok; a++) {
        PaDeviceIndex dev_idx = attempts[a];
        if (dev_idx == paNoDevice) continue;
        const PaDeviceInfo *dev_info = Pa_GetDeviceInfo(dev_idx);
        if (!dev_info || dev_info->maxOutputChannels < 2) continue;

        double try_rates[2] = {sample_rate, dev_info->defaultSampleRate};
        int n_rates = (dev_info->defaultSampleRate >= 8000.0 && fabs(dev_info->defaultSampleRate - sample_rate) > 1.0) ? 2 : 1;

        for (int r = 0; r < n_rates; r++) {
            double sr_use = try_rates[r];
            double periods = (block_size >= 512) ? 2.0 : 3.0;
            double min_cushion = ((double)block_size * periods) / sr_use;
            double sug_lat = dev_info->defaultLowOutputLatency;
            if (sug_lat < min_cushion) sug_lat = min_cushion;
            if (dev_info->defaultHighOutputLatency > 0.0 && sug_lat > dev_info->defaultHighOutputLatency) {
                sug_lat = dev_info->defaultHighOutputLatency;
            }

            PaStreamParameters out_params;
            memset(&out_params, 0, sizeof(out_params));
            out_params.device = dev_idx;
            out_params.channelCount = 2;
            out_params.sampleFormat = paFloat32;
            out_params.suggestedLatency = sug_lat;
            out_params.hostApiSpecificStreamInfo = NULL;

            __atomic_store_n(&dsp->stream_aborted, 0, __ATOMIC_RELEASE);
            __atomic_store_n(&dsp->rt_thread_inited, 0, __ATOMIC_RELEASE);
            uint64_t now = mono_ns_now();
            __atomic_store_n(&dsp->stream_started_ns, now, __ATOMIC_RELEASE);
            __atomic_store_n(&dsp->last_callback_ns, now, __ATOMIC_RELEASE);

            PaStream *stream = NULL;
            PaError err = Pa_OpenStream(
                &stream,
                NULL,
                &out_params,
                sr_use,
                block_size,
                paNoFlag,
                stagerig_pa_callback,
                dsp
            );
            if (err == paNoError && stream) {
                (void)Pa_SetStreamFinishedCallback(stream, pa_stream_finished_cb);
                err = Pa_StartStream(stream);
                if (err == paNoError) {
                    const PaStreamInfo *si = Pa_GetStreamInfo(stream);
                    double actual_sr = (si && si->sampleRate >= 8000.0) ? si->sampleRate : sr_use;
                    sync_dsp_sample_rate(dsp, actual_sr, sample_rate);
                    dsp->pa_stream = stream;
                    __atomic_store_n(&dsp->stream_active, 1, __ATOMIC_RELEASE);
                    if (out_latency_ms) {
                        *out_latency_ms = (si && si->outputLatency > 0.0)
                            ? (si->outputLatency * 1000.0)
                            : (sug_lat * 1000.0);
                    }
                    opened_ok = 1;
                    break;
                }
                Pa_CloseStream(stream);
            }
        }
    }

    if (!opened_ok) {
        __atomic_store_n(&dsp->stream_active, 0, __ATOMIC_RELEASE);
    }
    rig_mutex_unlock(&dsp->stream_lock);
    return opened_ok ? 0 : -1;
}

DSP_EXPORT void stagerig_simulate_stream_abort(StageRigDSP *dsp) {
    if (!dsp) return;
    pa_stream_finished_cb(dsp);
}

DSP_EXPORT void stagerig_get_stream_stats(
    StageRigDSP *dsp,
    int *active,
    int *aborted,
    uint64_t *cb_count,
    uint64_t *xruns,
    uint64_t *last_cb_ms_ago
) {
    if (!dsp) return;
    int is_aborted = __atomic_load_n(&dsp->stream_aborted, __ATOMIC_ACQUIRE);
    int is_active = 0;
    if (rig_mutex_trylock(&dsp->stream_lock) == 0) {
        is_active = (dsp->pa_stream && !is_aborted && Pa_IsStreamActive(dsp->pa_stream) == 1) ? 1 : 0;
        rig_mutex_unlock(&dsp->stream_lock);
    } else {
        is_active = (__atomic_load_n(&dsp->stream_active, __ATOMIC_ACQUIRE) && !is_aborted) ? 1 : 0;
    }
    uint64_t started = __atomic_load_n(&dsp->stream_started_ns, __ATOMIC_ACQUIRE);
    uint64_t last_cb = __atomic_load_n(&dsp->last_callback_ns, __ATOMIC_ACQUIRE);
    uint64_t ref = (last_cb > started) ? last_cb : started;
    uint64_t now = mono_ns_now();
    uint64_t ago_ms = (ref > 0 && now > ref) ? ((now - ref) / 1000000ULL) : 0ULL;

    if (active) *active = is_active;
    if (aborted) *aborted = is_aborted;
    if (cb_count) *cb_count = __atomic_load_n(&dsp->callback_count, __ATOMIC_RELAXED);
    if (xruns) *xruns = __atomic_load_n(&dsp->xrun_count, __ATOMIC_RELAXED);
    if (last_cb_ms_ago) *last_cb_ms_ago = ago_ms;
}

#endif

DSP_EXPORT int stagerig_load_soundfont(StageRigDSP *dsp, const char *path) {
    if (!dsp || !dsp->synth || !path) return -1;
    rig_mutex_lock(&dsp->sf_lock);
    int sfid = fluid_synth_sfload(dsp->synth, path, 0);
    rig_mutex_unlock(&dsp->sf_lock);
    return sfid;
}

DSP_EXPORT int stagerig_unload_soundfont(StageRigDSP *dsp, int sfid) {
    if (!dsp || !dsp->synth || sfid <= 0) return -1;
    rig_mutex_lock(&dsp->sf_lock);
    for (int z = 0; z < NUM_ZONES; z++) {
        if (__atomic_load_n(&dsp->zones[z].sfid, __ATOMIC_ACQUIRE) == sfid) {
            __atomic_store_n(&dsp->zones[z].sfid, -1, __ATOMIC_RELEASE);
            rt_enqueue_event(dsp, EVT_ZONE_FLUSH_NOTES, (uint8_t)z, 0, 0);
        }
    }
    int rc = fluid_synth_sfunload(dsp->synth, sfid, 1);
    rig_mutex_unlock(&dsp->sf_lock);
    return rc;
}

DSP_EXPORT int stagerig_set_zone_program(StageRigDSP *dsp, int zone_idx, int sfid, int bank, int prog) {
    if (!dsp || !dsp->synth || zone_idx < 0 || zone_idx >= NUM_ZONES || sfid <= 0) return -1;
    rig_mutex_lock(&dsp->sf_lock);
    ZoneState *zs = &dsp->zones[zone_idx];
    if (zs->sfid == sfid && zs->bank == bank && zs->prog == prog) {
        fluid_synth_cc(dsp->synth, zone_idx, 7, 127);
        fluid_synth_cc(dsp->synth, zone_idx, 11, 127);
        fluid_synth_cc(dsp->synth, zone_idx, 64, 0);
        fluid_synth_cc(dsp->synth, zone_idx, 1, 0);
        fluid_synth_pitch_bend(dsp->synth, zone_idx, 8192);
        rig_mutex_unlock(&dsp->sf_lock);
        return 0;
    }
    rt_enqueue_event(dsp, EVT_ZONE_FLUSH_NOTES, (uint8_t)zone_idx, 0, 0);
    fluid_synth_cc(dsp->synth, zone_idx, 64, 0);
    __atomic_store_n(&zs->sfid, sfid, __ATOMIC_RELEASE);
    zs->bank = bank;
    zs->prog = prog;
    int res = fluid_synth_program_select(dsp->synth, zone_idx, sfid, (unsigned int)bank, (unsigned int)prog);
    fluid_synth_cc(dsp->synth, zone_idx, 7, 127);
    fluid_synth_cc(dsp->synth, zone_idx, 11, 127);
    fluid_synth_cc(dsp->synth, zone_idx, 64, 0);
    fluid_synth_cc(dsp->synth, zone_idx, 1, 0);
    fluid_synth_cc(dsp->synth, zone_idx, 73, __atomic_load_n(&zs->attack_cc, __ATOMIC_ACQUIRE));
    fluid_synth_cc(dsp->synth, zone_idx, 72, __atomic_load_n(&zs->release_cc, __ATOMIC_ACQUIRE));
    fluid_synth_pitch_bend(dsp->synth, zone_idx, 8192);
    rig_mutex_unlock(&dsp->sf_lock);
    return res;
}

DSP_EXPORT void stagerig_set_zone_volume(StageRigDSP *dsp, int zone_idx, int vol_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (vol_cc < 0) vol_cc = 0;
    if (vol_cc > 127) vol_cc = 127;
    __atomic_store_n(&dsp->zones[zone_idx].volume_cc, vol_cc, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_mute(StageRigDSP *dsp, int zone_idx, int muted) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    __atomic_store_n(&dsp->zones[zone_idx].muted, muted ? 1 : 0, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_solo(StageRigDSP *dsp, int zone_idx, int soloed) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    __atomic_store_n(&dsp->zones[zone_idx].soloed, soloed ? 1 : 0, __ATOMIC_RELEASE);
    refresh_any_solo(dsp);
}

DSP_EXPORT void stagerig_set_zone_fx(StageRigDSP *dsp, int zone_idx, int is_delay, int val_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (val_cc < 0) val_cc = 0;
    if (val_cc > 127) val_cc = 127;
    if (is_delay) {
        __atomic_store_n(&dsp->zones[zone_idx].delay_cc, val_cc, __ATOMIC_RELEASE);
    } else {
        __atomic_store_n(&dsp->zones[zone_idx].reverb_cc, val_cc, __ATOMIC_RELEASE);
    }
}

DSP_EXPORT void stagerig_set_zone_chorus(StageRigDSP *dsp, int zone_idx, int chorus_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (chorus_cc < 0) chorus_cc = 0;
    if (chorus_cc > 127) chorus_cc = 127;
    __atomic_store_n(&dsp->zones[zone_idx].chorus_cc, chorus_cc, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_envelope(StageRigDSP *dsp, int zone_idx, int attack_cc, int release_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (attack_cc < 0) attack_cc = 0;
    if (attack_cc > 127) attack_cc = 127;
    if (release_cc < 0) release_cc = 0;
    if (release_cc > 127) release_cc = 127;
    __atomic_store_n(&dsp->zones[zone_idx].attack_cc, attack_cc, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->zones[zone_idx].release_cc, release_cc, __ATOMIC_RELEASE);
    if (dsp->synth && rig_mutex_trylock(&dsp->sf_lock) == 0) {
        fluid_synth_cc(dsp->synth, zone_idx, 73, attack_cc);
        fluid_synth_cc(dsp->synth, zone_idx, 72, release_cc);
        rig_mutex_unlock(&dsp->sf_lock);
    }
}

DSP_EXPORT void stagerig_set_zone_pan(StageRigDSP *dsp, int zone_idx, int pan_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (pan_cc < 0) pan_cc = 0;
    if (pan_cc > 127) pan_cc = 127;
    __atomic_store_n(&dsp->zones[zone_idx].pan_cc, pan_cc, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_tone(StageRigDSP *dsp, int zone_idx, int cutoff_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (cutoff_cc < 0) cutoff_cc = 0;
    if (cutoff_cc > 127) cutoff_cc = 127;
    __atomic_store_n(&dsp->zones[zone_idx].cutoff_cc, cutoff_cc, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->zones[zone_idx].filters_dirty, 1, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_filter(StageRigDSP *dsp, int zone_idx, int cutoff_cc, int resonance_cc, int tone_cc) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    if (cutoff_cc < 0) cutoff_cc = 0;
    if (cutoff_cc > 127) cutoff_cc = 127;
    if (resonance_cc < 0) resonance_cc = 0;
    if (resonance_cc > 127) resonance_cc = 127;
    if (tone_cc < 0) tone_cc = 0;
    if (tone_cc > 127) tone_cc = 127;

    ZoneState *zs = &dsp->zones[zone_idx];
    __atomic_store_n(&zs->cutoff_cc, cutoff_cc, __ATOMIC_RELEASE);
    __atomic_store_n(&zs->resonance_cc, resonance_cc, __ATOMIC_RELEASE);
    __atomic_store_n(&zs->tone_cc, tone_cc, __ATOMIC_RELEASE);
    __atomic_store_n(&zs->filters_dirty, 1, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_eq(
    StageRigDSP *dsp,
    int zone_idx,
    float low_db,
    float low_mid_db,
    float mid_db,
    float high_mid_db,
    float high_db
) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    float vals[NUM_EQ_BANDS] = {low_db, low_mid_db, mid_db, high_mid_db, high_db};
    ZoneState *zs = &dsp->zones[zone_idx];
    for (int b = 0; b < NUM_EQ_BANDS; b++) {
        float v = vals[b];
        if (!isfinite(v)) v = 0.0f;
        if (v < -12.0f) v = -12.0f;
        if (v > 12.0f) v = 12.0f;
        int tenths = (int)roundf(v * 10.0f);
        __atomic_store_n(&zs->eq_tenths_db[b], tenths, __ATOMIC_RELEASE);
    }
    __atomic_store_n(&zs->filters_dirty, 1, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_zone_params(
    StageRigDSP *dsp,
    int zone_idx,
    int transpose,
    int key_low,
    int key_hi,
    int vel_low,
    int vel_hi,
    int sustain_enable,
    int expr_enable
) {
    if (!dsp || zone_idx < 0 || zone_idx >= NUM_ZONES) return;
    ZoneState *zs = &dsp->zones[zone_idx];
    int tr_clamped = (transpose < -36) ? -36 : ((transpose > 36) ? 36 : transpose);
    int old_tr = __atomic_exchange_n(&zs->transpose, tr_clamped, __ATOMIC_ACQ_REL);
    if (old_tr != tr_clamped) {
        rt_enqueue_event(dsp, EVT_ZONE_FLUSH_NOTES, (uint8_t)zone_idx, 0, 0);
    }
    __atomic_store_n(&zs->key_low, (key_low < 0) ? 0 : ((key_low > 127) ? 127 : key_low), __ATOMIC_RELEASE);
    __atomic_store_n(&zs->key_hi, (key_hi < 0) ? 0 : ((key_hi > 127) ? 127 : key_hi), __ATOMIC_RELEASE);
    __atomic_store_n(&zs->vel_low, (vel_low < 0) ? 0 : ((vel_low > 127) ? 127 : vel_low), __ATOMIC_RELEASE);
    __atomic_store_n(&zs->vel_hi, (vel_hi < 0) ? 0 : ((vel_hi > 127) ? 127 : vel_hi), __ATOMIC_RELEASE);
    __atomic_store_n(&zs->sustain_enable, sustain_enable ? 1 : 0, __ATOMIC_RELEASE);
    __atomic_store_n(&zs->expr_enable, expr_enable ? 1 : 0, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_bpm(StageRigDSP *dsp, float bpm) {
    if (!dsp) return;
    update_delay_timing(dsp, bpm);
}

DSP_EXPORT void stagerig_set_master_fx(
    StageRigDSP *dsp,
    float rev_room,
    float rev_damp,
    float rev_level,
    float dly_feedback,
    float dly_level
) {
    if (!dsp) return;
    if (!isfinite(rev_room)) rev_room = 0.84f;
    if (!isfinite(rev_damp)) rev_damp = 0.28f;
    if (!isfinite(rev_level)) rev_level = 1.10f;
    if (!isfinite(dly_feedback)) dly_feedback = 0.36f;
    if (!isfinite(dly_level)) dly_level = 0.52f;

    if (rev_room < 0.1f) rev_room = 0.1f;
    if (rev_room > 0.96f) rev_room = 0.96f;
    if (rev_damp < 0.0f) rev_damp = 0.0f;
    if (rev_damp > 0.95f) rev_damp = 0.95f;
    if (rev_level < 0.0f) rev_level = 0.0f;
    if (rev_level > 2.2f) rev_level = 2.2f;
    if (dly_feedback < 0.0f) dly_feedback = 0.0f;
    if (dly_feedback > 0.85f) dly_feedback = 0.85f;
    if (dly_level < 0.0f) dly_level = 0.0f;
    if (dly_level > 1.5f) dly_level = 1.5f;

    __atomic_store_n(&dsp->rev_room_bits, f2u(rev_room), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->rev_damp_bits, f2u(rev_damp), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->rev_level_bits, f2u(rev_level), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->dly_fb_bits, f2u(dly_feedback), __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->dly_lvl_bits, f2u(dly_level), __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_pad_layer(StageRigDSP *dsp, int layer_idx, const float *interleaved_lr, int frames) {
    if (!dsp || layer_idx < 0 || layer_idx >= NUM_PAD_LAYERS || !interleaved_lr || frames <= 16) return;
    if (__atomic_load_n(&dsp->pad_lengths[layer_idx], __ATOMIC_ACQUIRE) > 0) return;
    size_t bytes = (size_t)frames * 2 * sizeof(float);
    float *copy = (float *)malloc(bytes);
    if (!copy) return;
    memcpy(copy, interleaved_lr, bytes);
    float *expected = NULL;
    if (__atomic_compare_exchange_n(&dsp->pad_bufs[layer_idx], &expected, copy, 0, __ATOMIC_RELEASE, __ATOMIC_RELAXED)) {
        __atomic_store_n(&dsp->pad_lengths[layer_idx], frames, __ATOMIC_RELEASE);
    } else {
        free(copy);
    }
}

DSP_EXPORT void stagerig_set_pad_layers_ex(
    StageRigDSP *dsp,
    int playing,
    float rate,
    const int *vols,
    const int *mutes,
    int count
) {
    if (!dsp) return;
    if (!isfinite(rate) || rate < 0.25f || rate > 4.0f) rate = 1.0f;
    __atomic_store_n(&dsp->pad_playing, playing ? 1 : 0, __ATOMIC_RELEASE);
    int n = (count < NUM_PAD_LAYERS) ? count : NUM_PAD_LAYERS;
    for (int i = 0; i < n; i++) {
        if (vols) {
            int vc = vols[i] < 0 ? 0 : (vols[i] > 127 ? 127 : vols[i]);
            __atomic_store_n(&dsp->pad_layer_vols[i], vc, __ATOMIC_RELEASE);
        }
        if (mutes) {
            __atomic_store_n(&dsp->pad_layer_mutes[i], mutes[i] ? 1 : 0, __ATOMIC_RELEASE);
        }
    }
    float old_rate = u2f(__atomic_load_n(&dsp->pad_rate_bits, __ATOMIC_ACQUIRE));
    if (fabsf(rate - old_rate) > 1e-5f) {
        __atomic_store_n(&dsp->pad_rate_bits, f2u(rate), __ATOMIC_RELEASE);
        __atomic_add_fetch(&dsp->pad_rate_ver, 1U, __ATOMIC_RELEASE);
    }
}

DSP_EXPORT void stagerig_set_pad_state(
    StageRigDSP *dsp,
    int playing,
    float rate,
    int v0,
    int v1,
    int v2,
    int m0,
    int m1,
    int m2
) {
    int vols[3] = {v0, v1, v2};
    int mutes[3] = {m0, m1, m2};
    stagerig_set_pad_layers_ex(dsp, playing, rate, vols, mutes, 3);
}

DSP_EXPORT void stagerig_set_masters_state(
    StageRigDSP *dsp,
    int synth_vol,
    int synth_muted,
    int pad_vol,
    int pad_muted
) {
    if (!dsp) return;
    int sv = synth_vol < 0 ? 0 : (synth_vol > 127 ? 127 : synth_vol);
    int pv = pad_vol < 0 ? 0 : (pad_vol > 127 ? 127 : pad_vol);
    __atomic_store_n(&dsp->synth_master_vol, sv, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->synth_master_muted, synth_muted ? 1 : 0, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->pad_master_vol, pv, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->pad_master_muted, pad_muted ? 1 : 0, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_set_master_state(StageRigDSP *dsp, int volume, int muted, int target_mode) {
    if (!dsp) return;
    int vc = volume < 0 ? 0 : (volume > 127 ? 127 : volume);
    int m = muted ? 1 : 0;
    if (target_mode == 1) {
        __atomic_store_n(&dsp->synth_master_vol, vc, __ATOMIC_RELEASE);
        __atomic_store_n(&dsp->synth_master_muted, m, __ATOMIC_RELEASE);
    } else if (target_mode == 2) {
        __atomic_store_n(&dsp->pad_master_vol, vc, __ATOMIC_RELEASE);
        __atomic_store_n(&dsp->pad_master_muted, m, __ATOMIC_RELEASE);
    } else {
        stagerig_set_masters_state(dsp, vc, m, vc, m);
    }
}

DSP_EXPORT void stagerig_set_drum_pad_sample(StageRigDSP *dsp, int pad_idx, const float *interleaved_lr, int frames) {
    if (!dsp || pad_idx < 0 || pad_idx >= NUM_DRUM_PADS) return;
    float *copy = NULL;
    if (interleaved_lr && frames > 4) {
        size_t bytes = (size_t)frames * 2 * sizeof(float);
        copy = (float *)malloc(bytes);
        if (!copy) return;
        memcpy(copy, interleaved_lr, bytes);
    } else {
        frames = 0;
    }
    rig_mutex_lock(&dsp->drum_lock);
    for (int v = 0; v < MAX_DRUM_VOICES; v++) {
        if (dsp->drum_voices[v].active && dsp->drum_voices[v].pad_idx == pad_idx) {
            dsp->drum_voices[v].active = 0;
        }
    }
    float *old = dsp->drum_bufs[pad_idx];
    dsp->drum_bufs[pad_idx] = copy;
    dsp->drum_lengths[pad_idx] = frames;
    rig_mutex_unlock(&dsp->drum_lock);
    if (old) free(old);
}

DSP_EXPORT void stagerig_set_drum_pad_params(StageRigDSP *dsp, int pad_idx, int vol_cc, int muted, int loop) {
    if (!dsp || pad_idx < 0 || pad_idx >= NUM_DRUM_PADS) return;
    int vc = vol_cc < 0 ? 0 : (vol_cc > 127 ? 127 : vol_cc);
    __atomic_store_n(&dsp->drum_vols[pad_idx], vc, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->drum_mutes[pad_idx], muted ? 1 : 0, __ATOMIC_RELEASE);
    __atomic_store_n(&dsp->drum_loops[pad_idx], loop ? 1 : 0, __ATOMIC_RELEASE);
}

DSP_EXPORT void stagerig_trigger_drum_pad(StageRigDSP *dsp, int pad_idx, int velocity, int stop_only) {
    if (!dsp || pad_idx < 0 || pad_idx >= NUM_DRUM_PADS) return;
    int v = velocity < 1 ? 100 : (velocity > 127 ? 127 : velocity);
    rt_enqueue_event(dsp, EVT_DRUM_TRIGGER, (uint8_t)pad_idx, (int16_t)v, (int16_t)(stop_only ? 1 : 0));
}

DSP_EXPORT void stagerig_note_on(StageRigDSP *dsp, int note, int velocity) {
    if (!dsp || !dsp->synth || note < 0 || note > 127) return;
    rt_enqueue_event(dsp, EVT_NOTE_ON, 0, (int16_t)note, (int16_t)velocity);
}

DSP_EXPORT void stagerig_note_off(StageRigDSP *dsp, int note) {
    if (!dsp || !dsp->synth || note < 0 || note > 127) return;
    rt_enqueue_event(dsp, EVT_NOTE_OFF, 0, (int16_t)note, 0);
}

DSP_EXPORT void stagerig_send_performance_cc(StageRigDSP *dsp, int cc_num, int val) {
    if (!dsp || !dsp->synth) return;
    rt_enqueue_event(dsp, EVT_PERF_CC, 0, (int16_t)cc_num, (int16_t)val);
}

DSP_EXPORT void stagerig_pitch_bend(StageRigDSP *dsp, int bend_val) {
    if (!dsp || !dsp->synth) return;
    rt_enqueue_event(dsp, EVT_PITCH_BEND, 0, (int16_t)bend_val, 0);
}

DSP_EXPORT void stagerig_panic(StageRigDSP *dsp) {
    if (!dsp || !dsp->synth) return;
    rt_enqueue_event(dsp, EVT_PANIC, 0, 0, 0);
}

DSP_EXPORT void stagerig_get_telemetry_v2(
    StageRigDSP *dsp,
    float *out_zone_peaks,
    float *out_pad_peaks,
    float *out_drum_peaks,
    float *out_synth_master_peak,
    float *out_pad_master_peak,
    float *out_master_peak,
    int *out_voices
) {
    if (!dsp) return;
#ifdef __ANDROID__
    maintain_quality(dsp);
#endif
    for (int z = 0; z < NUM_ZONES; z++) {
        uint32_t bits = __atomic_exchange_n(&dsp->zones[z].peak_vu_bits, 0U, __ATOMIC_ACQ_REL);
        if (out_zone_peaks) out_zone_peaks[z] = u2f(bits);
    }
    for (int p = 0; p < NUM_PAD_LAYERS; p++) {
        uint32_t bits = __atomic_exchange_n(&dsp->pad_peak_bits[p], 0U, __ATOMIC_ACQ_REL);
        if (out_pad_peaks) out_pad_peaks[p] = u2f(bits);
    }
    for (int d = 0; d < NUM_DRUM_PADS; d++) {
        uint32_t bits = __atomic_exchange_n(&dsp->drum_peak_bits[d], 0U, __ATOMIC_ACQ_REL);
        if (out_drum_peaks) out_drum_peaks[d] = u2f(bits);
    }
    uint32_t sm_bits = __atomic_exchange_n(&dsp->synth_master_peak_bits, 0U, __ATOMIC_ACQ_REL);
    uint32_t pm_bits = __atomic_exchange_n(&dsp->pad_master_peak_bits, 0U, __ATOMIC_ACQ_REL);
    uint32_t m_bits = __atomic_exchange_n(&dsp->master_peak_bits, 0U, __ATOMIC_ACQ_REL);
    if (out_synth_master_peak) *out_synth_master_peak = u2f(sm_bits);
    if (out_pad_master_peak) *out_pad_master_peak = u2f(pm_bits);
    if (out_master_peak) *out_master_peak = u2f(m_bits);
    if (out_voices) *out_voices = __atomic_load_n(&dsp->active_voices, __ATOMIC_RELAXED);
}

DSP_EXPORT void stagerig_get_telemetry_ex(
    StageRigDSP *dsp,
    float *out_zone_peaks,
    float *out_pad_peaks,
    float *out_master_peak,
    int *out_voices
) {
    float pad5[NUM_PAD_LAYERS] = {0};
    stagerig_get_telemetry_v2(dsp, out_zone_peaks, pad5, NULL, NULL, NULL, out_master_peak, out_voices);
    if (out_pad_peaks) {
        for (int i = 0; i < 3; i++) out_pad_peaks[i] = pad5[i];
    }
}

DSP_EXPORT void stagerig_get_telemetry(StageRigDSP *dsp, float *out_zone_peaks, float *out_master_peak, int *out_voices) {
    stagerig_get_telemetry_v2(dsp, out_zone_peaks, NULL, NULL, NULL, NULL, out_master_peak, out_voices);
}

/* =========================================================================
 * REAL-TIME AUDIO BLOCK RENDERER (SYNTH + 5-LAYER PAD + 4 DRUMS + FX + LIMITER)
 * ========================================================================= */
DSP_EXPORT void stagerig_render_block(StageRigDSP *dsp, float *out_interleaved_lr, int frames) {
    if (!dsp || !dsp->synth || !out_interleaved_lr || frames <= 0) return;

    int done = 0;
    while (done < frames) {
        int chunk = frames - done;
        if (chunk > MAX_BLOCK_FRAMES) chunk = MAX_BLOCK_FRAMES;

        if (rig_mutex_trylock(&dsp->sf_lock) == 0) {
            drain_event_ring(dsp);
            rig_mutex_unlock(&dsp->sf_lock);
        }

        float *out_ptrs[NUM_ZONES * 2];
        for (int i = 0; i < NUM_ZONES * 2; i++) {
            memset(dsp->zone_bufs[i], 0, (size_t)chunk * sizeof(float));
            out_ptrs[i] = dsp->zone_bufs[i];
        }

        fluid_synth_process(dsp->synth, chunk, 0, NULL, NUM_ZONES * 2, out_ptrs);
        if (rig_mutex_trylock(&dsp->sf_lock) == 0) {
            __atomic_store_n(&dsp->active_voices, fluid_synth_get_active_voice_count(dsp->synth), __ATOMIC_RELAXED);
            rig_mutex_unlock(&dsp->sf_lock);
        }

        int any_solo = __atomic_load_n(&dsp->any_solo, __ATOMIC_ACQUIRE);
        int delay_samp_l = __atomic_load_n(&dsp->delay_samples_l, __ATOMIC_ACQUIRE);
        int delay_samp_r = __atomic_load_n(&dsp->delay_samples_r, __ATOMIC_ACQUIRE);

        float target_gains[NUM_ZONES];
        float target_rev[NUM_ZONES];
        float target_dly[NUM_ZONES];
        float target_cho[NUM_ZONES];
        float target_pan_l[NUM_ZONES];
        float target_pan_r[NUM_ZONES];

        for (int z = 0; z < NUM_ZONES; z++) {
            ZoneState *zs = &dsp->zones[z];
            if (__atomic_exchange_n(&zs->filters_dirty, 0, __ATOMIC_ACQ_REL)) {
                update_zone_filters(zs, (double)dsp->sample_rate);
            }

            int muted = __atomic_load_n(&zs->muted, __ATOMIC_ACQUIRE);
            int soloed = __atomic_load_n(&zs->soloed, __ATOMIC_ACQUIRE);
            int vol_cc = __atomic_load_n(&zs->volume_cc, __ATOMIC_ACQUIRE);
            int rev_cc = __atomic_load_n(&zs->reverb_cc, __ATOMIC_ACQUIRE);
            int dly_cc = __atomic_load_n(&zs->delay_cc, __ATOMIC_ACQUIRE);
            int cho_cc = __atomic_load_n(&zs->chorus_cc, __ATOMIC_ACQUIRE);
            int pan_cc = __atomic_load_n(&zs->pan_cc, __ATOMIC_ACQUIRE);

            int eff_active = any_solo ? (soloed && !muted) : (!muted);
            if (!eff_active || vol_cc <= 0) {
                target_gains[z] = 0.0f;
            } else {
                float norm = (float)vol_cc / 127.0f;
                target_gains[z] = powf(norm, 1.35f) * 1.05f;
            }
            target_rev[z] = ((float)rev_cc / 127.0f) * 0.72f;
            target_dly[z] = ((float)dly_cc / 127.0f) * 0.65f;
            target_cho[z] = ((float)cho_cc / 127.0f) * 0.52f;

            float pan_norm = (float)pan_cc / 127.0f;
            target_pan_l[z] = (pan_norm <= 0.5f) ? 1.0f : (1.0f - (pan_norm - 0.5f) * 2.0f);
            target_pan_r[z] = (pan_norm >= 0.5f) ? 1.0f : (pan_norm * 2.0f);
        }

        /* Independent Master gain ramp for Synth & Pad */
        int sm_vol = __atomic_load_n(&dsp->synth_master_vol, __ATOMIC_ACQUIRE);
        int sm_mute = __atomic_load_n(&dsp->synth_master_muted, __ATOMIC_ACQUIRE);
        int pm_vol = __atomic_load_n(&dsp->pad_master_vol, __ATOMIC_ACQUIRE);
        int pm_mute = __atomic_load_n(&dsp->pad_master_muted, __ATOMIC_ACQUIRE);
        float tgt_synth_mg = (sm_mute || sm_vol <= 0) ? 0.0f : powf((float)sm_vol / 127.0f, 1.25f);
        float tgt_pad_mg = (pm_mute || pm_vol <= 0) ? 0.0f : powf((float)pm_vol / 127.0f, 1.25f);
        dsp->cur_synth_mg += 0.25f * (tgt_synth_mg - dsp->cur_synth_mg);
        dsp->cur_pad_mg += 0.25f * (tgt_pad_mg - dsp->cur_pad_mg);
        const float synth_mg = dsp->cur_synth_mg;
        const float pad_mg = dsp->cur_pad_mg;

        /* Worship Pad state & crossfade preparation */
        uint32_t rver = __atomic_load_n(&dsp->pad_rate_ver, __ATOMIC_ACQUIRE);
        if (rver != dsp->seen_pad_rate_ver) {
            dsp->seen_pad_rate_ver = rver;
            dsp->pad_rate_b = dsp->pad_rate_a;
            dsp->pad_pos_b = dsp->pad_pos_a;
            dsp->pad_rate_a = (double)u2f(__atomic_load_n(&dsp->pad_rate_bits, __ATOMIC_ACQUIRE));
            dsp->pad_xfade_mix = 1.0f;
        }

        int p_playing = __atomic_load_n(&dsp->pad_playing, __ATOMIC_ACQUIRE);
        int pad_len_ref = 0;
        for (int l = 0; l < NUM_PAD_LAYERS; l++) {
            int ln = __atomic_load_n(&dsp->pad_lengths[l], __ATOMIC_ACQUIRE);
            if (ln > 16) {
                pad_len_ref = ln;
                break;
            }
        }
        int pad_active = (pad_len_ref > 16) && (p_playing || dsp->pad_env >= 0.0005f);

        float tgt_env = p_playing ? 1.0f : 0.0f;
        float env_start = dsp->pad_env;
        float env_step = (float)chunk / (dsp->sample_rate * 1.25f);
        float env_end = (env_start < tgt_env)
            ? fminf(tgt_env, env_start + env_step)
            : fmaxf(tgt_env, env_start - env_step);
        dsp->pad_env = env_end;
        float d_env = (env_end - env_start) / (float)chunk;

        float xf_start = dsp->pad_xfade_mix;
        float xf_step = (xf_start > 0.001f) ? ((float)chunk / (dsp->sample_rate * 1.15f)) : 0.0f;
        float xf_end = fmaxf(0.0f, xf_start - xf_step);
        dsp->pad_xfade_mix = xf_end;
        float d_xf = (xf_end - xf_start) / (float)chunk;
        int do_xfade = (xf_start > 0.001f);

        const float *pad_ptr[NUM_PAD_LAYERS] = {NULL};
        int pad_lens[NUM_PAD_LAYERS] = {0};
        float pad_lg[NUM_PAD_LAYERS] = {0};
        int any_pad_layer = 0;

        if (pad_active) {
            for (int l = 0; l < NUM_PAD_LAYERS; l++) {
                int len = __atomic_load_n(&dsp->pad_lengths[l], __ATOMIC_ACQUIRE);
                int lv = __atomic_load_n(&dsp->pad_layer_vols[l], __ATOMIC_ACQUIRE);
                int lm = __atomic_load_n(&dsp->pad_layer_mutes[l], __ATOMIC_ACQUIRE);
                float tg = lm ? 0.0f : powf((float)lv / 127.0f, 1.35f);
                float ng = dsp->cur_pad_gains[l] + 0.25f * (tg - dsp->cur_pad_gains[l]);
                dsp->cur_pad_gains[l] = ng;
                if (len > 16 && dsp->pad_bufs[l] && ng >= 0.0005f) {
                    pad_ptr[l] = dsp->pad_bufs[l];
                    pad_lens[l] = len;
                    pad_lg[l] = ng;
                    any_pad_layer = 1;
                    float pv = ng * env_end * pad_mg;
                    atomic_max_float_bits(&dsp->pad_peak_bits[l], pv);
                }
            }
            if (!any_pad_layer) {
                dsp->pad_pos_a = fmod(dsp->pad_pos_a + (double)chunk * dsp->pad_rate_a * dsp->pad_sr_comp, (double)pad_len_ref);
                if (do_xfade) {
                    dsp->pad_pos_b = fmod(dsp->pad_pos_b + (double)chunk * dsp->pad_rate_b * dsp->pad_sr_comp, (double)pad_len_ref);
                }
            }
        }

        int drum_lock_held = (rig_mutex_trylock(&dsp->drum_lock) == 0);
        float drum_pad_gains[NUM_DRUM_PADS] = {0};
        int drum_pad_loops[NUM_DRUM_PADS] = {0};
        float drum_block_peaks[NUM_DRUM_PADS] = {0};
        if (drum_lock_held) {
            for (int d = 0; d < NUM_DRUM_PADS; d++) {
                int dm = __atomic_load_n(&dsp->drum_mutes[d], __ATOMIC_ACQUIRE);
                int dv = __atomic_load_n(&dsp->drum_vols[d], __ATOMIC_ACQUIRE);
                drum_pad_gains[d] = (dm || dv <= 0) ? 0.0f : powf((float)dv / 127.0f, 1.25f);
                drum_pad_loops[d] = __atomic_load_n(&dsp->drum_loops[d], __ATOMIC_ACQUIRE);
            }
        }

        float *dst = out_interleaved_lr + (done * 2);
        float block_master_peak = 0.0f;
        float block_synth_peak = 0.0f;
        float block_pad_peak = 0.0f;
        float zone_block_peaks[NUM_ZONES] = {0.0f, 0.0f, 0.0f, 0.0f};

        const float smooth_a = 0.0055f;
        const float lim_att = 1.0f - expf(-1.0f / (0.00015f * dsp->sample_rate));
        const float lim_rel = 1.0f - expf(-1.0f / (0.15f * dsp->sample_rate));
        float lim_gain = dsp->lim_gain;
        const float room = u2f(__atomic_load_n(&dsp->rev_room_bits, __ATOMIC_ACQUIRE));
        const float damp1 = u2f(__atomic_load_n(&dsp->rev_damp_bits, __ATOMIC_ACQUIRE));
        const float damp2 = 1.0f - damp1;
        const float rev_lvl = u2f(__atomic_load_n(&dsp->rev_level_bits, __ATOMIC_ACQUIRE));
        const float dly_fb = u2f(__atomic_load_n(&dsp->dly_fb_bits, __ATOMIC_ACQUIRE));
        const float dly_lvl = u2f(__atomic_load_n(&dsp->dly_lvl_bits, __ATOMIC_ACQUIRE));
        const double chorus_phase_inc = (2.0 * M_PI * 0.85) / (double)dsp->sample_rate;
        /* Chorus delay centre/depth are defined in time (not samples) so pitch modulation is identical at any rate.
         * Depth 1.2 ms @ 0.85 Hz = about +/-11 cents (the old +/-165 samples gave +/-30 cents: audible detune). */
        const float ch_center_l = 0.0100f * dsp->sample_rate;
        const float ch_center_r = 0.0110f * dsp->sample_rate;
        const float ch_depth = 0.0012f * dsp->sample_rate;
        int fx_bad = 0;

        double pos_a = dsp->pad_pos_a;
        double pos_b = dsp->pad_pos_b;
        if (pad_len_ref > 16) {
            if (!(pos_a >= 0.0) || pos_a >= (double)pad_len_ref) pos_a = fmod(fabs(pos_a), (double)pad_len_ref);
            if (!(pos_b >= 0.0) || pos_b >= (double)pad_len_ref) pos_b = fmod(fabs(pos_b), (double)pad_len_ref);
        }
        const double rate_a = dsp->pad_rate_a * dsp->pad_sr_comp;
        const double rate_b = dsp->pad_rate_b * dsp->pad_sr_comp;

        for (int i = 0; i < chunk; i++) {
            float dry_l = 0.0f;
            float dry_r = 0.0f;
            float rev_in = 0.0f;
            float dly_in_l = 0.0f;
            float dly_in_r = 0.0f;

            for (int z = 0; z < NUM_ZONES; z++) {
                ZoneState *zs = &dsp->zones[z];
                zs->cur_gain += smooth_a * (target_gains[z] - zs->cur_gain);
                zs->cur_rev_send += smooth_a * (target_rev[z] - zs->cur_rev_send);
                zs->cur_dly_send += smooth_a * (target_dly[z] - zs->cur_dly_send);
                zs->cur_chorus_mix += smooth_a * (target_cho[z] - zs->cur_chorus_mix);
                zs->cur_pan_l += smooth_a * (target_pan_l[z] - zs->cur_pan_l);
                zs->cur_pan_r += smooth_a * (target_pan_r[z] - zs->cur_pan_r);

                float g = zs->cur_gain;
                if (g < 0.0001f) continue;

                float zl = sanitize_audio(dsp->zone_bufs[z * 2][i], 4.0f) * g * zs->cur_pan_l;
                float zr = sanitize_audio(dsp->zone_bufs[z * 2 + 1][i], 4.0f) * g * zs->cur_pan_r;

                for (int b = 0; b < NUM_EQ_BANDS; b++) {
                    if (zs->eq_biquads[b].active) {
                        process_stereo_biquad(&zs->eq_biquads[b], &zl, &zr);
                    }
                }
                if (zs->lpf_biquad.active) {
                    process_stereo_biquad(&zs->lpf_biquad, &zl, &zr);
                }
                if (zs->tone_biquad.active) {
                    process_stereo_biquad(&zs->tone_biquad, &zl, &zr);
                }

                /* Stereo Quadrature Modulated Chorus */
                int cw = zs->chorus_idx;
                zs->chorus_buf_l[cw] = zl;
                zs->chorus_buf_r[cw] = zr;
                zs->chorus_idx = (cw + 1) & CHORUS_BUF_MASK;
                if (zs->cur_chorus_mix > 0.001f) {
                    zs->chorus_phase += chorus_phase_inc;
                    if (zs->chorus_phase >= 2.0 * M_PI) zs->chorus_phase -= 2.0 * M_PI;
                    float ph = (float)zs->chorus_phase;
                    float mod_l = ch_center_l + ch_depth * sinf(ph);
                    float mod_r = ch_center_r + ch_depth * cosf(ph);
                    int il = (int)mod_l;
                    int ir = (int)mod_r;
                    float fl = mod_l - (float)il;
                    float fr = mod_r - (float)ir;
                    int l0 = (cw - il) & CHORUS_BUF_MASK;
                    int l1 = (cw - il - 1) & CHORUS_BUF_MASK;
                    int r0 = (cw - ir) & CHORUS_BUF_MASK;
                    int r1 = (cw - ir - 1) & CHORUS_BUF_MASK;
                    float wl = zs->chorus_buf_l[l0] + fl * (zs->chorus_buf_l[l1] - zs->chorus_buf_l[l0]);
                    float wr = zs->chorus_buf_r[r0] + fr * (zs->chorus_buf_r[r1] - zs->chorus_buf_r[r0]);
                    zl += wl * zs->cur_chorus_mix;
                    zr += wr * zs->cur_chorus_mix;
                }

                float abs_z = fabsf(zl) > fabsf(zr) ? fabsf(zl) : fabsf(zr);
                if (abs_z > zone_block_peaks[z]) zone_block_peaks[z] = abs_z;

                dry_l += zl;
                dry_r += zr;

                float mono_z = (zl + zr) * 0.5f;
                rev_in += mono_z * zs->cur_rev_send;
                dly_in_l += zl * zs->cur_dly_send;
                dly_in_r += zr * zs->cur_dly_send;
            }

            /* --- 1. BPM-Synced Stereo Ping-Pong Tape Delay --- */
            int w_idx = dsp->delay_write_idx;
            int r_idx_l = (w_idx - delay_samp_l) & DELAY_BUF_MASK;
            int r_idx_r = (w_idx - delay_samp_r) & DELAY_BUF_MASK;

            float tap_l = dsp->delay_buf_l[r_idx_l];
            float tap_r = dsp->delay_buf_r[r_idx_r];

            dsp->delay_lp_l = 0.55f * tap_l + 0.45f * dsp->delay_lp_l;
            dsp->delay_lp_r = 0.55f * tap_r + 0.45f * dsp->delay_lp_r;

            dsp->delay_buf_l[w_idx] = dly_in_l + dsp->delay_lp_r * dly_fb;
            dsp->delay_buf_r[w_idx] = dly_in_r + dsp->delay_lp_l * dly_fb;
            dsp->delay_write_idx = (w_idx + 1) & DELAY_BUF_MASK;

            rev_in = rev_in + (dsp->delay_lp_l + dsp->delay_lp_r) * 0.16f;

            /* --- 2. Stereo Cathedral Reverb --- */
            float rev_l = 0.0f;
            float rev_r = 0.0f;
            float scaled_rev_in = rev_in * 0.032f;

            for (int c = 0; c < NUM_COMBS; c++) {
                CombFilter *cl = &dsp->combs_l[c];
                float out_l = cl->buf[cl->idx];
                cl->filterstore = (out_l * damp2) + (cl->filterstore * damp1);
                cl->buf[cl->idx] = scaled_rev_in + (cl->filterstore * room);
                if (++cl->idx >= cl->size) cl->idx = 0;
                rev_l += out_l;

                CombFilter *cr = &dsp->combs_r[c];
                float out_r = cr->buf[cr->idx];
                cr->filterstore = (out_r * damp2) + (cr->filterstore * damp1);
                cr->buf[cr->idx] = scaled_rev_in + (cr->filterstore * room);
                if (++cr->idx >= cr->size) cr->idx = 0;
                rev_r += out_r;
            }

            for (int a = 0; a < NUM_ALLPASS; a++) {
                AllpassFilter *al = &dsp->allpass_l[a];
                float bufl = al->buf[al->idx];
                float in_l = rev_l;
                rev_l = -in_l + bufl;
                al->buf[al->idx] = in_l + (bufl * 0.5f);
                if (++al->idx >= al->size) al->idx = 0;

                AllpassFilter *ar = &dsp->allpass_r[a];
                float bufr = ar->buf[ar->idx];
                float in_r = rev_r;
                rev_r = -in_r + bufr;
                ar->buf[ar->idx] = in_r + (bufr * 0.5f);
                if (++ar->idx >= ar->size) ar->idx = 0;
            }

            /* NaN / runaway guard for the whole FX chain (checked once per sample, fixed after the block) */
            if (!(fabsf(rev_l) < 64.0f) || !(fabsf(rev_r) < 64.0f) ||
                !(fabsf(dsp->delay_lp_l) < 64.0f) || !(fabsf(dsp->delay_lp_r) < 64.0f)) {
                fx_bad = 1;
                rev_l = 0.0f;
                rev_r = 0.0f;
                dsp->delay_lp_l = 0.0f;
                dsp->delay_lp_r = 0.0f;
            }

            float synth_l = sanitize_audio((dry_l + dsp->delay_lp_l * dly_lvl + rev_l * rev_lvl) * synth_mg, 4.0f);
            float synth_r = sanitize_audio((dry_r + dsp->delay_lp_r * dly_lvl + rev_r * rev_lvl) * synth_mg, 4.0f);
            float abs_sm = fabsf(synth_l) > fabsf(synth_r) ? fabsf(synth_l) : fabsf(synth_r);
            if (abs_sm > block_synth_peak) block_synth_peak = abs_sm;

            /* --- 3. Continuous 5-Layer Worship Pad Mix (Zero-Alloc C) --- */
            float pad_l = 0.0f;
            float pad_r = 0.0f;
            if (any_pad_layer) {
                float mix_a_l = 0.0f, mix_a_r = 0.0f;
                int ia0 = (int)pos_a;
                float fa = (float)(pos_a - (double)ia0);
                for (int l = 0; l < NUM_PAD_LAYERS; l++) {
                    if (!pad_ptr[l]) continue;
                    int len = pad_lens[l];
                    int i0 = (len == pad_len_ref) ? ia0 : (ia0 % len);
                    int i1 = i0 + 1;
                    if (i1 >= len) i1 = 0;
                    const float *b = pad_ptr[l];
                    float sl = b[i0 * 2] + fa * (b[i1 * 2] - b[i0 * 2]);
                    float sr_s = b[i0 * 2 + 1] + fa * (b[i1 * 2 + 1] - b[i0 * 2 + 1]);
                    mix_a_l += sl * pad_lg[l];
                    mix_a_r += sr_s * pad_lg[l];
                }
                pos_a += rate_a;
                while (pos_a >= (double)pad_len_ref) pos_a -= (double)pad_len_ref;

                if (do_xfade) {
                    float mix_b_l = 0.0f, mix_b_r = 0.0f;
                    int ib0 = (int)pos_b;
                    float fb = (float)(pos_b - (double)ib0);
                    for (int l = 0; l < NUM_PAD_LAYERS; l++) {
                        if (!pad_ptr[l]) continue;
                        int len = pad_lens[l];
                        int i0 = (len == pad_len_ref) ? ib0 : (ib0 % len);
                        int i1 = i0 + 1;
                        if (i1 >= len) i1 = 0;
                        const float *b = pad_ptr[l];
                        float sl = b[i0 * 2] + fb * (b[i1 * 2] - b[i0 * 2]);
                        float sr_s = b[i0 * 2 + 1] + fb * (b[i1 * 2 + 1] - b[i0 * 2 + 1]);
                        mix_b_l += sl * pad_lg[l];
                        mix_b_r += sr_s * pad_lg[l];
                    }
                    pos_b += rate_b;
                    while (pos_b >= (double)pad_len_ref) pos_b -= (double)pad_len_ref;

                    float xf = xf_start + (float)i * d_xf;
                    if (xf < 0.0f) xf = 0.0f;
                    if (xf > 1.0f) xf = 1.0f;
                    float ang = xf * (float)(M_PI * 0.5);
                    float gain_b = sinf(ang);
                    float gain_a = cosf(ang);
                    pad_l = mix_a_l * gain_a + mix_b_l * gain_b;
                    pad_r = mix_a_r * gain_a + mix_b_r * gain_b;
                } else {
                    pad_l = mix_a_l;
                    pad_r = mix_a_r;
                }

                float cur_env = env_start + (float)i * d_env;
                if (cur_env < 0.0f) cur_env = 0.0f;
                if (cur_env > 1.0f) cur_env = 1.0f;
                float pad_scale = cur_env * 0.76f * pad_mg;
                pad_l *= pad_scale;
                pad_r *= pad_scale;
                float abs_pm = fabsf(pad_l) > fabsf(pad_r) ? fabsf(pad_l) : fabsf(pad_r);
                if (abs_pm > block_pad_peak) block_pad_peak = abs_pm;
            }

            /* --- 4. 4-Slot Stereo Drum Pads Mix --- */
            float drum_l = 0.0f;
            float drum_r = 0.0f;
            if (drum_lock_held) {
                for (int v = 0; v < MAX_DRUM_VOICES; v++) {
                    DrumVoice *dv = &dsp->drum_voices[v];
                    if (!dv->active) continue;
                    int pidx = dv->pad_idx;
                    const float *dbuf = dsp->drum_bufs[pidx];
                    int dlen = dsp->drum_lengths[pidx];
                    if (!dbuf || dlen <= 0) {
                        dv->active = 0;
                        continue;
                    }
                    if (dv->pos >= dlen) {
                        if (drum_pad_loops[pidx]) {
                            dv->pos = 0;
                        } else {
                            dv->active = 0;
                            continue;
                        }
                    }
                    float dg = drum_pad_gains[pidx] * dv->vel_gain;
                    float dl = dbuf[dv->pos * 2] * dg;
                    float dr = dbuf[dv->pos * 2 + 1] * dg;
                    dv->pos++;
                    drum_l += dl;
                    drum_r += dr;
                    float abs_d = fabsf(dl) > fabsf(dr) ? fabsf(dl) : fabsf(dr);
                    if (abs_d > drum_block_peaks[pidx]) drum_block_peaks[pidx] = abs_d;
                }
            }

            /* --- 5. Sum & C1-Smooth Soft-Knee Master Limiter --- */
            float out_l = sanitize_audio(synth_l + pad_l + drum_l, 8.0f);
            float out_r = sanitize_audio(synth_r + pad_r + drum_r, 8.0f);

            /* Transparent peak limiter: unity gain below the threshold (no harmonic distortion), smooth
             * gain reduction above it, then a very gentle final safety soft-clip close to full scale. */
            float pk = fabsf(out_l);
            float pkr = fabsf(out_r);
            if (pkr > pk) pk = pkr;
            float lim_tgt = (pk > LIMITER_THRESH) ? (LIMITER_THRESH / pk) : 1.0f;
            if (lim_tgt < lim_gain) lim_gain += (lim_tgt - lim_gain) * lim_att;
            else lim_gain += (1.0f - lim_gain) * lim_rel;
            out_l *= lim_gain;
            out_r *= lim_gain;
            float al = fabsf(out_l);
            if (al > 0.95f) {
                float lim = 0.95f + 0.05f * tanhf((al - 0.95f) / 0.05f);
                out_l = (out_l >= 0.0f) ? lim : -lim;
            }
            float ar = fabsf(out_r);
            if (ar > 0.95f) {
                float lim = 0.95f + 0.05f * tanhf((ar - 0.95f) / 0.05f);
                out_r = (out_r >= 0.0f) ? lim : -lim;
            }

            dst[i * 2] = out_l;
            dst[i * 2 + 1] = out_r;

            float post_al = fabsf(out_l);
            float post_ar = fabsf(out_r);
            float abs_m = (post_al > post_ar) ? post_al : post_ar;
            if (abs_m > block_master_peak) block_master_peak = abs_m;
        }

        dsp->lim_gain = lim_gain;
        if (fx_bad) {
            memset(dsp->delay_buf_l, 0, sizeof(dsp->delay_buf_l));
            memset(dsp->delay_buf_r, 0, sizeof(dsp->delay_buf_r));
            clear_reverb_buffers(dsp);
        }

        if (drum_lock_held) {
            rig_mutex_unlock(&dsp->drum_lock);
            for (int d = 0; d < NUM_DRUM_PADS; d++) {
                float sd = drum_block_peaks[d] * 1.45f;
                if (sd > 1.0f) sd = 1.0f;
                atomic_max_float_bits(&dsp->drum_peak_bits[d], sd);
            }
        }

        if (any_pad_layer) {
            dsp->pad_pos_a = pos_a;
            if (do_xfade) dsp->pad_pos_b = pos_b;
        }

        for (int z = 0; z < NUM_ZONES; z++) {
            float scaled_z = zone_block_peaks[z] * 2.5f;
            if (scaled_z > 1.0f) scaled_z = 1.0f;
            atomic_max_float_bits(&dsp->zones[z].peak_vu_bits, scaled_z);
        }
        float scaled_sm = block_synth_peak * 1.65f;
        if (scaled_sm > 1.0f) scaled_sm = 1.0f;
        atomic_max_float_bits(&dsp->synth_master_peak_bits, scaled_sm);

        float scaled_pm = block_pad_peak * 1.65f;
        if (scaled_pm > 1.0f) scaled_pm = 1.0f;
        atomic_max_float_bits(&dsp->pad_master_peak_bits, scaled_pm);

        float scaled_m = block_master_peak * 1.65f;
        if (scaled_m > 1.0f) scaled_m = 1.0f;
        atomic_max_float_bits(&dsp->master_peak_bits, scaled_m);

        done += chunk;
    }
}
