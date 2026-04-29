"""Boot-time policy resolution for the agent.

Resolution order (first hit wins):
    1. FOREMAN_POLICY_FILE — explicit path to a policy YAML.
    2. FOREMAN_POLICY_TARGET — name like "managed-cloud"; looked up in the
       packaged policies/ directory.
    3. Default to packaged policies/managed-cloud.yaml.

If none of the above resolves to a real file, bootstrap_policy() raises so
the agent fails LOUD at boot rather than silently running with no egress
restrictions. A misconfigured deployment is better surfaced than hidden.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from foreman.security.policy import Policy, load_policy
from foreman.security.network import apply_policy as _apply_policy


_DEFAULT_TARGET = "managed-cloud"


def _packaged_policies_dir() -> Path:
    """Return the policies/ dir as it sits in the source tree / install root.

    Tries (in order):
        - <repo>/policies/   (dev: working tree)
        - <site-packages>/policies/  (installed wheel, if we ship via package data)

    Falls back to the first candidate even if it doesn't exist; the caller
    re-checks before loading.
    """
    here = Path(__file__).resolve()
    # foreman/security/bootstrap.py → foreman/ → repo root
    repo_root = here.parent.parent.parent
    candidate = repo_root / "policies"
    return candidate


def resolve_policy_path() -> Path:
    """Resolve which policy YAML to load. Pure path math, no file I/O for the env-var paths."""
    explicit = os.environ.get("FOREMAN_POLICY_FILE")
    if explicit:
        return Path(explicit).expanduser()

    target = os.environ.get("FOREMAN_POLICY_TARGET", _DEFAULT_TARGET)
    return _packaged_policies_dir() / f"{target}.yaml"


def bootstrap_policy() -> Policy:
    """Resolve, load, and apply the active policy. Returns the loaded Policy.

    Raises FileNotFoundError if no policy file is reachable. Fail-closed.
    """
    path = resolve_policy_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Foreman policy file not found: {path}. "
            "Set FOREMAN_POLICY_FILE to an absolute path, or "
            "FOREMAN_POLICY_TARGET to one of: managed-cloud, "
            "single-tenant-cloud, on-prem."
        )
    policy = load_policy(path)
    _apply_policy(policy)
    logger.info("Foreman policy bootstrapped: {} (from {})", policy.name, path)
    return policy
