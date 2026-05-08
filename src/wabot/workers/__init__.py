"""Worker process entrypoints.

Each worker module owns its own loop. Selected via the container CMD or
docker-compose `command:` field.
"""

from __future__ import annotations
