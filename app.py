import os
import json
import time
import queue
import shutil
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
    send_file
)

from dotenv import load_dotenv

# load .env file
load_dotenv()

# pipeline module imports
from src.pdf_extractor import setup_logging, extract_text_from_pdf, get_pdf_metadata
from src.text_processor import process_pages
from src.progress_tracker import ProgressTracker
from src.tts_engine import load_models, process_chunks, generate_audio_chunk, stop_zonos_server
from src.audio_merger import merge_chunks, merge_all_chunks_from_dir

# import config variables
from config import (
    INPUT_DIR,
    CHUNKS_DIR,
    FINAL_DIR,
    FINAL_OUTPUT_FILENAME,
    TTS_ENGINE,
    BARK_VOICE_PRESET,
    ZONOS_VOICE_PRESET,
    ZONOS_QUANT,
    ZONOS_MODEL_FILE,
    ZONOS_BACKEND,
    RESUME_ENABLED,
    PROGRESS_FILE
)

# setup
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
setup_logging()

logger = logging.getLogger(__name__)

# global state
progress_queue = queue.Queue()
is_running = False
stop_event = threading.Event()

last_result = {
    "status": "idle",
    "output_path": None,
    "error": None
}

# sending progress updates to the frontend via SSE
def send_progress(message: str, percent: int = None, eta: str = None, status: str = None):
    update = {
        "message": message,
        "percent": percent,
        "eta": eta,
        "status": status,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    progress_queue.put(json.dumps(update))
    logger.info(f"[UI] {message}")
    
# eta calculation
def calculate_eta(completed: int, total: int, start_time: float) -> str:
    if completed < 3:
        return "Calculating..."
    
    elapsed = time.time() - start_time
    per_chunk = elapsed / completed
    remaining = (total - completed) * per_chunk
     
    if remaining < 60:
        return f"~{int(remaining)} seconds remaining"
    elif remaining < 3600:
        minutes = int(remaining / 60)
        return f"~{minutes} minutes remaining"
    else:
        hours   = int(remaining / 3600)
        minutes = int((remaining % 3600) / 60)
        return f"~{hours}h {minutes}m remaining"

# pipeline thread
def run_pipeline(pdf_path: Path, voice: str, reset: bool, engine: str = TTS_ENGINE):
    global is_running, last_result

    is_running = True
    stop_event.clear()
    last_result = {
        "status": "running",
        "output_path": None,
        "error": None
    }
    
    try:
        # extract
        send_progress("Extracting text from PDF...", percent=5)
        metadata = get_pdf_metadata(pdf_path)
        
        send_progress(
            f"Found: '{metadata['title']}' — {metadata['pages']} pages",
            percent=8
        )
        
        pages = extract_text_from_pdf(pdf_path)
        send_progress(
            f"Extracted text from {len(pages)} pages.",
            percent=12
        )
        
        # process
        send_progress("Processing text into chunks...", percent=15)
        chunks = process_pages(pages)   
        
        total_chunks = len(chunks)
        send_progress(f"Processed text into {total_chunks} chunks.", percent=20)

        if not chunks:
            send_progress(
                "No text found. PDF may be image-based and require OCR.",
                status="error"
            )
            return 
            
        # TTS Initialization
        engine_label = "Zyphra ZONOS2 (Quant 4)" if engine == "zonos2" else "Suno Bark"
        send_progress(f"Loading {engine_label} AI Model...", percent=22)
        
        load_models(engine=engine)
        send_progress("Model ready. Generating audio...", percent=30)
        
        # progress tracker
        tracker = ProgressTracker(
            pdf_name = pdf_path.name,
            total_chunks = total_chunks,
        )
        
        if reset:
            tracker.reset()
            send_progress("Progress reset. Starting from chunk 0.", percent=25)
        elif tracker.get_summary()['completed'] > 0:
            done = tracker.get_summary()['completed']
            send_progress(
                f"Resuming from chunk {done}/{total_chunks}...",
                percent=25
            )

        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        
        generated_files = []
        tts_start_time = time.time()
        
        for index, text in enumerate(chunks):
            if stop_event.is_set():
                break

            if tracker.is_complete(index):
                chunk_path = CHUNKS_DIR / f"chunk_{index:04d}.wav"
                generated_files.append(chunk_path)
                continue

            completed = len(tracker.completed_chunks)
            percent = 25 + int((completed / total_chunks) * 60)
            eta = calculate_eta(completed, total_chunks, tts_start_time)

            send_progress(
                f"Synthesizing chunk {index + 1}/{total_chunks} ({engine.upper()})...",
                percent=percent,
                eta=eta
            )
            
            try:
                output_path = generate_audio_chunk(text, index, engine=engine, voice=voice)
                tracker.mark_complete(index)
                generated_files.append(output_path)
            except Exception as e:
                logger.error(f"Chunk {index} failed: {e}")
                tracker.mark_failed(index)
                continue        
                
            completed = len(tracker.completed_chunks)
            percent   = 25 + int((completed / total_chunks) * 60)
            eta = calculate_eta(completed, total_chunks, tts_start_time)
            
            send_progress(
                f"Completed chunk {completed}/{total_chunks} ({engine.upper()})...",
                percent=percent,
                eta=eta
            )

        if stop_event.is_set():
            last_result = {"status": "stopped", "output_path": None, "error": None}
            send_progress("Generation stopped by user.", status="stopped")
            return

        summary = tracker.get_summary()
        send_progress(
            f"Audio generation complete. "
            f"{summary['completed']} succeeded, {summary['failed']} failed.",
            percent=87
        )
        
        # merge
        send_progress("Merging audio chunks...", percent=90)
        final_path = merge_chunks(generated_files)
        
        import scipy.io.wavfile as wav_reader
        sample_rate, audio_data = wav_reader.read(str(final_path))
        duration_seconds = len(audio_data) / sample_rate
        duration_minutes = int(duration_seconds / 60)
        
        last_result = {
            "status":      "complete",
            "output_path": str(final_path),
            "error":       None
        }

        send_progress(
            f"Audiobook complete! Duration: {duration_minutes}m ({int(duration_seconds)}s) at {sample_rate}Hz.",
            percent=100,
            eta="Done!",
            status="complete"
        )
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        last_result = {"status": "error", "output_path": None, "error": str(e)}
        send_progress(
            f"Error: {str(e)}. Check logs/run.log for details.",
            status="error"
        )

    finally:
        is_running = False
        stop_event.clear()

# Routes

@app.route("/")
def index():
    return render_template(
        "index.html",
        default_engine=TTS_ENGINE,
        default_voice=ZONOS_VOICE_PRESET if TTS_ENGINE == "zonos2" else BARK_VOICE_PRESET
    )

@app.route("/voices")
def get_voices():
    return jsonify({
        "zonos2": [
            {"id": "AmericanMale", "name": "American Male (Default) ★"},
            {"id": "AmericanFemale", "name": "American Female"},
            {"id": "BritishFemale", "name": "British Female"}
        ],
        "bark": [
            {"id": "v2/en_speaker_6", "name": "en_speaker_6 — Male, Natural ★"},
            {"id": "v2/en_speaker_0", "name": "en_speaker_0 — Male, Deep"},
            {"id": "v2/en_speaker_1", "name": "en_speaker_1 — Male, Neutral"},
            {"id": "v2/en_speaker_2", "name": "en_speaker_2 — Male, Clear"},
            {"id": "v2/en_speaker_3", "name": "en_speaker_3 — Male, Expressive"},
            {"id": "v2/en_speaker_4", "name": "en_speaker_4 — Male, Soft"},
            {"id": "v2/en_speaker_5", "name": "en_speaker_5 — Female, Neutral"},
            {"id": "v2/en_speaker_7", "name": "en_speaker_7 — Female, Clear"},
            {"id": "v2/en_speaker_8", "name": "en_speaker_8 — Female, Expressive"},
            {"id": "v2/en_speaker_9", "name": "en_speaker_9 — Female, Soft"}
        ]
    })

@app.route("/upload", methods=["POST"])
def upload():
    global is_running
    
    if is_running:
        return jsonify({
            "success": False,
            "error": "Have patience! The current book is still being processed. You can check the progress on the homepage."
        }), 409 
        
    if "pdf" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400 
    
    file = request.files["pdf"]
    
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400
        
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "File must be a PDF."}), 400

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = INPUT_DIR / file.filename
    file.save(str(pdf_path))
    logger.info(f"PDF uploaded: {pdf_path}")
    
    engine = request.form.get("engine", TTS_ENGINE).lower()
    default_v = ZONOS_VOICE_PRESET if engine == "zonos2" else BARK_VOICE_PRESET
    voice_preset = request.form.get("voice", default_v)
    reset = request.form.get("reset", "false").lower() == "true"

    thread = threading.Thread(
        target=run_pipeline,
        args=(pdf_path, voice_preset, reset, engine),
        daemon=True
    )
    thread.start()
    
    return jsonify({"success": True, "filename": file.filename, "engine": engine, "voice": voice_preset})
    
