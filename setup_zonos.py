#!/usr/bin/env python3
"""
setup_zonos.py — Automated installer for Zyphra ZONOS2 runtime and Q4 GGUF models.
Runs seamlessly on any Linux system (local Ubuntu, Kaggle, Google Colab).
"""

import os
import sys
import tarfile
import urllib.request
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
ZONOS_DIR = BASE_DIR / "tools" / "zonos2"
MODELS_DIR = ZONOS_DIR / "models"

ZONOS_RELEASE_URL = "https://github.com/Zyphra/zonos2.cpp/releases/download/v0.5.2/zonos2-linux-x64-vulkan.tar.gz"
HF_BASE_URL = "https://huggingface.co/Zyphra/ZONOS2-GGUF/resolve/main"
REQUIRED_MODELS = ["zonos2-q4_k.gguf", "dac.gguf", "spk-encoder.gguf"]

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

def setup_models():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    missing = []
    for filename in REQUIRED_MODELS:
        target = MODELS_DIR / filename
        if target.exists() and target.stat().st_size > 1024 * 1024:
            print(f"✓ {filename} already present ({target.stat().st_size / (1024*1024):.1f} MB)")
        else:
            missing.append(filename)

    if not missing:
        print("\n✓ All ZONOS2 Q4 models are present and ready!")
        return

    print(f"\nDownloading missing models: {missing}...")

    # Try huggingface_hub first, fallback to curl
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
            # Multi-platform curl download
            url = f"{HF_BASE_URL}/{filename}"
            ret = subprocess.run(["curl", "-L", "--progress-bar", "-o", str(target), url])
            if ret.returncode != 0:
                raise RuntimeError(f"Failed to download {filename} from {url}")

        print(f"✓ {filename} ready.")

    print("\n✓ All ZONOS2 models ready!")

if __name__ == "__main__":
    print("=" * 60)
    print(" Setting up Zyphra ZONOS2 (Quantization 4) Engine")
    print("=" * 60)
    setup_binaries()
    setup_models()
    print("=" * 60)
    print(" Setup Complete! You can now run main.py or app.py.")
    print("=" * 60)
