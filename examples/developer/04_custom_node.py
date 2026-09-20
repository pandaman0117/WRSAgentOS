"""Start an explicitly reviewed TTS backend, or an Agent with the same skill contract."""

import asyncio
import sys

from examples.developer.custom_speech import create_node, install_contract
from wrs_agent.__main__ import main

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"tts", "agent"}:
        raise SystemExit("usage: 04_custom_node.py tts|agent [standard node options]")
    install_contract()
    try:
        asyncio.run(main(action_factory=create_node if sys.argv[1] == "tts" else None))
    except KeyboardInterrupt:
        pass
