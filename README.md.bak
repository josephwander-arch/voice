# Voice Server

Voice input/output for Claude Desktop — real-time speech-to-text via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with biquad noise filtering and rule-based emotion detection, paired with text-to-speech via [edge-tts](https://github.com/rany2/edge-tts). Runs as a local HTTP server on `localhost:5123` and exposes MCP tools for Claude Desktop integration.

## Install — just ask your AI

If you already have [`local`](https://github.com/josephwander-arch/local) installed in Claude Desktop, or you're sitting in Claude Code / Codex CLI / Gemini CLI, paste this prompt:

> `https://github.com/josephwander-arch/voice` — Can you install this MCP for us to use here and the voice listening server, and make me a new `.bat` to call it and direct me to do what I need to do to get both sides running, then we can have a talk.

Your AI will:

1. Download the matching pre-built `voice-mcp.exe` for your architecture (ARM64 or x64) from [releases/latest](https://github.com/josephwander-arch/voice/releases/latest).
2. Drop it somewhere sensible (usually `C:\CPC\servers\`).
3. Edit your `claude_desktop_config.json` to register it as an MCP server (your existing servers are preserved; a timestamped backup is made first).
4. Clone this repo and install the Python listener requirements (`pip install -r requirements.txt`).
5. Write you a `START_VOICE_SERVER.bat` that launches `python voice_server.py` on boot.
6. Tell you to quit and reopen Claude Desktop, start the listener, and you're talking.

If your AI doesn't have filesystem/shell access, fall back to the manual install below.

## Features

- **Speech-to-text** via faster-whisper (base model, int8 quantized)
- **Biquad noise filtering** — 80 Hz highpass + 7.5 kHz lowpass removes hum and hiss
- **Emotion detection** — rule-based classifier from audio features (energy, pitch variance, ZCR, spectral centroid)
- **Triple beep** indicator when recording starts
- **Real-time level monitoring** — RMS printed per chunk
- **Configurable** — silence timeout, RMS threshold, min speech duration via query params or TOML config
- **End-phrase stripping** — automatically removes "send this", "done", "stop", etc.
- **Response emotion analysis** — text-based hedge/excitement/engagement scoring

## Requirements

- Python 3.11+
- PortAudio (system library, required by PyAudio)
- ffmpeg (for MP3→WAV conversion in TTS playback)
- A working microphone

## Manual installation

```bash
pip install -r requirements.txt
```

### PortAudio

- **Windows:** `pip install pyaudio` usually works. If not, download from [PyAudio wheels](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio).
- **macOS:** `brew install portaudio && pip install pyaudio`
- **Linux:** `sudo apt install portaudio19-dev && pip install pyaudio`

### ffmpeg

- **Windows:** `winget install Gyan.FFmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html). Ensure `ffmpeg` is on your PATH, or set the `VOICE_FFMPEG_PATH` environment variable.
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

## Quick Start

```bash
# Start the voice server
python voice_server.py

# Server runs on http://localhost:5123
# Endpoints:
#   GET  /status              - Health check
#   POST /listen?timeout=30   - Record + transcribe + emotion
#        &skip_emotion=true   - Skip emotion detection
#        &skip_filter=true    - Skip noise filtering
#        &silence_timeout=4.0 - Silence cutoff seconds
#        &min_speech_duration=3.0 - Min speech before checking silence
#        &rms_threshold=100   - Loudness floor (20-500)
```

On Windows, you can also double-click `START_VOICE_SERVER.bat`.

## Configuration

Create `voice.config.toml` in the repo directory (or set `VOICE_CONFIG_PATH` env var) to override defaults:

```toml
[listen]
silence_timeout_secs = 4.0
min_speech_duration_secs = 3.0
rms_threshold = 100
noise_filter_enabled = true
pre_record_enabled = true
```

Config lookup order:
1. `VOICE_CONFIG_PATH` environment variable
2. `./voice.config.toml` (current directory)
3. `~/.config/voice/voice.config.toml`

## MCP Integration

`server.py` provides MCP tool wrappers (`speak`, `listen_for_speech`, `start_voice_mode`) for Claude Desktop integration via the [FastMCP](https://github.com/jlowin/fastmcp) framework.

For production Claude Desktop use, companion **Rust MCP binaries** (`voice-mcp.exe`) are available as release assets (ARM64 + x64). These wrap the same voice server with Rust-native MCP transport and checkpoint recovery. Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "voice": {
      "command": "path/to/voice-mcp.exe"
    }
  }
}
```

The Python `server.py` serves as a pure-Python MCP fallback if you prefer not to use the Rust binary.

## Architecture

- `voice_server.py` — Standalone HTTP server (faster-whisper STT + noise filter + emotion detection)
- `server.py` — MCP tool wrapper that delegates to voice_server.py for STT and uses edge-tts for TTS
- `response_analyzer.py` — Text-based response emotion analysis (separate from audio emotion)
- `emotion_config.json` — Thresholds and word lists for response analyzer
- `play_audio.ps1` — PowerShell audio playback helper (Windows)
- `START_VOICE_SERVER.bat` — Windows launcher script

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `VOICE_CONFIG_PATH` | Path to `voice.config.toml` | Auto-discovered |
| `VOICE_FFMPEG_PATH` | Path to ffmpeg binary | Auto-discovered via PATH |
| `VOICE_EMOTION_LOG_DIR` | Directory for emotion analysis logs | `~/.voice/logs/` |

## License

Apache 2.0 — see [LICENSE](LICENSE)
