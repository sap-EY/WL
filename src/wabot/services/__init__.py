"""Service layer.

Modules in here orchestrate cross-cutting flows that span the broker,
DB, cache, and adapters. They are deliberately import-free at the
edges (no FastAPI, no SQLAlchemy types in their public interfaces) so
they can be reused from worker entrypoints, admin tools, and tests.
"""
