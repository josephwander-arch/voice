#!/usr/bin/env python3
"""Voice MCP Server - Full conversation mode with Edge TTS."""

from mcp.server.fastmcp import FastMCP
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

mcp = FastMCP("Voice")


def _play_audio_file(path: str) -> None:
    """Play an audio file using the first available local backend."""
    extension = os.path.splitext(path)[1].lower()

    if extension == ".wav":
        try:
            import simpleaudio as sa

            wave_obj = sa.WaveObject.from_wave_file(path)
            play_obj = wave_obj.play()
            play_obj.wait_done()
            return
        except Exception:
            pass

    players = [
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", path],
        ["mpv", "--no-video", "--really-quiet", path],
    ]
    if extension == ".wav":
        players.extend(
            [
                ["paplay", path],
                ["aplay", path],
                ["pw-play", path],
            ]
        )

    for command in players:
        executable = shutil.which(command[0])
        if executable is None:
            continue
        subprocess.run([executable, *command[1:]], check=True)
        return

    raise RuntimeError(
        "No audio playback backend available. Install ffplay, mpv, simpleaudio, "
        "paplay, aplay, or pw-play."
    )

@mcp.tool()
def speak(text: str, voice: str = "en-GB-RyanNeural", rate: str = "-15%") -> str:
    """
    Speak text aloud using Edge TTS and a local audio player.
    
    Args:
        text: What to say
        voice: Voice name (default en-GB-RyanNeural)
        rate: Speaking rate, e.g. "-20%", "+10%", "-15%" (default -15%)
    """
    temp_dir = tempfile.mkdtemp(prefix="voice-tts-")
    temp_path = os.path.join(temp_dir, "claude_voice.mp3")
    wav_path = os.path.join(temp_dir, "claude_voice.wav")

    try:
        import edge_tts

        # Generate speech with edge-tts
        async def generate():
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(temp_path)

        asyncio.run(generate())

        # Prefer direct playback of the generated MP3 to avoid fragile conversion paths.
        _play_audio_file(temp_path)

        return "spoke"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@mcp.tool()
def listen_for_speech(timeout: int = 30) -> str:
    """
    Listen for voice input via standalone server.
    
    Requires voice_server.py running separately.
    Returns transcribed speech or error.
    
    Args:
        timeout: Max seconds to wait
    """
    try:
        url = f"http://localhost:5123/listen?timeout={timeout}"
        req = urllib.request.Request(url, method='POST')
        
        with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
            result = json.loads(resp.read().decode())
            if result.get('success'):
                return result.get('text', '')
            else:
                return f"[ERROR: {result.get('error', 'Unknown')}]"
    except urllib.error.URLError:
        return "[ERROR: Voice server not running. Start: python voice_server.py]"
    except Exception as e:
        return f"[ERROR: {str(e)}]"

@mcp.tool()
def start_voice_mode() -> str:
    """
    Check if voice server is ready for conversation mode.
    
    Returns status. If ready, Claude should:
    1. Call listen_for_speech() to hear user
    2. Generate response
    3. Call speak() to say it
    4. Repeat until user says "stop" or "exit"
    """
    try:
        url = "http://localhost:5123/status"
        with urllib.request.urlopen(url, timeout=2) as resp:
            result = json.loads(resp.read().decode())
            if result.get('success'):
                return "READY - Voice server running. Entering conversation mode."
            return "ERROR - Server responded but not ready"
    except Exception:
        return "ERROR - Voice server not running. Start it first: python voice_server.py"

if __name__ == "__main__":
    mcp.run()
