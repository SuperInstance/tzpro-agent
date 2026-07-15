#!/usr/bin/env python3
"""run_daemon.py — Start the tzpro-agent background daemons.

Launches all background processes:
1. capture.py — dual-cadence capture loop (30s sounder / 4min full frame)
2. deltalog.py integration — chart delta logger on 4-min cadence

Run with: python run_daemon.py
Stop with: Ctrl+C
"""

from __future__ import annotations
import asyncio, logging, sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
log = logging.getLogger("tzpro.daemon")


async def main():
    """Coordinate daemon processes."""
    from config import CAPTURES_DIR
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Import capture loop from capture module
    from capture import capture_loop

    log.info("=" * 50)
    log.info("tzpro-agent daemon starting")
    log.info("  Sounder: every 30s")
    log.info("  Full frame: every 4min")
    log.info("  Chart delta: on 4-min capture")
    log.info("  Position: from NMEA bridge (:8654)")
    log.info("=" * 50)

    try:
        await capture_loop()
    except KeyboardInterrupt:
        log.info("Shutdown")
    except Exception as e:
        log.error("Daemon error: %s", e)
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(main())
