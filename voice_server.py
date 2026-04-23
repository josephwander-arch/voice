#!/usr/bin/env python3
"""
Voice Input Server v2.0 - Enhanced Edition
Features:
  • faster-whisper with int8 CPU inference
  • Biquad noise filtering (80Hz HP + 8kHz LP)
  • Emotion detection via audio features
  • Triple beep, level monitoring, end phrase stripping
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import pyaudio
import struct
import traceback
import wave
import os
import tempfile
import time
import numpy as np
from urllib.parse import urlparse, parse_qs
from faster_whisper import WhisperModel
from scipy.signal import butter, lfilter
from scipy.fft import fft

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
SAMPLE_RATE = 16000
CHUNK_SIZE = 8000  # ~500ms chunks
BEEP_FREQ = 880
BEEP_DURATION = 0.15
BEEP_GAP = 0.08

# Default listen params — overridden by voice.config.toml [listen] section and per-call params
DEFAULT_SILENCE_TIMEOUT = 4.0
DEFAULT_RMS_THRESHOLD = 100
DEFAULT_MIN_SPEECH_DURATION = 3.0

END_PHRASES = [
    'send this', 'send it', 'done', "that's it", 'stop', 'exit',
    'over', 'end', 'finished', 'complete', 'go ahead', 'send'
]

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════
import tomllib
from pathlib import Path

def _find_config():
    candidates = [
        os.environ.get("VOICE_CONFIG_PATH"),
        "./voice.config.toml",
        os.path.join(os.path.expanduser("~"), ".config", "voice", "voice.config.toml"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None

VOICE_CONFIG_PATH = _find_config()

def get_listen_defaults():
    if VOICE_CONFIG_PATH is None:
        return {
            "silence_timeout": DEFAULT_SILENCE_TIMEOUT,
            "min_speech_duration": DEFAULT_MIN_SPEECH_DURATION,
            "rms_threshold": DEFAULT_RMS_THRESHOLD,
            "pre_record_enabled": True,
            "noise_filter_enabled": True,
        }
    try:
        with open(VOICE_CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        listen = config.get("listen", {})
        return {
            "silence_timeout": listen.get("silence_timeout_secs", DEFAULT_SILENCE_TIMEOUT),
            "min_speech_duration": listen.get("min_speech_duration_secs", DEFAULT_MIN_SPEECH_DURATION),
            "rms_threshold": listen.get("rms_threshold", DEFAULT_RMS_THRESHOLD),
            "pre_record_enabled": listen.get("pre_record_enabled", True),
            "noise_filter_enabled": listen.get("noise_filter_enabled", True),
        }
    except Exception:
        return {
            "silence_timeout": DEFAULT_SILENCE_TIMEOUT,
            "min_speech_duration": DEFAULT_MIN_SPEECH_DURATION,
            "rms_threshold": DEFAULT_RMS_THRESHOLD,
            "pre_record_enabled": True,
            "noise_filter_enabled": True,
        }

# ═══════════════════════════════════════════════════════════════════
# NOISE FILTERING
# ═══════════════════════════════════════════════════════════════════
def butter_highpass(cutoff, fs, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    return b, a

def butter_lowpass(cutoff, fs, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return b, a

def apply_noise_filter(samples, sample_rate=16000):
    """Apply highpass (80Hz) and lowpass (8kHz) filters"""
    # Highpass at 80Hz - removes low frequency hum/rumble
    b_hp, a_hp = butter_highpass(80, sample_rate)
    filtered = lfilter(b_hp, a_hp, samples)
    
    # Lowpass at 7500Hz - removes high frequency noise (must be < Nyquist)
    b_lp, a_lp = butter_lowpass(7500, sample_rate)
    filtered = lfilter(b_lp, a_lp, filtered)
    
    return filtered.astype(np.int16)

# ═══════════════════════════════════════════════════════════════════
# EMOTION DETECTION
# ═══════════════════════════════════════════════════════════════════
def extract_audio_features(samples, sample_rate=16000):
    """Extract features for emotion detection"""
    samples = samples.astype(np.float32) / 32768.0  # Normalize
    n = len(samples)
    
    if n == 0:
        return None
    
    # 1. Energy (RMS)
    energy = np.sqrt(np.mean(samples ** 2))
    
    # 2. Zero Crossing Rate
    zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / 2
    zcr = zero_crossings / n
    
    # 3. Spectral Centroid (brightness)
    fft_size = 2048
    spectral_centroids = []
    for i in range(0, n - fft_size, fft_size):
        chunk = samples[i:i + fft_size]
        spectrum = np.abs(fft(chunk)[:fft_size // 2])
        freqs = np.arange(fft_size // 2)
        
        if np.sum(spectrum) > 0:
            centroid = np.sum(freqs * spectrum) / np.sum(spectrum)
            spectral_centroids.append(centroid)
    
    spectral_centroid = np.mean(spectral_centroids) if spectral_centroids else 0
    
    # 4. Pitch variance via autocorrelation
    frame_size = 1024
    pitches = []
    for i in range(0, n - frame_size * 2, frame_size):
        chunk = samples[i:i + frame_size]
        corr = np.correlate(chunk, chunk, mode='full')
        corr = corr[len(corr) // 2:]
        
        # Find first peak after initial decay
        min_lag = sample_rate // 500  # Max 500Hz
        max_lag = sample_rate // 50   # Min 50Hz
        
        if max_lag < len(corr):
            peak_idx = np.argmax(corr[min_lag:max_lag]) + min_lag
            if corr[peak_idx] > 0.1:
                pitch = sample_rate / peak_idx
                pitches.append(pitch)
    
    pitch_variance = np.std(pitches) if len(pitches) > 1 else 0
    
    # 5. Speech rate estimate (voiced frame ratio)
    frame_ms = 20
    frame_samples = sample_rate * frame_ms // 1000
    energy_threshold = energy * 0.3
    voiced_frames = 0
    total_frames = 0
    
    for i in range(0, n, frame_samples):
        chunk = samples[i:i + frame_samples]
        if len(chunk) > 0:
            frame_energy = np.sqrt(np.mean(chunk ** 2))
            if frame_energy > energy_threshold:
                voiced_frames += 1
            total_frames += 1
    
    duration_secs = n / sample_rate
    speech_rate = (voiced_frames * 0.15) / duration_secs if duration_secs > 0 else 0
    
    return {
        'energy': float(energy),
        'zero_crossing_rate': float(zcr),
        'spectral_centroid': float(spectral_centroid),
        'pitch_variance': float(pitch_variance),
        'speech_rate': float(speech_rate)
    }

def detect_emotion(features):
    """Classify emotion from audio features"""
    if not features:
        return {'primary': 'neutral', 'confidence': 0.5, 'features': {}}
    
    # Normalize features to 0-1 range (calibrated 2026-01-21)
    # Raw values: energy ~0.003-0.006, pitch_var 0-25, rate 1-5, centroid 230-320, zcr 0.13-0.17
    norm_energy = min(features['energy'] * 180, 1.0)      # Was *10, too low
    norm_pitch_var = min(features['pitch_variance'] / 40, 1.0)  # Slightly more sensitive
    norm_rate = min(features['speech_rate'] / 6, 1.0)     # Adjusted for typical 2-5 range
    norm_centroid = min(features['spectral_centroid'] / 400, 1.0)  # Was /200, always maxed
    norm_zcr = min(features['zero_crossing_rate'] * 4, 1.0)  # Was *20, way too aggressive
    
    # Arousal = activation level (high energy + fast + rough)
    arousal = (norm_energy + norm_rate + norm_zcr) / 3
    
    # Valence indicator (pitch variance suggests expressiveness)
    valence = norm_pitch_var - norm_zcr * 0.5
    
    # Rule-based classification
    if arousal > 0.7:
        if valence > 0.3:
            emotion = 'excited'
            confidence = 0.6 + arousal * 0.3
        else:
            emotion = 'angry'
            confidence = 0.5 + arousal * 0.3
    elif arousal < 0.3:
        if norm_pitch_var < 0.2 and norm_rate < 0.3:
            emotion = 'sad'
            confidence = 0.5 + (1 - arousal) * 0.3
        else:
            emotion = 'calm'
            confidence = 0.5 + (1 - arousal) * 0.2
    else:
        if norm_pitch_var > 0.5 and norm_centroid > 0.4:
            emotion = 'happy'
            confidence = 0.4 + norm_pitch_var * 0.3
        else:
            emotion = 'neutral'
            confidence = 0.6
    
    return {
        'primary': emotion,
        'confidence': min(confidence, 0.95),
        'features': features
    }

# ═══════════════════════════════════════════════════════════════════
# MODEL LOADING
# ═══════════════════════════════════════════════════════════════════
print("╔══════════════════════════════════════════════════╗")
print("║      Voice Server v2.0 (Enhanced Python)        ║")
print("╠══════════════════════════════════════════════════╣")
print("║ Features:                                        ║")
print("║   • faster-whisper (CPU int8)                    ║")
print("║   • Biquad noise filtering                       ║")
print("║   • Emotion detection                            ║")
print("║   • Triple beep + level monitoring               ║")
print("╚══════════════════════════════════════════════════╝")
print()
print("[Voice] Loading Whisper model (base, int8)...")
try:
    model = WhisperModel("base", device="cpu", compute_type="int8")
except Exception as e:
    print(f"[Voice] ERROR: Failed to load Whisper model: {e}")
    print("[Voice] Make sure faster-whisper is installed: pip install faster-whisper")
    print("[Voice] The 'base' model will be downloaded automatically on first run (~150 MB).")
    raise
print("[Voice] Model loaded!")

# ═══════════════════════════════════════════════════════════════════
# HTTP HANDLER
# ═══════════════════════════════════════════════════════════════════
class VoiceHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[Voice] {args[0]}")
    
    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/listen':
            cfg = get_listen_defaults()
            timeout = int(params.get('timeout', [60])[0])
            skip_emotion = params.get('skip_emotion', ['true'])[0].lower() == 'true'
            skip_filter = params.get('skip_filter', [str(not cfg["noise_filter_enabled"]).lower()])[0].lower() == 'true'
            silence_timeout = float(params.get('silence_timeout', [cfg["silence_timeout"]])[0])
            min_speech_duration = float(params.get('min_speech_duration', [cfg["min_speech_duration"]])[0])
            rms_threshold = float(params.get('rms_threshold', [cfg["rms_threshold"]])[0])
            result = self.capture_voice(timeout, skip_emotion, skip_filter, silence_timeout, min_speech_duration, rms_threshold)
            self.send_json(result)
        else:
            self.send_json({'success': False, 'error': 'Unknown endpoint'})
    
    def do_GET(self):
        if self.path == '/status':
            self.send_json({
                'success': True, 
                'status': 'running',
                'version': '2.0',
                'features': [
                    'faster-whisper',
                    'noise-filtering',
                    'emotion-detection',
                    'triple-beep',
                    'level-monitoring'
                ]
            })
        else:
            self.send_json({'success': False, 'error': 'Use POST /listen'})
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def capture_voice(self, max_duration, skip_emotion=False, skip_filter=False, silence_timeout=None, min_speech_duration=None, rms_threshold=None):
        cfg = get_listen_defaults()
        silence_timeout = silence_timeout if silence_timeout is not None else cfg["silence_timeout"]
        min_speech_duration = min_speech_duration if min_speech_duration is not None else cfg["min_speech_duration"]
        rms_threshold = rms_threshold if rms_threshold is not None else cfg["rms_threshold"]

        p = None
        try:
            p = pyaudio.PyAudio()

            # ─────────────────────────────────────────────────────
            # TRIPLE BEEP
            # ─────────────────────────────────────────────────────
            print(f"[Voice] Recording... (max {max_duration}s, silence={silence_timeout}s, rms={rms_threshold})")
            t = np.linspace(0, BEEP_DURATION, int(SAMPLE_RATE * BEEP_DURATION), False)
            beep_tone = (np.sin(2 * np.pi * BEEP_FREQ * t) * 16000).astype(np.int16)
            gap = np.zeros(int(SAMPLE_RATE * BEEP_GAP), dtype=np.int16)
            triple_beep = np.concatenate([beep_tone, gap, beep_tone, gap, beep_tone])

            beep_stream = p.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True)
            beep_stream.write(triple_beep.tobytes())
            beep_stream.stop_stream()
            beep_stream.close()
            time.sleep(0.3)  # Buffer flush

            # ─────────────────────────────────────────────────────
            # RECORDING
            # ─────────────────────────────────────────────────────
            stream = p.open(format=pyaudio.paInt16,
                          channels=1,
                          rate=SAMPLE_RATE,
                          input=True,
                          frames_per_buffer=CHUNK_SIZE)

            all_frames = []
            has_speech = False
            silent_chunks = 0
            max_silent_chunks = int(silence_timeout * SAMPLE_RATE / CHUNK_SIZE)
            max_chunks = int(max_duration * SAMPLE_RATE / CHUNK_SIZE)
            min_chunks = int(min_speech_duration * SAMPLE_RATE / CHUNK_SIZE)

            for i in range(max_chunks):
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                all_frames.append(data)

                # Calculate RMS
                samples = struct.unpack(f'{CHUNK_SIZE}h', data)
                rms = (sum(s*s for s in samples) / CHUNK_SIZE) ** 0.5

                if i % 2 == 0:
                    print(f"[Voice] Chunk {i//2 + 1}: level={int(rms)}")

                if rms >= rms_threshold:
                    has_speech = True
                    silent_chunks = 0
                elif has_speech and i >= min_chunks:
                    silent_chunks += 1
                    if silent_chunks >= max_silent_chunks:
                        print("[Voice] Silence detected, stopping")
                        break

            stream.stop_stream()
            stream.close()

            if not has_speech:
                return {'success': False, 'error': 'No speech detected'}
            
            # ─────────────────────────────────────────────────────
            # NOISE FILTERING
            # ─────────────────────────────────────────────────────
            audio_data = b''.join(all_frames)
            samples_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if not skip_filter:
                print("[Voice] Applying noise filter...")
                samples_array = apply_noise_filter(samples_array, SAMPLE_RATE)
            
            # ─────────────────────────────────────────────────────
            # EMOTION DETECTION
            # ─────────────────────────────────────────────────────
            emotion_result = None
            if not skip_emotion:
                print("[Voice] Analyzing emotion...")
                features = extract_audio_features(samples_array, SAMPLE_RATE)
                emotion_result = detect_emotion(features)
                print(f"[Voice] Emotion: {emotion_result['primary']} ({emotion_result['confidence']:.0%})")
            
            # ─────────────────────────────────────────────────────
            # SAVE & TRANSCRIBE
            # ─────────────────────────────────────────────────────
            temp_path = os.path.join(tempfile.gettempdir(), 'voice_whisper.wav')
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(samples_array.tobytes())
            
            print("[Voice] Transcribing with Whisper...")
            segments, info = model.transcribe(temp_path, beam_size=5)
            text = " ".join([seg.text for seg in segments]).strip()
            
            os.unlink(temp_path)
            
            if not text:
                return {'success': False, 'error': 'Could not understand audio', 'emotion': emotion_result}
            
            print(f"[Voice] Transcribed: {text}")
            
            # ─────────────────────────────────────────────────────
            # STRIP END PHRASES
            # ─────────────────────────────────────────────────────
            text_lower = text.lower()
            for phrase in END_PHRASES:
                if text_lower.endswith(phrase):
                    text = text[:-(len(phrase))].strip().rstrip('.,!?')
                    break
            
            result = {'success': True, 'text': text}
            if emotion_result:
                result['emotion'] = emotion_result
            
            return result
                
        except Exception as e:
            print(f"[Voice] Error: {e}")
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
        finally:
            if p is not None:
                p.terminate()

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    port = 5123
    server = HTTPServer(('localhost', port), VoiceHandler)
    print()
    print("=" * 50)
    print(f"Voice Server running on http://localhost:{port}")
    print("=" * 50)
    print("Endpoints:")
    print("  GET  /status              - Health check")
    print("  POST /listen?timeout=30   - Record + transcribe + emotion")
    print("       &skip_emotion=true   - Skip emotion detection")
    print("       &skip_filter=true    - Skip noise filtering")
    print("       &silence_timeout=4.0 - Silence cutoff seconds")
    print("       &min_speech_duration=3.0 - Min speech before checking silence")
    print("       &rms_threshold=100   - Loudness floor (20-500)")
    print()
    print("Leave this window open. Claude will call /listen")
    print("Press Ctrl+C to stop.")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Voice] Server stopped.")
        server.shutdown()

if __name__ == "__main__":
    main()
