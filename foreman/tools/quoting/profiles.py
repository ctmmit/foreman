"""The three quoting steering profiles.

Same drawing under three profiles produces visibly different quotes. The owner
flips between them based on shop conditions; on the hero demo (150-pc 6061
bracket) the swing is roughly $1,070 per quote.

Stored personality deltas (PricingCorrection.margin_pct_delta and
lead_delta_days) apply ON TOP of the steering-chosen base. Steering sets the
curve; personality bends it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SteeringName = Literal["conservative", "balanced", "aggressive"]


@dataclass(frozen=True)
class SteeringProfile:
    """One quoting steering profile."""

    name: SteeringName
    display_label: str  # human-readable, e.g., "Hold the line"
    margin_pct_delta: float  # adjustment vs neutral baseline
    lead_delta_days: int
    always_ask_clarifying: bool
    cite_lost_bid_benchmark: bool
    description: str


# CONSERVATIVE: protect downside on uncertain work.
CONSERVATIVE = SteeringProfile(
    name="conservative",
    display_label="Hold the line",
    margin_pct_delta=15.0,  # +15% margin cushion
    lead_delta_days=3,  # +3 days buffer
    always_ask_clarifying=True,
    cite_lost_bid_benchmark=False,
    description=(
        "Conservative quoting. New customer, tight tolerances, mixed units, "
        "or capacity tight. Always asks a clarifying question on anything "
        "ambiguous; pads margin and lead to absorb surprise."
    ),
)

# BALANCED: the default. Established customer, normal job.
BALANCED = SteeringProfile(
    name="balanced",
    display_label="Book rate",
    margin_pct_delta=0.0,
    lead_delta_days=0,
    always_ask_clarifying=False,
    cite_lost_bid_benchmark=False,
    description=(
        "Balanced quoting. Established customer, normal job. Books at the "
        "shop's standard margin and lead-time math; no padding, no undercut."
    ),
)

# AGGRESSIVE: take share when slack permits.
AGGRESSIVE = SteeringProfile(
    name="aggressive",
    display_label="Win it",
    margin_pct_delta=-8.0,  # undercut historical base
    lead_delta_days=-1,  # tighten lead where slack permits
    always_ask_clarifying=False,
    cite_lost_bid_benchmark=True,
    description=(
        "Aggressive quoting. Slack on the floor, want to take share, "
        "willing to undercut the historical base. Cites the nearest lost bid "
        "as the competitive benchmark."
    ),
)


_PROFILES: dict[SteeringName, SteeringProfile] = {
    "conservative": CONSERVATIVE,
    "balanced": BALANCED,
    "aggressive": AGGRESSIVE,
}


def get_profile(name: str) -> SteeringProfile:
    """Look up a profile by name, defaulting to BALANCED on unknown input."""
    if name not in _PROFILES:
        return BALANCED
    return _PROFILES[name]  # type: ignore[index]


def list_profile_names() -> list[str]:
    return list(_PROFILES.keys())
