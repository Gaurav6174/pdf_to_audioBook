#!/usr/bin/env python3
"""
setup_zonos.py — Automated installer for Zyphra ZONOS2 runtime and GGUF models.
Supports any quantization: q4_k (4.9GB), q8_0 (8.5GB recommended for 16GB GPU), or f16 (15.3GB).
"""

import os
import sys
import tarfile
import urllib.request
import subprocess
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent
ZONOS_DIR = BASE_DIR / "tools" / "zonos2"
MODELS_DIR = ZONOS_DIR / "models"

ZONOS_RELEASE_URL = "https://github.com/Zyphra/zonos2.cpp/releases/download/v0.5.2/zonos2-linux-x64-vulkan.tar.gz"
HF_BASE_URL = "https://huggingface.co/Zyphra/ZONOS2-GGUF/resolve/main"

def download_progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, downloaded * 100 / total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        sys.stdout.write(f"\r  Progress: {percent:.1f}% ({mb:.1f} / {total_mb:.1f} MB)")
    else:
        sys.stdout.write(f"\r  Downloaded: {downloaded / (1024 * 1024):.1f} MB")
    sys.stdout.flush()

def setup_binaries():
    cli_bin = ZONOS_DIR / "zonos2-cli"
    if cli_bin.exists() and os.access(str(cli_bin), os.X_OK):
        print("✓ Zonos2 runtime binaries already installed.")
        return

    ZONOS_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ZONOS_DIR / "zonos2_runtime.tar.gz"

    print("Downloading Zonos2 C++ runtime binaries from GitHub...")
    urllib.request.urlretrieve(ZONOS_RELEASE_URL, archive_path, download_progress)
    print("\nExtracting runtime binaries...")

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=str(ZONOS_DIR))

    if archive_path.exists():
        archive_path.unlink()

    for bin_name in ["zonos2-cli", "zonos2-server", "dac-cli", "spk-encoder-cli"]:
        b = ZONOS_DIR / bin_name
        if b.exists():
            os.chmod(str(b), 0o755)

    print("✓ Zonos2 C++ runtime binaries ready.")

def setup_models(quant: str = "q8_0"):
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    backbone_file = f"zonos2-{quant}.gguf"
    required_files = [backbone_file, "dac.gguf", "spk-encoder.gguf"]

    missing = []
    for filename in required_files:
        target = MODELS_DIR / filename
        if target.exists() and target.stat().st_size > 1024 * 1024:
            print(f"✓ {filename} already present ({target.stat().st_size / (1024*1024):.1f} MB)")
        else:
            missing.append(filename)

    if not missing:
        print(f"\n✓ All ZONOS2 {quant.upper()} models are present and ready!")
        return

    print(f"\nDownloading missing models ({quant.upper()}): {missing}...")

    hf_available = False
    try:
        from huggingface_hub import hf_hub_download
        hf_available = True
    except ImportError:
        pass

    for filename in missing:
        target = MODELS_DIR / filename
        print(f"Fetching {filename}...")
        if hf_available:
            from huggingface_hub import hf_hub_download
            hf_hub_download(
                repo_id="Zyphra/ZONOS2-GGUF",
                filename=filename,
                local_dir=str(MODELS_DIR),
                local_dir_use_symlinks=False
            )
        else:
            url = f"{HF_BASE_URL}/{filename}"
            ret = subprocess.run(["curl", "-L", "--progress-bar", "-o", str(target), url])
            if ret.returncode != 0:
                raise RuntimeError(f"Failed to download {filename} from {url}")

        print(f"✓ {filename} ready.")

    print(f"\n✓ All ZONOS2 {quant.upper()} models ready!")

def update_env_file(quant: str):
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    settings = {
        "ZONOS_QUANT": quant,
        "TTS_ENGINE": "zonos2"
    }

    has_gpu = False
    try:
        import torch
        has_gpu = torch.cuda.is_available()
    except Exception:
        pass
    if not has_gpu and Path("/proc/driver/nvidia/version").exists():
        has_gpu = True

    if has_gpu:
        settings["ZONOS_BACKEND"] = "gpu"
        settings["DEVICE"] = "cuda"

    new_keys = set(settings.keys())
    updated_lines = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in new_keys:
                updated_lines.append(f"{k}={settings[k]}")
                new_keys.remove(k)
                continue
        updated_lines.append(line)

    for k in new_keys:
        updated_lines.append(f"{k}={settings[k]}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    backend_val = settings.get("ZONOS_BACKEND", "cpu")
    print(f"✓ Configuration saved to .env (ZONOS_QUANT={quant}, ZONOS_BACKEND={backend_val})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Zyphra ZONOS2 runtime and model weights.")
    parser.add_argument(
        "--quant",
        type=str,
        default=os.getenv("ZONOS_QUANT", "q8_0"),
        choices=["q4_k", "q5_k", "q6_k", "q8_0", "f16"],
        help="Quantization tier to download: 'q8_0' (recommended 8.5GB for 16GB GPU), 'q4_k' (4.9GB), or 'f16' (15.3GB)"
    )
    args = parser.parse_args()

    print("=" * 65)
    print(f" Setting up Zyphra ZONOS2 ({args.quant.upper()}) Engine")
    print("=" * 65)
    setup_binaries()
    setup_models(quant=args.quant)
    update_env_file(quant=args.quant)
    print("=" * 65)
    print(" Setup Complete! You can now run main.py or app.py.")
    print("=" * 65)
