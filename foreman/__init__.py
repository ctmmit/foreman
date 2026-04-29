"""Foreman: a quoting deputy for small US machine shops.

Foreman-specific code lives in this package, parallel to the nanobot/ package
that holds the upstream agent runtime. Keeping the two separate minimizes
upstream-merge conflicts.
"""

__all__ = ["memory", "hooks"]
