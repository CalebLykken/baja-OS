#!/bin/sh
# Spoken directions: Piper (offline text-to-speech) with the "kristin"
# voice, which was trained on public-domain LibriVox recordings. No sudo;
# safe to re-run.
#
#   deploy/audio/install-voice.sh
#
# Goes in $BAJA_VOICE_DIR (default ~/.local/share/baja-os/voice):
#   venv/                        piper-tts 1.8.0 and onnxruntime 1.30.0
#   en_US-kristin-medium.onnx    the voice (63 MB, checksum verified)
set -eu

DIR="${BAJA_VOICE_DIR:-$HOME/.local/share/baja-os/voice}"
VOICE=en_US-kristin-medium
VOICE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/kristin/medium
VOICE_SHA256=5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

mkdir -p "$DIR"
if ! "$DIR/venv/bin/python" -c "import piper" 2>/dev/null; then
    echo "Installing Piper..."
    python3 -m venv "$DIR/venv"
    "$DIR/venv/bin/pip" install -q --only-binary=:all: "piper-tts==1.8.0" "onnxruntime==1.30.0"
fi

if [ ! -f "$DIR/$VOICE.onnx" ] || [ "$(sha256 "$DIR/$VOICE.onnx")" != "$VOICE_SHA256" ]; then
    echo "Downloading the voice..."
    curl -fsSL --retry 3 -o "$DIR/$VOICE.onnx.part" "$VOICE_URL/$VOICE.onnx"
    if [ "$(sha256 "$DIR/$VOICE.onnx.part")" != "$VOICE_SHA256" ]; then
        echo "Checksum mismatch for the voice" >&2
        exit 1
    fi
    mv "$DIR/$VOICE.onnx.part" "$DIR/$VOICE.onnx"
fi
curl -fsSL --retry 3 -o "$DIR/$VOICE.onnx.json" "$VOICE_URL/$VOICE.onnx.json"

# Say something, so a broken install shows up now rather than on the road.
"$DIR/venv/bin/python" - "$DIR/$VOICE.onnx" <<'EOF'
import sys, time, wave
from piper import PiperVoice
t = time.time()
voice = PiperVoice.load(sys.argv[1])
with wave.open("/tmp/baja-voice-test.wav", "wb") as w:
    voice.synthesize_wav("In a quarter mile, turn right onto Broad Street.", w)
print(f"Voice ready ({time.time() - t:.1f} s to load and speak a test line)")
EOF
