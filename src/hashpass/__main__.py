"""Enable `python3 -m hashpass` by delegating to the CLI entry point."""
from hashpass.cli import main

raise SystemExit(main())