@app.route("/stream")
def stream():
    def event_stream():
        while True:
            try:
                update = progress_queue.get(timeout=30) 
                yield f"data: {update}\n\n"

                parsed = json.loads(update)
                if parsed.get("status") in ("complete", "error", "stopped"):
                    break
            except queue.Empty:
                yield "data: {\"type\": \"heartbeat\"}\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
    
@app.route("/status")
def status():
    return jsonify({
        "is_running": is_running,
        "last_result": last_result
    })

@app.route("/download")
def download():
    if last_result["status"] != "complete":
        return jsonify({"error": "No audiobook available yet."}), 404
        
    output_path = Path(last_result["output_path"])
    if not output_path.exists():
        return jsonify({"error": "Audiobook file not found on disk."}), 404
        
    return send_file(
        str(output_path),
        as_attachment=True,
        download_name="audiobook.wav",
        mimetype="audio/wav"
    )
    
@app.route("/merge", methods=["POST"])
def merge_only():
    global is_running
    if is_running:
        return jsonify({
            "success": False,
            "error": "Cannot merge while another job is running."
        }), 409
        
    def run_merge():
        global is_running, last_result
        is_running = True
        last_result = {"status": "running", "output_path": None, "error": None}
        
        try:
            send_progress("Merging existing audio chunks...", percent=10)
            final_path = merge_all_chunks_from_dir()
            
            last_result = {
                "status": "complete",
                "output_path": str(final_path),
                "error": None
            }
            send_progress("Merge complete!", percent=100, status="complete")
        except Exception as e:
            logger.error(f"Merge error: {e}", exc_info=True)
            last_result = {"status": "error", "output_path": None, "error": str(e)}
            send_progress(f"Error during merge: {str(e)}", status="error")
        finally:
            is_running = False
            
    threading.Thread(target=run_merge, daemon=True).start()
    return jsonify({"success": True})

