"""Enable `python3 -m hashengine` by delegating to the engine CLI entry point."""
from hashengine.cli import main

raise SystemExit(main())
