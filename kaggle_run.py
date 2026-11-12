#!/usr/bin/env python3
"""
kaggle_run.py — Native CUDA Runner for Kaggle GPU instances.
Builds native CUDA ZONOS2 binaries for Tesla T4 (sm_75),
starts Flask Web UI on GPU, and exposes it via Cloudflare tunnel.
"""

import os
import sys
import time
import shutil
import multiprocessing
import subprocess
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def kill_old_processes():
    print("Stopping previous background processes...")
    for proc in ["app.py", "zonos2-server", "zonos2-cli", "cloudflared"]:
        subprocess.run(["pkill", "-9", "-f", proc], stderr=subprocess.DEVNULL)
    subprocess.run(["fuser", "-k", "5000/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["fuser", "-k", "1919/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    tunnel_log = BASE_DIR / "tunnel.log"
    if tunnel_log.exists():
        tunnel_log.unlink()

def ensure_cuda_binaries():
    target_dir = BASE_DIR / "tools" / "zonos2"
    target_dir.mkdir(parents=True, exist_ok=True)
    marker = target_dir / ".built_with_cuda"
    server_bin = target_dir / "zonos2-server"

    if marker.exists() and server_bin.exists() and os.access(str(server_bin), os.X_OK):
        print("\n[1/4] ✓ Native CUDA ZONOS2 runtime is compiled and ready.")
        return

    print("\n" + "=" * 70)
    print(" [1/4] Compiling Native CUDA ZONOS2 Runtime for Tesla T4 (sm_75)")
    print(" (Pure CUDA execution — directly allocates into 15 GB GPU VRAM)")
    print("=" * 70)

    src_dir = Path("/tmp/zonos2_src")
    if src_dir.exists():
        shutil.rmtree(src_dir, ignore_errors=True)

    print("Fetching zonos2.cpp source code with submodules...")
    subprocess.run([
        "git", "clone", "--recurse-submodules", "--depth", "1",
        "https://github.com/Zyphra/zonos2.cpp.git", str(src_dir)
    ], check=True)

    build_dir = src_dir / "build-cuda"
    print("Configuring CMake with GGML_CUDA=ON for sm_75...")
    subprocess.run([
        "cmake", "-B", str(build_dir),
        "-DGGML_CUDA=ON",
        "-DCMAKE_CUDA_ARCHITECTURES=75",
        "-DCMAKE_BUILD_TYPE=Release"
    ], cwd=str(src_dir), check=True)

    nproc = max(1, multiprocessing.cpu_count())
    print(f"Compiling with NVCC using {nproc} CPU threads (takes ~2 minutes)...")
    subprocess.run([
        "cmake", "--build", str(build_dir), "-j", str(nproc)
    ], cwd=str(src_dir), check=True)

    # Locate generated binaries
    found_bins = list(build_dir.glob("**/zonos2-server"))
    if not found_bins:
        raise RuntimeError("Build finished but zonos2-server was not found!")
    bin_folder = found_bins[0].parent

    bin_names = ["zonos2-server", "zonos2-cli", "dac-cli", "spk-encoder-cli", "quantize-cli"]
    for b in bin_names:
        src = bin_folder / b
        if src.exists():
            dst = target_dir / b
            shutil.copy2(src, dst)
            dst.chmod(0o755)
            print(f"  ✓ Installed CUDA binary: {b}")

    # Copy default voices and emotion directions if present in repo
    for extra in ["default_voices", "emotion_directions"]:
        s = src_dir / extra
        d = target_dir / extra
        if s.exists() and not d.exists():
            shutil.copytree(s, d)

    marker.write_text("cuda-sm75\n")
    print("✓ Native CUDA compilation complete!")

def check_models():
    print("\n[2/4] Checking ZONOS2 model weights...")
    models_dir = BASE_DIR / "tools" / "zonos2" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    existing = [
        p for p in models_dir.glob("zonos2-*.gguf")
        if not p.name.endswith(".part") and p.stat().st_size > 1024 * 1024
    ]
    if existing:
        existing.sort(key=lambda p: p.stat().st_size, reverse=True)
        print(f"✓ Found model: {existing[0].name} ({existing[0].stat().st_size / (1024**3):.2f} GB)")
    else:
        print("Downloading ZONOS2 Q8_0 weights (8.5 GB)...")
        subprocess.run([sys.executable, "setup_zonos.py", "--quant", "q8_0"], check=True)

def check_cloudflared():
    print("\n[3/4] Checking Cloudflare tunnel binary...")
    cf_bin = Path("/usr/local/bin/cloudflared")
    if not cf_bin.exists():
        import urllib.request
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        urllib.request.urlretrieve(url, cf_bin)
        cf_bin.chmod(0o755)
        print("✓ Downloaded cloudflared binary.")
    else:
        print("✓ Cloudflared binary ready.")

def start_services():
    print("\n[4/4] Starting Flask Web UI and CUDA Zonos2 Engine...")
    os.environ["ZONOS_QUANT"] = "q8_0"
    os.environ["ZONOS_BACKEND"] = "gpu"

    flask_proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(BASE_DIR))

    # Wait for Flask startup
    started = False
    for _ in range(25):
        time.sleep(0.5)
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:5000/status") as resp:
                if resp.status == 200:
                    started = True
                    break
        except Exception:
            pass

    if started:
        print("✓ Flask Web UI is active on http://127.0.0.1:5000")
    else:
        print("✓ Flask server initializing...")

    # Start Cloudflare tunnel
    print("Opening secure Cloudflare tunnel to public web...")
    tunnel_log = BASE_DIR / "tunnel.log"
    if tunnel_log.exists():
        tunnel_log.unlink()

    tunnel_proc = subprocess.Popen([
        "cloudflared", "tunnel",
        "--url", "http://127.0.0.1:5000",
        "--logfile", str(tunnel_log)
    ])

    url = None
    for _ in range(50):
        if tunnel_log.exists():
            content = tunnel_log.read_text(errors="ignore")
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match:
                url = match.group(0)
                break
        time.sleep(0.5)

    if url:
        print("\n" + "=" * 70)
        print("  🎉 AUDIOBOOK WEB UI IS READY (RUNNING ON NVIDIA CUDA GPU)")
        print(f"  👉 LIVE URL: {url}")
        print("=" * 70)
        print("  (Keep this cell running while using the Web UI)\n")
    else:
        print("⚠️ Tunnel log contents:")
        if tunnel_log.exists():
            print(tunnel_log.read_text())

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services...")
        tunnel_proc.terminate()
        flask_proc.terminate()
        print("Done.")

def main():
    print("=" * 70)
    print("      PDF to Audiobook — Native NVIDIA CUDA Engine      ")
    print("=" * 70)
    kill_old_processes()
    ensure_cuda_binaries()
    check_models()
    check_cloudflared()
    start_services()

if __name__ == "__main__":
    main()
