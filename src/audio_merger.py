import logging
import numpy as np
import scipy.io.wavfile as wav
from pathlib import Path

from config import (
    CHUNKS_DIR,
    FINAL_DIR,
    FINAL_OUTPUT_FILENAME,
    PAUSE_BETWEEN_CHUNKS_MS,
    SAMPLE_RATE
)

logger = logging.getLogger(__name__)

def ensure_final_dir():
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Final output directory ready: {FINAL_DIR}")
    
def create_silence(duration_ms: int, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    num_samples = int((duration_ms / 1000) * sample_rate)
    return np.zeros(num_samples, dtype=np.int16)

def load_chunk(chunk_path: Path) -> tuple[np.ndarray | None, int]:
    if not chunk_path.exists():
        logger.warning(f"Chunk file not found, skipping: {chunk_path}")
        return None, SAMPLE_RATE
    try:
        sample_rate, audio_data = wav.read(str(chunk_path))
        
        # Convert float32 or non-int16 data to int16 cleanly
        if np.issubdtype(audio_data.dtype, np.floating):
            audio_data = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
        elif audio_data.dtype != np.int16:
            audio_data = audio_data.astype(np.int16)

        return audio_data, sample_rate
    except Exception as e:
        logger.error(f"Failed to load chunk {chunk_path.name}: {e}")
        return None, SAMPLE_RATE
    
def get_sorted_chunk_paths(chunk_files: list[Path]) -> list[Path]:
    return sorted(chunk_files, key=lambda p: p.name)

# core merge function

def merge_chunks(chunk_files: list[Path], target_sample_rate: int | None = None) -> Path:
    if not chunk_files:
        raise ValueError("No chunk files provided for merging.")
    
    ensure_final_dir()
    
    sorted_chunks = get_sorted_chunk_paths(chunk_files)
    logger.info(f"Merging {len(sorted_chunks)} chunks into final audiobook...")
    
    audio_segments = []
    effective_sample_rate = target_sample_rate
    
    loaded_chunks = []
    for chunk_path in sorted_chunks:
        audio_data, sr = load_chunk(chunk_path)
        if audio_data is not None:
            if effective_sample_rate is None:
                effective_sample_rate = sr
            loaded_chunks.append(audio_data)

    if not loaded_chunks:
        raise ValueError("No audio segments could be loaded. "
                         "All chunk files may be corrupted or missing.")

    effective_sample_rate = effective_sample_rate or SAMPLE_RATE
    silence = create_silence(PAUSE_BETWEEN_CHUNKS_MS, sample_rate=effective_sample_rate)

    for i, audio_data in enumerate(loaded_chunks):
        audio_segments.append(audio_data)
        if i < len(loaded_chunks) - 1:
            audio_segments.append(silence)
            
        if (i + 1) % 50 == 0:
            logger.info(f"Merged {i + 1}/{len(loaded_chunks)} chunks...")

    logger.info(f"Concatenating all audio segments at {effective_sample_rate}Hz...")
    final_audio = np.concatenate(audio_segments, axis=0)
    
    output_path = FINAL_DIR / FINAL_OUTPUT_FILENAME
    wav.write(str(output_path), effective_sample_rate, final_audio)
    
    duration_seconds = len(final_audio) / effective_sample_rate
    duration_minutes = duration_seconds / 60
    
    logger.info(
        f"Audiobook saved to: {output_path}\n"
        f"Sample Rate: {effective_sample_rate} Hz\n"
        f"Total duration: {duration_minutes:.1f} minutes "
        f"({duration_seconds:.0f} seconds)\n"
        f"File size: {output_path.stat().st_size / (1024*1024):.1f} MB"
    )

    return output_path

def merge_all_chunks_from_dir() -> Path:
    logger.info(f"Scanning for chunk files in: {CHUNKS_DIR}")
    chunk_files = list(CHUNKS_DIR.glob("*.wav"))

    if not chunk_files:
        raise FileNotFoundError(
            f"No .wav chunk files found in {CHUNKS_DIR}. "
            f"Make sure TTS engine has run first."
        )
    
    logger.info(f"Found {len(chunk_files)} chunk files.")
    return merge_chunks(chunk_files)
