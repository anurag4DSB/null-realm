"""Worker entry point."""

import asyncio

from nullrealm.worker.bootstrap import bootstrap_and_run

if __name__ == "__main__":
    asyncio.run(bootstrap_and_run())
