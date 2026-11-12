import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

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

# ── Zyphra ZONOS2 Settings (GGUF Quantization 4 for ~4GB VRAM hardware) ──
ZONOS_DIR = BASE_DIR / "tools" / "zonos2"
ZONOS_MODELS_DIR = ZONOS_DIR / "models"
ZONOS_QUANT = os.getenv("ZONOS_QUANT", "q4_k")  # Quant 4: optimal for RTX 2050 (4GB VRAM)
ZONOS_MODEL_FILE = ZONOS_MODELS_DIR / f"zonos2-{ZONOS_QUANT}.gguf"
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
ZONOS_BACKEND = os.getenv("ZONOS_BACKEND", "cpu")  # "cpu" for ~4GB VRAM hardware, "gpu" if >=6GB VRAM

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
