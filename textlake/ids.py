"""Synthetic stable IDs when API omits them."""

from __future__ import annotations

import hashlib


def synthetic_agent_id(name: str) -> str:
    """Stable hex ID for an agent when API omits id; name is canonical natural key."""
    return hashlib.sha256(f"agent:{name.lower()}".encode()).hexdigest()


def synthetic_submolt_id(name: str) -> str:
    """Stable hex ID for a submolt when API omits id; name is canonical natural key."""
    return hashlib.sha256(f"submolt:{name.lower()}".encode()).hexdigest()
