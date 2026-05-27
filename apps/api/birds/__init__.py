"""Stable bird-agent import facade.

The historical root modules stay importable for compatibility while new code can
depend on ``birds.*`` package paths.
"""

__all__ = ["goshawk", "kakapo", "shrike", "cuckoo", "pigeon"]
