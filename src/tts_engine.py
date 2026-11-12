import os
import sys
import time
import logging
import atexit
import subprocess
import requests
import numpy as np
import scipy.io.wavfile as wav
from pathlib import Path

from config import (
    CHUNKS_DIR,
    DEVICE,
    TTS_ENGINE,
    BARK_VOICE_PRESET,
    BARK_SAMPLE_RATE,
    USE_SMALL_MODELS,
    CPU_OFFLOAD,
    ZONOS_DIR,
    ZONOS_MODELS_DIR,
    ZONOS_QUANT,
    ZONOS_MODEL_FILE,
    ZONOS_DAC_FILE,
    ZONOS_SPEAKER_FILE,
    ZONOS_SERVER_BIN,
    ZONOS_CLI_BIN,
    ZONOS_DEFAULT_VOICES_DIR,
    ZONOS_EMOTION_DIR,
    ZONOS_HOST,
    ZONOS_PORT,
    ZONOS_VOICE_PRESET,
    ZONOS_SAMPLE_RATE,
    ZONOS_BACKEND
)

logger = logging.getLogger(__name__)

# ── Patch torch.load for Bark if torch is loaded ──
try:
    import torch
    _original_torch_load = torch.load

    def _patched_torch_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return _original_torch_load(*args, **kwargs)

    torch.load = _patched_torch_load
except ImportError:
    pass

# Global state
_bark_models_loaded = False
_zonos_server_process = None
_zonos_speakers_cache = {}  # maps label/id -> speaker_embedding_id
_current_engine = TTS_ENGINE
_active_voice = None

def get_current_engine() -> str:
    global _current_engine
    return _current_engine

def set_current_engine(engine: str):
    global _current_engine
    _current_engine = (engine or TTS_ENGINE).lower()

def ensure_chunks_dir():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Chunks directory ready: {CHUNKS_DIR}")

def get_chunk_path(chunk_index: int) -> Path:
    filename = f"chunk_{chunk_index:04d}.wav"
    return CHUNKS_DIR / filename

# ─────────────────────────────────────────────────────────────
# Bark TTS Implementation
# ─────────────────────────────────────────────────────────────

def _load_bark_models():
    global _bark_models_loaded
    if _bark_models_loaded:
        logger.info("Bark models already loaded. Skipping.")
        return

    os.environ["SUNO_USE_SMALL_MODELS"] = "1" if USE_SMALL_MODELS else "0"
    os.environ["SUNO_OFFLOAD_CPU"] = "1" if CPU_OFFLOAD else "0"

    logger.info(f"Loading Bark models on device: {DEVICE}")
    logger.info(f"Using small models: {USE_SMALL_MODELS}")
    logger.info("This may take 10-30 seconds on first run...")

    from bark import preload_models
    preload_models()

    _bark_models_loaded = True
    logger.info("Bark models loaded successfully.")

def _generate_bark_audio_chunk(text: str, chunk_index: int, voice: str | None = None) -> Path:
    from bark import generate_audio

    voice_preset = voice or BARK_VOICE_PRESET
    output_path = get_chunk_path(chunk_index)
    logger.debug(f"[Bark] Generating chunk {chunk_index} with voice '{voice_preset}': '{text[:50]}...'")

    audio_array = generate_audio(text, history_prompt=voice_preset)
    audio_int16 = (audio_array * 32767).astype(np.int16)
    wav.write(str(output_path), BARK_SAMPLE_RATE, audio_int16)

    logger.debug(f"[Bark] Chunk {chunk_index} saved to {output_path}")
    return output_path

# ─────────────────────────────────────────────────────────────
# Zyphra ZONOS2 Implementation (GGUF Quantization 4)
# ─────────────────────────────────────────────────────────────

def is_zonos_server_healthy(host: str = ZONOS_HOST, port: int = ZONOS_PORT, timeout: float = 2.0) -> bool:
    try:
        url = f"http://{host}:{port}/health"
        res = requests.get(url, timeout=timeout)
        return res.status_code == 200
    except Exception:
        return False

