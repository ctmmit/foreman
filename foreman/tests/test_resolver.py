"""Tests for the customer-id resolver — the non-negotiable correctness boundary.

Wrong customer → wrong recalled feedback → wrong margin applied. Each test
documents one resolution scenario from CLAUDE.md non-negotiable #4.
"""

from __future__ import annotations

import pytest

from foreman.memory import Customer, resolve_customer
from foreman.memory.resolver import ESCALATION_THRESHOLD, CustomerResolution


def _make(
    customer_id: str,
    display_name: str,
    *,
    email_domains: list[str] | None = None,
    email_addresses: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Customer:
    return Customer(
        customer_id=customer_id,
        display_name=display_name,
        email_domains=email_domains or [],
        email_addresses=email_addresses or [],
        aliases=aliases or [],
    )


# ---------------------------------------------------------------------------
# Empty store → escalate
# ---------------------------------------------------------------------------


def test_empty_store_escalates() -> None:
    res = resolve_customer({}, email_from="anyone@anywhere.com")
    assert res.escalate is True
    assert res.matched is None
    assert res.candidates == []
    assert "new customer" in res.reason.lower()


# ---------------------------------------------------------------------------
# Exact email-address match → confidence 1.0
# ---------------------------------------------------------------------------


def test_exact_email_address_matches_with_full_confidence() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing", email_addresses=["buyer@boeing.com"]),
        "bosch": _make("bosch", "Bosch", email_addresses=["sales@bosch.com"]),
    }
    res = resolve_customer(customers, email_from="Jane Doe <buyer@boeing.com>")
    assert res.escalate is False
    assert res.matched is not None
    assert res.matched.customer_id == "boeing"
    assert res.confidence == 1.0
    assert "email_address" in res.reason


# ---------------------------------------------------------------------------
# Exact domain match — single customer claims it
# ---------------------------------------------------------------------------


def test_unique_domain_match_resolves_with_full_confidence() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing", email_domains=["boeing.com"]),
    }
    res = resolve_customer(customers, email_from="new-contact@boeing.com")
    assert res.escalate is False
    assert res.matched.customer_id == "boeing"
    assert res.confidence == 1.0
    assert "domain:boeing.com" in res.reason


def test_shared_domain_escalates_with_both_candidates() -> None:
    """A domain claimed by multiple customers (rare; conglomerates) must not auto-resolve."""
    customers = {
        "boeing-aero": _make("boeing-aero", "Boeing Aerospace", email_domains=["boeing.com"]),
        "boeing-def": _make("boeing-def", "Boeing Defense", email_domains=["boeing.com"]),
    }
    res = resolve_customer(customers, email_from="x@boeing.com")
    assert res.escalate is True
    assert {c.customer.customer_id for c in res.candidates} == {"boeing-aero", "boeing-def"}
    for c in res.candidates:
        assert c.confidence < ESCALATION_THRESHOLD


# ---------------------------------------------------------------------------
# Reply-To divergence (forwarded RFQ) → escalate even if both individually match
# ---------------------------------------------------------------------------


def test_from_and_reply_to_different_customers_escalates() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing", email_addresses=["buyer@boeing.com"]),
        "broker": _make("broker", "Broker Co", email_addresses=["agent@brokers.com"]),
    }
    res = resolve_customer(
        customers,
        email_from="agent@brokers.com",
        email_reply_to="buyer@boeing.com",
    )
    assert res.escalate is True
    candidate_ids = {c.customer.customer_id for c in res.candidates}
    assert candidate_ids == {"boeing", "broker"}
    assert "forwarded" in res.reason.lower() or "broker" in res.reason.lower()


def test_from_and_reply_to_same_customer_resolves_normally() -> None:
    customers = {
        "boeing": _make(
            "boeing",
            "Boeing",
            email_addresses=["buyer@boeing.com", "assistant@boeing.com"],
        ),
    }
    res = resolve_customer(
        customers,
        email_from="assistant@boeing.com",
        email_reply_to="buyer@boeing.com",
    )
    assert res.escalate is False
    assert res.matched.customer_id == "boeing"


# ---------------------------------------------------------------------------
# Fuzzy name fallback
# ---------------------------------------------------------------------------


def test_fuzzy_name_matches_with_strong_hint() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing Frenos S.A.", aliases=["Boeing Brakes"]),
    }
    res = resolve_customer(
        customers,
        email_from="contact@unknown-domain.com",
        display_name_hint="Boeing Brakes",
    )
    assert res.escalate is False
    assert res.matched.customer_id == "boeing"
    assert res.confidence >= ESCALATION_THRESHOLD


def test_fuzzy_name_weak_hint_escalates_with_candidates() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing Frenos S.A."),
    }
    res = resolve_customer(
        customers,
        email_from="contact@unknown-domain.com",
        display_name_hint="Boeing-ish maybe",
    )
    assert res.escalate is True
    # Should still surface boeing as a candidate (reasonably similar) but
    # below the auto-resolve threshold.
    if res.candidates:
        assert res.candidates[0].customer.customer_id == "boeing"
        assert res.candidates[0].confidence < ESCALATION_THRESHOLD


# ---------------------------------------------------------------------------
# No match anywhere → escalate cleanly
# ---------------------------------------------------------------------------


def test_no_match_anywhere_escalates_empty() -> None:
    customers = {
        "boeing": _make("boeing", "Boeing", email_domains=["boeing.com"]),
    }
    res = resolve_customer(customers, email_from="someone@completely-different.io")
    assert res.escalate is True
    assert res.matched is None
    assert "new customer" in res.reason.lower() or "below threshold" in res.reason.lower()


# ---------------------------------------------------------------------------
# CLAUDE.md non-negotiable #4: confidence below 0.9 must NEVER auto-resolve
# ---------------------------------------------------------------------------


def test_no_resolution_ever_returns_match_below_threshold() -> None:
    """Property: if confidence < 0.9, matched MUST be None and escalate MUST be True."""
    scenarios: list[CustomerResolution] = [
        resolve_customer({}, email_from="x@y.com"),
        resolve_customer(
            {"a": _make("a", "Alpha", email_domains=["x.com"]),
             "b": _make("b", "Beta", email_domains=["x.com"])},
            email_from="z@x.com",
        ),
        resolve_customer(
            {"a": _make("a", "Alpha")},
            email_from="z@unknown.com",
            display_name_hint="totally-different-name",
        ),
    ]
    for res in scenarios:
        if res.confidence < ESCALATION_THRESHOLD:
            assert res.matched is None, f"Below-threshold resolution leaked a match: {res}"
            assert res.escalate is True
