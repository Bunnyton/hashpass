"""Enable `python3 -m hashpass` by delegating to the student CLI entry point."""
from hashpass.student_cli import main

raise SystemExit(main())