def _fetch_zonos_speakers(host: str = ZONOS_HOST, port: int = ZONOS_PORT) -> dict[str, str]:
    global _zonos_speakers_cache
    try:
        url = f"http://{host}:{port}/tts/speakers"
        res = requests.get(url, timeout=3.0)
        if res.status_code == 200:
            data = res.json()
            speakers = data.get("speakers", [])
            mapping = {}
            for spk in speakers:
                spk_id = spk.get("id")
                label = spk.get("label", "")
                if spk_id:
                    mapping[spk_id] = spk_id
                    if label:
                        mapping[label] = spk_id
                        mapping[label.lower()] = spk_id
                        # handle file extensions e.g. AmericanMale.mp3
                        mapping[Path(label).stem] = spk_id
                        mapping[Path(label).stem.lower()] = spk_id
            _zonos_speakers_cache = mapping
            logger.info(f"Loaded {len(speakers)} ZONOS2 speakers: {list(mapping.keys())}")
            return mapping
    except Exception as e:
        logger.warning(f"Could not fetch ZONOS2 speakers from server: {e}")
    return _zonos_speakers_cache

def _ensure_vulkan_icd():
    """Configures Vulkan ICD for NVIDIA GPUs in containers (Kaggle/Colab)."""
    if not Path("/proc/driver/nvidia/version").exists() and not Path("/dev/nvidia0").exists():
        return

    icd_targets = [
        Path("/usr/share/vulkan/icd.d/nvidia_icd.json"),
        Path("/etc/vulkan/icd.d/nvidia_icd.json")
    ]
    if not any(p.exists() for p in icd_targets):
        try:
            target = Path("/etc/vulkan/icd.d/nvidia_icd.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            content = '{\n    "file_format_version" : "1.0.1",\n    "ICD": {\n        "library_path": "libGLX_nvidia.so.0",\n        "api_version" : "1.3.0"\n    }\n}\n'
            target.write_text(content)
            os.environ["VK_ICD_FILENAMES"] = str(target)
            logger.info(f"Auto-configured NVIDIA Vulkan ICD at {target}")
        except Exception as e:
            logger.warning(f"Could not auto-configure Vulkan ICD: {e}")

def _spawn_server(backend: str, max_wait_seconds: int = 90) -> bool:
    global _zonos_server_process

    if backend == "gpu":
        _ensure_vulkan_icd()

    logger.info(f"Starting ZONOS2 server on http://{ZONOS_HOST}:{ZONOS_PORT} (Backend: {backend.upper()})...")
    logger.info(f"Model: {ZONOS_MODEL_FILE.name} (Quant: {ZONOS_QUANT.upper()})")

    cmd = [
        str(ZONOS_SERVER_BIN),
        str(ZONOS_MODEL_FILE),
        "--host", ZONOS_HOST,
        "--port", str(ZONOS_PORT),
    ]

    if ZONOS_DAC_FILE.exists():
        cmd.extend(["--dac", str(ZONOS_DAC_FILE)])

    if ZONOS_SPEAKER_FILE.exists():
        cmd.extend(["--spk", str(ZONOS_SPEAKER_FILE)])

    if ZONOS_DEFAULT_VOICES_DIR.exists():
        cmd.extend(["--tts-default-voices-dir", str(ZONOS_DEFAULT_VOICES_DIR)])

    if ZONOS_EMOTION_DIR.exists():
        cmd.extend(["--tts-emotion-directions-dir", str(ZONOS_EMOTION_DIR)])

    if backend == "gpu":
        cmd.append("--gpu")
    else:
        cmd.append("--cpu")

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    server_log = open(log_dir / "zonos_server.log", "a", encoding="utf-8")

    try:
        _zonos_server_process = subprocess.Popen(
            cmd,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            cwd=str(ZONOS_DIR)
        )
    except Exception as e:
        logger.error(f"Failed to spawn ZONOS2 server process: {e}")
        return False

    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        if _zonos_server_process.poll() is not None:
            server_log.flush()
            return False

        if is_zonos_server_healthy():
            logger.info(f"ZONOS2 server is up and responsive on {backend.upper()} backend.")
            try:
                server_log.flush()
                log_text = Path("logs/zonos_server.log").read_text(errors="ignore")
                last_backend = [l for l in log_text.splitlines() if "zonos2: backend =" in l]
                if last_backend:
                    logger.info(f"Active runtime device: {last_backend[-1]}")
            except Exception:
                pass
            _fetch_zonos_speakers()
            return True

        time.sleep(1.0)

    return False

def ensure_zonos_server_ready(max_wait_seconds: int = 90) -> bool:
    if is_zonos_server_healthy():
        logger.info("ZONOS2 server is already running and healthy.")
        _fetch_zonos_speakers()
        return True

    global ZONOS_MODEL_FILE, ZONOS_QUANT
    if not ZONOS_MODEL_FILE.exists():
        import config
        resolved_quant, resolved_path = config._resolve_zonos_model()
        if resolved_path.exists():
            ZONOS_QUANT = resolved_quant
            ZONOS_MODEL_FILE = resolved_path
            logger.info(f"Auto-detected model file on disk: {ZONOS_MODEL_FILE.name}")
        else:
            raise FileNotFoundError(
                f"ZONOS2 model file not found at: {ZONOS_MODEL_FILE}\n"
                f"Ensure GGUF weights have completed downloading via 'python setup_zonos.py --quant {ZONOS_QUANT}'."
            )

    if not ZONOS_SERVER_BIN.exists() or not os.access(str(ZONOS_SERVER_BIN), os.X_OK):
        if ZONOS_SERVER_BIN.exists():
            os.chmod(str(ZONOS_SERVER_BIN), 0o755)
        else:
            raise FileNotFoundError(f"ZONOS2 server binary not found at: {ZONOS_SERVER_BIN}")

    preferred_backend = ZONOS_BACKEND.lower()
    success = _spawn_server(backend=preferred_backend, max_wait_seconds=max_wait_seconds)

    if not success and preferred_backend == "gpu":
        logger.warning(
            "ZONOS2 server failed to start with GPU backend (VRAM limit reached: "
            "model requires 4.58 GB, while GPU has 4.0 GB VRAM). "
            "Falling back automatically to CPU backend..."
        )
        success = _spawn_server(backend="cpu", max_wait_seconds=max_wait_seconds)

    if not success:
        raise RuntimeError(
            "ZONOS2 server failed to start. Check logs/zonos_server.log for details."
        )

    return True

def stop_zonos_server():
    global _zonos_server_process
    if _zonos_server_process and _zonos_server_process.poll() is None:
        logger.info("Stopping ZONOS2 server process...")
        try:
            _zonos_server_process.terminate()
            _zonos_server_process.wait(timeout=5)
        except Exception:
            _zonos_server_process.kill()
        _zonos_server_process = None

atexit.register(stop_zonos_server)

def _generate_zonos_audio_chunk(text: str, chunk_index: int, voice: str | None = None) -> Path:
    output_path = get_chunk_path(chunk_index)
    voice_name = voice or ZONOS_VOICE_PRESET or "AmericanMale"
    clean_voice_key = Path(voice_name).stem

    # Attempt 1: HTTP API to running zonos2-server
    try:
        if ensure_zonos_server_ready():
            # Find matching speaker ID
            speaker_id = (
                _zonos_speakers_cache.get(voice_name)
                or _zonos_speakers_cache.get(clean_voice_key)
                or _zonos_speakers_cache.get(clean_voice_key.lower())
            )

            # If not found, refresh speakers once
            if not speaker_id:
                _fetch_zonos_speakers()
                speaker_id = (
                    _zonos_speakers_cache.get(voice_name)
                    or _zonos_speakers_cache.get(clean_voice_key)
                    or _zonos_speakers_cache.get(clean_voice_key.lower())
                )

            # Try /v1/audio/speech first (OpenAI compatibility endpoint)
            v1_url = f"http://{ZONOS_HOST}:{ZONOS_PORT}/v1/audio/speech"
            v1_payload = {
                "model": "zonos2",
                "input": text,
                "voice": clean_voice_key,
                "response_format": "wav"
            }
            res = requests.post(v1_url, json=v1_payload, timeout=60)
            if res.status_code == 200 and len(res.content) > 100:
                with open(output_path, "wb") as f:
                    f.write(res.content)
                logger.debug(f"[Zonos2] Chunk {chunk_index} generated via /v1/audio/speech: {output_path}")
                return output_path

            # Fallback to /tts/generate
            gen_url = f"http://{ZONOS_HOST}:{ZONOS_PORT}/tts/generate"
            body = {
                "text": text,
                "format": "wav",
                "stream": False,
                "seed": 42
            }
            if speaker_id:
                body["speaker_embedding_id"] = speaker_id

            res2 = requests.post(gen_url, json=body, timeout=60)
            if res2.status_code == 200 and len(res2.content) > 100:
                with open(output_path, "wb") as f:
                    f.write(res2.content)
                logger.debug(f"[Zonos2] Chunk {chunk_index} generated via /tts/generate: {output_path}")
                return output_path

            logger.warning(f"Zonos2 server returned non-200 or empty response ({res2.status_code}). Falling back to CLI.")
    except Exception as e:
        logger.warning(f"Zonos2 server synthesis failed: {e}. Falling back to CLI.")

    # Attempt 2: Direct CLI synthesis using zonos2-cli
    logger.info(f"[Zonos2 CLI] Generating chunk {chunk_index} directly via CLI...")
    cmd = [
        str(ZONOS_CLI_BIN),
        str(ZONOS_MODEL_FILE),
        "--tts", text,
        str(output_path),
        "--dac", str(ZONOS_DAC_FILE),
        "--seed", "42"
    ]

    # Look for voice audio in default_voices
    candidate_voice_files = [
        ZONOS_DEFAULT_VOICES_DIR / f"{clean_voice_key}.mp3",
        ZONOS_DEFAULT_VOICES_DIR / f"{clean_voice_key}.wav",
        ZONOS_DEFAULT_VOICES_DIR / voice_name
    ]
    voice_file = next((vf for vf in candidate_voice_files if vf.exists()), None)
    if voice_file and ZONOS_SPEAKER_FILE.exists():
        cmd.extend(["--clone", str(voice_file), "--spk-encoder", str(ZONOS_SPEAKER_FILE)])

    cmd_run = list(cmd) + (["--gpu"] if ZONOS_BACKEND == "gpu" else ["--cpu"])
    result = subprocess.run(cmd_run, capture_output=True, text=True, cwd=str(ZONOS_DIR))
    if result.returncode != 0 and ZONOS_BACKEND == "gpu":
        logger.warning(f"ZONOS2 GPU CLI failed ({result.stderr}). Retrying on CPU...")
        cmd_run = list(cmd) + ["--cpu"]
        result = subprocess.run(cmd_run, capture_output=True, text=True, cwd=str(ZONOS_DIR))

    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        error_msg = result.stderr or result.stdout or "Unknown CLI failure"
        raise RuntimeError(f"ZONOS2 CLI synthesis failed: {error_msg}")

    logger.debug(f"[Zonos2 CLI] Chunk {chunk_index} saved to {output_path}")
    return output_path

# ─────────────────────────────────────────────────────────────
# Public Unified TTS API
# ─────────────────────────────────────────────────────────────

def load_models(engine: str | None = None):
    chosen_engine = (engine or _current_engine or TTS_ENGINE).lower()
    set_current_engine(chosen_engine)

    if chosen_engine == "bark":
        _load_bark_models()
    elif chosen_engine in ("zonos", "zonos2"):
        ensure_zonos_server_ready()
    else:
        raise ValueError(f"Unknown TTS engine: '{chosen_engine}'. Choose 'zonos2' or 'bark'.")

def generate_audio_chunk(text: str, chunk_index: int, engine: str | None = None, voice: str | None = None) -> Path:
    chosen_engine = (engine or _current_engine or TTS_ENGINE).lower()
    ensure_chunks_dir()

    if chosen_engine == "bark":
        return _generate_bark_audio_chunk(text, chunk_index, voice=voice)
    elif chosen_engine in ("zonos", "zonos2"):
        return _generate_zonos_audio_chunk(text, chunk_index, voice=voice)
    else:
        raise ValueError(f"Unknown TTS engine: '{chosen_engine}'. Choose 'zonos2' or 'bark'.")

# Compatibility wrapper for existing Bark monkey-patching in older code
def generate_audio(text: str, history_prompt: str | None = None):
    from bark import generate_audio as bark_generate
    return bark_generate(text, history_prompt=history_prompt or BARK_VOICE_PRESET)

def process_chunks(chunks: list[str], tracker, engine: str | None = None, voice: str | None = None) -> list[Path]:
    ensure_chunks_dir()
    chosen_engine = (engine or _current_engine or TTS_ENGINE).lower()
    set_current_engine(chosen_engine)
    
    generated_files = []
    total = len(chunks)
    
    logger.info(f"Starting TTS generation with engine '{chosen_engine}' for {total} chunks...")
    
    for index, text in enumerate(chunks):
        if tracker.is_complete(index):
            logger.debug(f"Chunk {index} already done. Skipping.")
            generated_files.append(get_chunk_path(index))
            continue   
        
        if index % 10 == 0:
            summary = tracker.get_summary()
            logger.info(
                f"Progress: {summary['completed']}/{total} chunks done "
                f"({summary['percent']}%)"
            )
            
        try:
            output_path = generate_audio_chunk(text, index, engine=chosen_engine, voice=voice)
            tracker.mark_complete(index)
            generated_files.append(output_path)
        except Exception as e:
            logger.error(f"Chunk {index} failed: {e}")
            tracker.mark_failed(index)
            
    summary = tracker.get_summary()
    logger.info(
        f"TTS generation complete ({chosen_engine}). "
        f"Success: {summary['completed']} | "
        f"Failed: {summary['failed']} | "
        f"Total: {total}"
    )
    
    return generated_files
