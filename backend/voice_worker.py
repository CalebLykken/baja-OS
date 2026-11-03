"""Text to speech for spoken directions, run by backend/voice.py under the
Piper install's own Python (deploy/audio/install-voice.sh), so the voice
stays loaded between lines (loading takes ~2 s on the Pi, speaking ~0.5 s).

Reads one JSON object per line on stdin, {"text": ..., "out": path},
writes the WAV and answers with one line: {"out": path} or {"error": ...}.
A line that fails leaves no WAV behind.

    python voice_worker.py MODEL.onnx
"""

import json
import os
import sys
import wave


def write_wav(voice, text, out):
    """Write `text` to the WAV `out`. None if that worked, else the error to
    report. Piper's own error is the one reported: the WAV is closed after
    it, and closing a WAV that never got its format (Piper raised before any
    audio, or the text had none) raises a wave.Error that would hide it."""
    w = wave.open(out, "wb")
    error = None
    try:
        voice.synthesize_wav(text, w)
    except Exception as e:              # keep serving; report what went wrong
        error = f"{type(e).__name__}: {e}"
    frames = w.getnframes()
    try:
        w.close()
    except Exception as e:
        if error is None and frames:
            error = f"{type(e).__name__}: {e}"
    if error is not None:
        return error
    if frames == 0:
        return "no audio for that text"
    return None


def discard(out):
    """Remove a WAV that was not written in full. Nothing to do if it is not there."""
    try:
        os.remove(out)
    except (OSError, TypeError, ValueError):
        pass


def main():
    from piper import PiperVoice

    voice = PiperVoice.load(sys.argv[1])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        out = None
        try:
            job = json.loads(line)
            out = job["out"]
            error = write_wav(voice, job["text"], out)
        except Exception as e:          # keep serving; report what went wrong
            error = str(e)
        if error is None:
            print(json.dumps({"out": out}), flush=True)
        else:
            if out is not None:
                discard(out)
            print(json.dumps({"error": error}), flush=True)


if __name__ == "__main__":
    main()
