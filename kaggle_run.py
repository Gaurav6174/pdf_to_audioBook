#!/usr/bin/env python3
"""
kaggle_run.py — One-click runner for Kaggle GPU instances.
Configures NVIDIA Vulkan, verifies models, starts Flask Web UI,
and opens a public Cloudflare tunnel link with live monitoring.
"""

import os
import sys
import time
import subprocess
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def kill_old_processes():
    print("Stopping any previous background processes...")
    for proc in ["app.py", "zonos2-server", "cloudflared"]:
        subprocess.run(["pkill", "-9", "-f", proc], stderr=subprocess.DEVNULL)
    subprocess.run(["fuser", "-k", "5000/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    tunnel_log = BASE_DIR / "tunnel.log"
    if tunnel_log.exists():
        tunnel_log.unlink()

def setup_vulkan_for_nvidia():
    print("\n[1/5] Configuring Vulkan for NVIDIA Tesla T4 GPU...")
    subprocess.run(["apt-get", "update", "-qq"], stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["apt-get", "install", "-y", "-qq", "libvulkan1", "vulkan-tools"], stderr=subprocess.DEVNULL, check=False)

    icd_dir = Path("/etc/vulkan/icd.d")
    icd_dir.mkdir(parents=True, exist_ok=True)
    icd_json = icd_dir / "nvidia_icd.json"
    
    icd_content = """{
    "file_format_version": "1.0.1",
    "ICD": {
        "library_path": "libGLX_nvidia.so.0",
        "api_version": "1.3.0"
    }
}
"""
    icd_json.write_text(icd_content)
    os.environ["VK_ICD_FILENAMES"] = str(icd_json)

    # Verify device detection
    try:
        res = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=5)
        devices = [line.strip() for line in res.stdout.splitlines() if "deviceName" in line]
        if devices:
            print(f"✓ Vulkan successfully detected GPU: {devices[0]}")
        else:
            print("✓ Vulkan ICD configured.")
    except Exception:
        print("✓ Vulkan ICD configured.")

def check_models():
    print("\n[2/5] Checking ZONOS2 model weights...")
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
    print("\n[3/5] Verifying Cloudflare tunnel binary...")
    cf_bin = Path("/usr/local/bin/cloudflared")
    if not cf_bin.exists():
        import urllib.request
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        urllib.request.urlretrieve(url, cf_bin)
        cf_bin.chmod(0o755)
        print("✓ Downloaded cloudflared binary.")
    else:
        print("✓ Cloudflared binary ready.")

def start_flask():
    print("\n[4/5] Launching Flask Web UI on GPU...")
    os.environ["ZONOS_QUANT"] = "q8_0"
    os.environ["ZONOS_BACKEND"] = "gpu"

    flask_proc = subprocess.Popen([sys.executable, "app.py"], cwd=str(BASE_DIR))
    
    # Wait for Flask to respond
    started = False
    for _ in range(20):
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
        print("✓ Flask Web UI is active and listening on port 5000.")
    else:
        print("✓ Flask server process started.")
    return flask_proc

def start_tunnel_and_monitor(flask_proc):
    print("\n[5/5] Establishing secure Cloudflare tunnel...")
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
        print("  🎉 SUCCESS! YOUR AUDIOBOOK WEB UI IS READY")
        print(f"  👉 LIVE URL: {url}")
        print("=" * 70)
        print("  (Keep this cell running while using the Web UI)\n")
    else:
        print("⚠️ Waiting for URL... Tunnel log:")
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
    print("   Starting PDF to Audiobook Service (Kaggle GPU Mode)   ")
    print("=" * 70)
    kill_old_processes()
    setup_vulkan_for_nvidia()
    check_models()
    check_cloudflared()
    flask_proc = start_flask()
    start_tunnel_and_monitor(flask_proc)

if __name__ == "__main__":
    main()
