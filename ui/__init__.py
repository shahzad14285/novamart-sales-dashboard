"""Orchestration-layer UI screens for the NovaMart Sales Intelligence Dashboard.

Distinct from ``components/`` (small, reusable presentational building
blocks used across pages) and ``pages/`` (thin, single-page scripts):
modules in ``ui/`` compose several *services* (``services/``) and
several ``components/`` building blocks into one coherent screen, such
as the Executive Report Center. A ``ui/`` module still renders no
business logic of its own -- it only coordinates.
"""

from __future__ import annotations
