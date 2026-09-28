"""Explicitly download pinned Qwen models and check all files; never invoked by node startup."""

import argparse
import json
from pathlib import Path

from wrs_agent.nodes.model_assets import manifest, model_root, verify_file


def download(kind, root):
    from huggingface_hub import hf_hub_download

    entry = manifest()[kind]
    directory = model_root(root) / entry["repo"].split("/")[-1]
    print(f"{kind}: {entry['repo']} @ {entry['revision']} ({entry['license']})", flush=True)
    print(f"Resources: {sum(x['size'] for x in entry['files']) / 1024**3:.2f} GiB", flush=True)
    receipt = {"revision": entry["revision"], "files": {}}
    for item in entry["files"]:
        target = directory / item["path"]
        # A rerun checks existing bytes as well; corrupted files require a fresh download.
        valid = False
        if target.is_file():
            try:
                verify_file(target, item)
                valid = True
            except ValueError:
                pass
        if not valid:
            hf_hub_download(
                repo_id=entry["repo"], revision=entry["revision"], filename=item["path"],
                local_dir=directory, force_download=target.exists(),
            )
            verify_file(target, item)
        stat = target.stat()
        receipt["files"][item["path"]] = [stat.st_size, stat.st_mtime_ns]
        print("verified", item["path"], flush=True)
    staging = directory / ".verified.tmp"
    staging.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    staging.replace(directory / ".verified.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["asr", "tts", "both"], default="both")
    parser.add_argument("--directory", type=Path, default=model_root())
    args = parser.parse_args()
    for kind in ("asr", "tts") if args.model == "both" else (args.model,):
        download(kind, args.directory)


if __name__ == "__main__":
    main()