@app.route("/stop", methods=["POST"])
def stop():
    stop_event.set()
    return jsonify({"success": True})

@app.route("/clear", methods=["POST"])
def clear_output():
    global is_running
    if is_running:
        return jsonify({"success": False, "error": "Cannot clear while a job is running."}), 409

    if CHUNKS_DIR.exists():
        for f in CHUNKS_DIR.glob("*.wav"):
            f.unlink()

    if FINAL_DIR.exists():
        for f in FINAL_DIR.glob("*.wav"):
            f.unlink()

    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    return jsonify({"success": True})

@app.route("/gpu_stats")
def gpu_stats():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return jsonify({"available": False})

        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        name, temp, util, mem_used, mem_total = parts

        return jsonify({
            "available":    True,
            "name":         name,
            "temperature":  int(temp),
            "utilization":  int(util),
            "memory_used":  int(mem_used),
            "memory_total": int(mem_total)
        })
    except Exception:
        return jsonify({"available": False})

if __name__ == "__main__":
    print("=" * 60)
    print(" PDF to Audiobook Web UI Starting...")
    print(f" Active TTS Engine : {TTS_ENGINE.upper()}")
    if TTS_ENGINE == "zonos2":
        print(f" ZONOS Quant       : {ZONOS_QUANT.upper()}")
        print(f" ZONOS Model File  : {ZONOS_MODEL_FILE.name}")
        print(f" ZONOS Backend     : {ZONOS_BACKEND.upper()}")
    print(" Access Web UI at   : http://localhost:5000")
    print("=" * 60)
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True
    )
