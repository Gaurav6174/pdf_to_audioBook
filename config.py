import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

INPUT_DIR   = BASE_DIR / "input"           # Where you put your PDF book
CHUNKS_DIR  = BASE_DIR / "output" / "chunks"  # One .wav file per sentence
FINAL_DIR   = BASE_DIR / "output" / "final"   
LOG_FILE    = BASE_DIR / "logs" / "run.log" 

DEFAULT_PDF = INPUT_DIR / "book.pdf"

# ── TTS Engine Selection ("zonos2" or "bark") ──
TTS_ENGINE = os.getenv("TTS_ENGINE", "zonos2").lower()

# ── Suno Bark Settings ──
BARK_VOICE_PRESET = os.getenv("BARK_VOICE_PRESET", "v2/en_speaker_6")
BARK_SAMPLE_RATE = 24000

# ── Zyphra ZONOS2 Settings (Dynamic Quantization & Auto-Detection) ──
ZONOS_DIR = BASE_DIR / "tools" / "zonos2"
ZONOS_MODELS_DIR = ZONOS_DIR / "models"

def _resolve_zonos_model():
    """Dynamically resolves the active ZONOS2 GGUF model file on disk or from env."""
    env_quant = os.getenv("ZONOS_QUANT")
    if env_quant:
        candidate = ZONOS_MODELS_DIR / f"zonos2-{env_quant}.gguf"
        if candidate.exists():
            return env_quant, candidate

    # Auto-detect existing zonos2-*.gguf files on disk
    if ZONOS_MODELS_DIR.exists():
        candidates = [
            p for p in ZONOS_MODELS_DIR.glob("zonos2-*.gguf")
            if not p.name.endswith(".part") and p.stat().st_size > 1024 * 1024
        ]
        if candidates:
            # Sort by size descending (f16 > q8_0 > q6_k > q5_k > q4_k)
            candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
            chosen = candidates[0]
            quant_name = chosen.stem.replace("zonos2-", "")
            return quant_name, chosen

    fallback_quant = env_quant or "q8_0"
    return fallback_quant, ZONOS_MODELS_DIR / f"zonos2-{fallback_quant}.gguf"

ZONOS_QUANT, ZONOS_MODEL_FILE = _resolve_zonos_model()
ZONOS_DAC_FILE = ZONOS_MODELS_DIR / "dac.gguf"
ZONOS_SPEAKER_FILE = ZONOS_MODELS_DIR / "spk-encoder.gguf"
ZONOS_SERVER_BIN = ZONOS_DIR / "zonos2-server"
ZONOS_CLI_BIN = ZONOS_DIR / "zonos2-cli"
ZONOS_DEFAULT_VOICES_DIR = ZONOS_DIR / "default_voices"
ZONOS_EMOTION_DIR = ZONOS_DIR / "emotion_directions"
ZONOS_HOST = os.getenv("ZONOS_HOST", "127.0.0.1")
ZONOS_PORT = int(os.getenv("ZONOS_PORT", 1919))
ZONOS_VOICE_PRESET = os.getenv("ZONOS_VOICE_PRESET", "AmericanMale")
ZONOS_SAMPLE_RATE = 44100

def _detect_zonos_backend():
    env_backend = os.getenv("ZONOS_BACKEND")
    if env_backend:
        return env_backend.lower()
    try:
        import torch
        if torch.cuda.is_available():
            return "gpu"
    except Exception:
        pass
    if Path("/proc/driver/nvidia/version").exists() or os.getenv("CUDA_VISIBLE_DEVICES"):
        return "gpu"
    return "cpu"

ZONOS_BACKEND = _detect_zonos_backend()

DEVICE = os.getenv("DEVICE", "cuda")  # "cuda" for GPU, "cpu" for CPU

USE_SMALL_MODELS = True
CPU_OFFLOAD = True

MAX_CHUNK_CHARS = 240
MIN_CHUNK_CHARS = 10

RESUME_ENABLED = True
PROGRESS_FILE = BASE_DIR / "output" / "progress.json"

# Default Sample Rate based on active engine
SAMPLE_RATE = ZONOS_SAMPLE_RATE if TTS_ENGINE == "zonos2" else BARK_SAMPLE_RATE

PAUSE_BETWEEN_CHUNKS_MS = 400
FINAL_OUTPUT_FILENAME = "audiobook.wav"

LOG_LEVEL = "INFO"
LOG_TO_CONSOLE = True
