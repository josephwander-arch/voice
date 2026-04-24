# Validation Plan

This branch exists to preserve the Linux-port testing context and close the
gaps we intentionally skipped while getting the first Arch Linux x86_64 PR
merged quickly.

## Validated Already

- Dependency install in a local `.venv` on Arch Linux x86_64
- `voice_server.py` startup, Whisper model load, and `/status` health check
- `server.py` MCP registration for Claude Code and Codex
- One-shot TTS playback through `server.speak(...)`
- One-shot STT capture through `POST /listen`
- Git fork / branch / PR flow

## Regressions Already Fixed

- `nest_asyncio` broke FastMCP startup on Python 3.14
- The previous `pydub` / `pyaudioop` playback path failed on Python 3.14
- `/listen` defaulted to `skip_emotion=true`, which contradicted the docs

## Follow-Up Gaps

These are the checks we did not fully cover during the first pass:

1. Full end-to-end conversation loop inside a real MCP client UI
2. Multiple consecutive voice turns instead of a single smoke test
3. Microphone and playback device behavior on Linux desktops
4. Echo / bleed from local playback back into microphone capture
5. Background listener lifecycle across reboot or login sessions
6. Automated regression coverage for the Linux and Python 3.14 fixes
7. Cross-platform regression checks for the original Windows-first flow
8. Emotion classifier calibration and usefulness review

Emotion classifier status:

- Keep feature in place
- Add simple global on/off control for debugging
- Treat emotion work as low priority until core voice reliability is stronger

## Task-Oriented Game Plan

1. Add automated regression tests for the code-level failures we already found.
2. Tighten docs so they match the current Linux implementation exactly.
3. Re-run local smoke tests after each change to avoid reintroducing breakage.
4. Add repeatable manual validation steps for:
   - MCP client conversation loop
   - multi-turn recording
   - headphone vs speaker behavior
   - listener background startup
5. If manual validation still shows echo or device issues, add explicit device
   selection or playback isolation controls.
