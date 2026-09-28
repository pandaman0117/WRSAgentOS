"""Pinned speech resources, downloaded explicitly and verified before local loading."""

import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = ROOT / ".local/models"


def model_root(root=None):
    """Share one default between downloading and loading, independent of process cwd."""
    configured = root if root is not None else os.environ.get("WRS_AGENT_MODELS")
    return Path(configured or DEFAULT_MODEL_ROOT).expanduser().resolve()


def manifest():
    return {
        kind: json.loads(
            files(f"wrs_agent.nodes.{kind}").joinpath("assets.json").read_text("utf-8")
        )
        for kind in ("asr", "tts")
    }


def model_directory(kind, root=None):
    root = model_root(root)
    entry = manifest()[kind]
    directory = root / entry["repo"].split("/")[-1]
    receipt_path = directory / ".verified.json"
    if not receipt_path.is_file():
        raise FileNotFoundError(
            "Speech model missing or unverified at "
            + str(directory)
            + "; run scripts/download_speech_models.py to download/verify it."
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("revision") != entry["revision"]:
        raise ValueError("speech_model_revision_mismatch")
    for item in entry["files"]:
        path = directory / item["path"]
        stat = path.stat()
        if stat.st_size != item["size"] or receipt.get("files", {}).get(item["path"]) != [
            stat.st_size,
            stat.st_mtime_ns,
        ]:
            raise ValueError("speech_model_changed: rerun download_speech_models.py")
    return directory.resolve()


def verify_file(path, entry):
    """LFS SHA256, or Git blob SHA1 for the small files in the pinned commit."""
    size = path.stat().st_size
    if size != entry["size"]:
        raise ValueError("speech_asset_size_mismatch: " + entry["path"])
    digest = hashlib.sha256() if "sha256" in entry else hashlib.sha1()
    if "git_sha1" in entry:
        digest.update(f"blob {size}\0".encode())
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != entry.get("sha256", entry.get("git_sha1")):
        raise ValueError("speech_asset_hash_mismatch: " + entry["path"])


def offline_cuda():
    # Set before importing Transformers; its internal tokenizer loads must stay offline too.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Qwen speech profile requires a CUDA GPU; install the speech extra")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("Qwen speech profile requires BF16 support")
    return torch
