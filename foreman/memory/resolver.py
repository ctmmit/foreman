"""Customer-id resolver with confidence-gated escalation.

The hero learning loop only works if `shop-recall-personality` retrieves the
RIGHT customer's prior corrections. Wrong customer → wrong recalled feedback →
wrong margin applied. This is the worst quoting failure mode and per
CLAUDE.md → Non-negotiables #4 it is fully preventable.

Resolution chain (in order; first to resolve with confidence ≥ 0.9 wins):
    1. Exact match on a specific email address listed under any customer.
    2. Exact match on the email's sender domain against customer email_domains
       — high confidence only when exactly ONE customer claims the domain.
    3. Fuzzy match (difflib.SequenceMatcher) against display_name + aliases,
       optionally biased by a display-name hint passed by the caller.

Below 0.9 → return CustomerResolution(escalate=True, candidates=[...]) so the
agent surfaces options to the owner instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from foreman.memory.models import Customer


# Threshold below which we escalate to the owner. CLAUDE.md non-negotiable #4.
ESCALATION_THRESHOLD: float = 0.9

# Below this even surfacing is noise — drop from candidate list entirely.
MIN_CANDIDATE_CONFIDENCE: float = 0.30

_EMAIL_RE = re.compile(r"<?([^\s<>]+@[^\s<>]+)>?")


@dataclass
class CustomerCandidate:
    """A resolver hit, with its individual confidence and reasoning."""

    customer: Customer
    confidence: float
    matched_on: str  # e.g., "email_address:buyer@boeing.com", "domain:boeing.com", "name:fuzzy(0.87)"


@dataclass
class CustomerResolution:
    """Output of resolve_customer.

    If escalate is True, the agent must surface `candidates` to the owner and
    wait for a pick before calling `shop-recall-personality`. If escalate is
    False, `matched` is the resolved customer.
    """

    matched: Customer | None
    confidence: float
    candidates: list[CustomerCandidate] = field(default_factory=list)
    escalate: bool = False
    reason: str = ""

    @property
    def customer_id(self) -> str | None:
        return self.matched.customer_id if self.matched else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_email(raw: str) -> str | None:
    """Extract the bare email from a `Name <addr@host>` style header value."""
    if not raw:
        return None
    match = _EMAIL_RE.search(raw)
    return match.group(1).lower().strip() if match else None


def _domain_of(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.split("@", 1)[1].lower()


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _fuzzy_score(query: str, target: str) -> float:
    """0.0-1.0 similarity, normalized for case and punctuation."""
    q, t = _normalize(query), _normalize(target)
    if not q or not t:
        return 0.0
    return SequenceMatcher(None, q, t).ratio()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_customer(
    customers: dict[str, Customer],
    *,
    email_from: str | None = None,
    email_reply_to: str | None = None,
    display_name_hint: str | None = None,
) -> CustomerResolution:
    """Resolve which customer an inbound RFQ belongs to.

    Args:
        customers: dict[customer_id -> Customer], typically from
            ForemanMemoryStore.list_customers().
        email_from: raw "From:" header value, e.g., "Jane <jane@boeing.com>".
        email_reply_to: optional "Reply-To:" header, used as a secondary signal.
            If From and Reply-To map to DIFFERENT customers we escalate even
            when each individually matches with high confidence — the buyer
            relay scenario.
        display_name_hint: free-form name passed by upstream extraction
            (e.g., signature parser, CRM lookup), used only for fuzzy bias.

    Returns:
        CustomerResolution. Caller must check `.escalate` before using
        `.matched`.
    """
    if not customers:
        return CustomerResolution(
            matched=None,
            confidence=0.0,
            escalate=True,
            reason="No customers in personality store; treat as new customer.",
        )

    from_addr = _extract_email(email_from or "")
    reply_addr = _extract_email(email_reply_to or "")

    # ---- Step 1: exact address match ---------------------------------------
    primary = _resolve_by_address(customers, from_addr)

    # If From and Reply-To resolve to different customers, escalate.
    if reply_addr and reply_addr != from_addr:
        secondary = _resolve_by_address(customers, reply_addr)
        if (
            primary
            and secondary
            and primary.customer.customer_id != secondary.customer.customer_id
        ):
            return CustomerResolution(
                matched=None,
                confidence=0.0,
                candidates=[primary, secondary],
                escalate=True,
                reason=(
                    "From and Reply-To headers point to different customers — "
                    "likely a forwarded or broker-relayed RFQ."
                ),
            )

    if primary and primary.confidence >= ESCALATION_THRESHOLD:
        return CustomerResolution(
            matched=primary.customer,
            confidence=primary.confidence,
            candidates=[primary],
            escalate=False,
            reason=primary.matched_on,
        )

    # ---- Step 2: exact domain match ----------------------------------------
    domain = _domain_of(from_addr) if from_addr else None
    by_domain = _resolve_by_domain(customers, domain) if domain else []

    if len(by_domain) == 1 and by_domain[0].confidence >= ESCALATION_THRESHOLD:
        return CustomerResolution(
            matched=by_domain[0].customer,
            confidence=by_domain[0].confidence,
            candidates=by_domain,
            escalate=False,
            reason=by_domain[0].matched_on,
        )

    # ---- Step 3: fuzzy on display name -------------------------------------
    fuzzy_hits = (
        _resolve_by_fuzzy_name(customers, display_name_hint)
        if display_name_hint
        else []
    )

    # Combine all candidates, dedupe by customer_id, keep best confidence per.
    pooled: dict[str, CustomerCandidate] = {}
    for cand in [c for c in [primary] if c] + by_domain + fuzzy_hits:
        prior = pooled.get(cand.customer.customer_id)
        if prior is None or cand.confidence > prior.confidence:
            pooled[cand.customer.customer_id] = cand
    pooled_list = sorted(pooled.values(), key=lambda c: c.confidence, reverse=True)
    pooled_list = [c for c in pooled_list if c.confidence >= MIN_CANDIDATE_CONFIDENCE]

    # Top hit good enough?
    if pooled_list and pooled_list[0].confidence >= ESCALATION_THRESHOLD:
        top = pooled_list[0]
        return CustomerResolution(
            matched=top.customer,
            confidence=top.confidence,
            candidates=pooled_list,
            escalate=False,
            reason=top.matched_on,
        )

    # Otherwise escalate with whatever we found.
    return CustomerResolution(
        matched=None,
        confidence=pooled_list[0].confidence if pooled_list else 0.0,
        candidates=pooled_list,
        escalate=True,
        reason=(
            "Lookup confidence below threshold; surface candidates to owner."
            if pooled_list
            else "No matching customer found; treat as new customer."
        ),
    )


# ---------------------------------------------------------------------------
# Per-strategy resolvers (internal)
# ---------------------------------------------------------------------------


def _resolve_by_address(
    customers: dict[str, Customer], address: str | None
) -> CustomerCandidate | None:
    if not address:
        return None
    for c in customers.values():
        addrs = {a.lower() for a in c.email_addresses}
        if address in addrs:
            return CustomerCandidate(
                customer=c,
                confidence=1.0,
                matched_on=f"email_address:{address}",
            )
    return None


def _resolve_by_domain(
    customers: dict[str, Customer], domain: str | None
) -> list[CustomerCandidate]:
    if not domain:
        return []
    hits = [
        c for c in customers.values()
        if domain in {d.lower() for d in c.email_domains}
    ]
    if len(hits) == 1:
        return [
            CustomerCandidate(
                customer=hits[0],
                confidence=1.0,
                matched_on=f"domain:{domain}",
            )
        ]
    if len(hits) > 1:
        # Domain shared by multiple customers (rare, but happens in conglomerates):
        # cap each at 0.5 so we escalate.
        return [
            CustomerCandidate(
                customer=c,
                confidence=0.5,
                matched_on=f"domain:{domain} (shared)",
            )
            for c in hits
        ]
    return []


def _resolve_by_fuzzy_name(
    customers: dict[str, Customer], hint: str | None
) -> list[CustomerCandidate]:
    if not hint:
        return []
    out: list[CustomerCandidate] = []
    for c in customers.values():
        scores = [_fuzzy_score(hint, c.display_name)]
        scores.extend(_fuzzy_score(hint, alias) for alias in c.aliases)
        best = max(scores) if scores else 0.0
        if best >= MIN_CANDIDATE_CONFIDENCE:
            out.append(
                CustomerCandidate(
                    customer=c,
                    confidence=best,
                    matched_on=f"name:fuzzy({best:.2f})",
                )
            )
    out.sort(key=lambda c: c.confidence, reverse=True)
    return out
