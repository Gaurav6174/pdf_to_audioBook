# PDF to Audiobook Generator

Convert any PDF book into a natural-sounding, high-fidelity audiobook using:
- **Zyphra ZONOS2** (MoE TTS, 4-bit Quantization `zonos2-q4_k.gguf`, 44.1 kHz studio audio)
- **Suno Bark** (Transformer neural audio synthesis, 24 kHz)

Both engines are fully integrated with automatic GPU/VRAM acceleration, progress tracking, live SSE logging, and a modern web interface.

---

## Supported TTS Engines

| Feature | Zyphra ZONOS2 (Quant 4) ★ | Suno Bark |
|---------|---------------------------|-----------|
| **Architecture** | Mixture of Experts (MoE) + DAC Vocoder | Transformer Semantic + Coarse/Fine Acoustic |
| **Quantization** | Q4_K GGUF (~4.9 GB) | FP16 / Small Models |
| **Hardware Fit** | Tuned for ~4GB VRAM (e.g. RTX 2050) | ~4-6GB VRAM |
| **Audio Sample Rate** | **44,100 Hz** (Studio Quality) | 24,000 Hz |
| **Inference Engine** | High-performance native `zonos2-server` / `zonos2-cli` | PyTorch / Transformers / Bark |
| **Default Voice** | `AmericanMale` | `v2/en_speaker_6` |
| **Speed** | Real-time generation (~0.2–0.5s per chunk) | ~3–8s per chunk |

---

## How It Works

```
PDF File
  → Extract text page by page        (PyMuPDF)
  → Split into sentences              (NLTK)
  → Chunk text                        (text_processor)
  → Generate audio for each chunk     (Zyphra ZONOS2 Q4 or Suno Bark)
  → Auto-detect sample rate & merge   (audio_merger: 44.1kHz or 24kHz)
  → Final audiobook.wav
```

---

## Project Structure

```
pdf_to_audioBook/
├── main.py                  # CLI entry point (supports --engine and --voice)
├── app.py                   # Web UI entry point (Flask on port 5000)
├── config.py                # Central configuration (engine, paths, device)
├── requirements.txt         # Python dependencies
├── .env                     # Local environment settings (CUDA/CPU)
│
├── input/                   # Drop your PDF books here
├── output/
│   ├── chunks/              # Generated chunk .wav files
│   ├── final/               # Final merged audiobook.wav
│   └── progress.json        # Auto-saved progress tracker
├── tools/
│   └── zonos2/              # Standalone GGML/GGUF ZONOS2 engine
│       ├── zonos2-server    # High-performance local HTTP server
│       ├── zonos2-cli       # Offline synthesis CLI
│       ├── models/          # zonos2-q4_k.gguf, dac.gguf, spk-encoder.gguf
│       └── default_voices/  # AmericanMale, AmericanFemale, BritishFemale
├── templates/
│   └── index.html           # Web UI template
├── static/
│   ├── style.css            # Dark cyberpunk stylesheet
│   └── script.js            # UI logic (SSE stream, engine switcher, GPU stats)
└── src/
    ├── pdf_extractor.py     # PDF text extraction
    ├── text_processor.py    # Chunk splitting
    ├── progress_tracker.py  # JSON progress saving/resuming
    ├── tts_engine.py        # Unified engine (Zonos2 Q4 + Bark)
    └── audio_merger.py      # Sample-rate-aware audio concatenation
```

---

## Setup & Installation

### Step 1 — Activate Python environment (Python 3.10)
```bash
conda activate pdf-bark-reader
# or: source /home/maximus/yes/envs/venv/bin/activate
```

### Step 2 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 3 — Download ZONOS2 Q4 weights (if not already downloaded)
The required GGUF model files for 4GB VRAM hardware from [HuggingFace Zyphra/ZONOS2-GGUF](https://huggingface.co/Zyphra/ZONOS2-GGUF/tree/main):
- `zonos2-q4_k.gguf` (~4.9 GB) — Q4_K experts with F16 spine
- `dac.gguf` (~254 MB) — Descript Audio Codec 44.1 kHz decoder
- `spk-encoder.gguf` (~24 MB) — ECAPA speaker encoder

They are located in `tools/zonos2/models/`. You can also trigger the built-in downloader:
```bash
cd tools/zonos2
./start-zonos2.sh --quant q4_k -y --no-browser
```

---

## Usage

### 1. Web UI (Recommended)
```bash
python app.py
```
Open **`http://localhost:5000`** in your browser.
- Select your engine (**Zyphra ZONOS2** or **Suno Bark**).
- Choose your desired voice preset.
- Upload any PDF file and click **GENERATE AUDIOBOOK**.
- Track real-time progress, live logs, and GPU temperature/VRAM load.
- Download the final `audiobook.wav` when complete!

### 2. Command Line Interface (CLI)
```bash
# Run with ZONOS2 (default, Quant 4, American Male)
python main.py --pdf input/book.pdf

# Run with ZONOS2 and a specific voice
python main.py --pdf input/book.pdf --engine zonos2 --voice BritishFemale

# Run with Suno Bark
python main.py --pdf input/book.pdf --engine bark --voice v2/en_speaker_6

# Reset saved progress and start from chunk 0
python main.py --pdf input/book.pdf --reset

# Re-merge existing chunks without re-synthesizing
python main.py --merge-only
```

---

## Available Voices

### Zyphra ZONOS2 Presets
- `AmericanMale` — American Male (Default) ★
- `AmericanFemale` — American Female
- `BritishFemale` — British Female

### Suno Bark Presets
- `v2/en_speaker_6` — Male, Natural (Bark Default) ★
- `v2/en_speaker_0` through `v2/en_speaker_4` — Male (Deep, Clear, Expressive, Soft)
- `v2/en_speaker_5`, `v2/en_speaker_7` through `v2/en_speaker_9` — Female (Neutral, Clear, Expressive, Soft)

---

## Hardware Optimization (RTX 2050 / 4GB VRAM)

The **Q4_K** quantization (`zonos2-q4_k.gguf`) retains the F16 spine (attention + router + speaker projection) while quantizing the MoE expert weights to 4-bit. This fits inside ~4GB VRAM with near-lossless audio fidelity (eval noise difference vs F16 ref), running at real-time speeds on NVIDIA GPUs.

---

## Credits
- [Zyphra ZONOS2](https://github.com/Zyphra/zonos2.cpp) & [ZONOS2-GGUF](https://huggingface.co/Zyphra/ZONOS2-GGUF) — Zonos2 MoE TTS
- [Suno Bark](https://github.com/suno-ai/bark) — Bark Neural TTS
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF extraction
- [NLTK](https://www.nltk.org/) — Text tokenization
