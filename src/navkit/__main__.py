"""Allow ``python -m navkit`` as an alias for the ``navkit`` command."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())
