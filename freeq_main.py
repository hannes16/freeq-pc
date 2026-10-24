"""Package-aware entry point for the FREEQ desktop application."""

from __future__ import annotations

import sys

import pygame

from freeq_port.freeq import FreeqGame


def main() -> int:
    game = FreeqGame()
    if "--smoke-test" in sys.argv:
        # Construction loads the story database, media manifest, images,
        # accessibility bridge, display, and mixer from the packaged bundle.
        pygame.quit()
        return 0
    game.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
