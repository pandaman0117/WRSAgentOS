"""A separate process advertising an incompatible contract, for discovery tests only."""

import asyncio
from dataclasses import replace

from wrs_agent.__main__ import main
from wrs_agent.skills import SKILLS

SKILLS["speak"] = replace(
    SKILLS["speak"], spec=SKILLS["speak"].spec.model_copy(update={"version": 2})
)

if __name__ == "__main__":
    asyncio.run(main())
