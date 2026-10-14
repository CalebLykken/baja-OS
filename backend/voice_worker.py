"""Text to speech for spoken directions, run by backend/voice.py under the
Piper install's own Python (deploy/audio/install-voice.sh), so the voice
stays loaded between lines (loading takes ~2 s on the Pi, speaking ~0.5 s).

Reads one JSON object per line on stdin, {"text": ..., "out": path},
writes the WAV and answers with one line: {"out": path} or {"error": ...}.

    python voice_worker.py MODEL.onnx
"""

import json
import sys
import wave

from piper import PiperVoice


def main():
    voice = PiperVoice.load(sys.argv[1])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            job = json.loads(line)
            with wave.open(job["out"], "wb") as w:
                voice.synthesize_wav(job["text"], w)
            print(json.dumps({"out": job["out"]}), flush=True)
        except Exception as e:          # keep serving; report what went wrong
            print(json.dumps({"error": str(e)}), flush=True)


if __name__ == "__main__":
    main()
