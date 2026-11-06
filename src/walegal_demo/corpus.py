"""A small, FICTIONAL corpus for the demo.

================================ IMPORTANT ================================
Every authority, citation, and holding in this file is INVENTED for the sole
purpose of demonstrating the pipeline. None of it is real Washington law.
The fictional statutes concern a made-up "Widget Safety Act" so there is no
chance of confusing the demo with genuine legal authority.

The real system runs against ~271K actual Washington authorities (RCW, WAC,
court rules, the Constitution, and case law from five courts). That corpus is
not part of this showcase.
==========================================================================
"""

from __future__ import annotations

from walegal_demo.types import (
    AUTHORITY_CASE,
    AUTHORITY_CONSTITUTION,
    AUTHORITY_STATUTE,
    COURT_APPEALS,
    COURT_STATE_SUPREME,
    Authority,
)

# --- Fictional statutes (Widget Safety Act) ---
_STATUTES = [
    Authority(
        authority_id="rcw-70-400-010",
        canonical_cite="RCW 70.400.010",
        authority_type=AUTHORITY_STATUTE,
        text=(
            "A person commits unlawful widget operation if the person operates a "
            "regulated widget in a public place without a valid widget endorsement "
            "issued under this chapter. Operation includes activating, steering, or "
            "remotely controlling the widget."
        ),
    ),
    Authority(
        authority_id="rcw-70-400-020",
        canonical_cite="RCW 70.400.020",
        authority_type=AUTHORITY_STATUTE,
        text=(
            "Unlawful widget operation in the first degree requires (1) operation "
            "without an endorsement and (2) operation within five hundred feet of a "
            "school or hospital. A violation is a class C felony."
        ),
    ),
    Authority(
        authority_id="rcw-70-400-030",
        canonical_cite="RCW 70.400.030",
        authority_type=AUTHORITY_STATUTE,
        text=(
            "It is an affirmative defense to a charge under RCW 70.400.020 that the "
            "operator held a provisional endorsement and the widget did not exceed "
            "the safe-speed threshold defined in RCW 70.400.040."
        ),
    ),
    Authority(
        authority_id="rcw-70-400-040",
        canonical_cite="RCW 70.400.040",
        authority_type=AUTHORITY_STATUTE,
        text=(
            "The department shall set a safe-speed threshold for each widget class. "
            "The threshold for a class A widget is eight miles per hour."
        ),
    ),
]

# --- Fictional constitution provision ---
_CONSTITUTION = [
    Authority(
        authority_id="const-art1-7",
        canonical_cite="Const. art. I, § 7",
        authority_type=AUTHORITY_CONSTITUTION,
        text=(
            "No person shall be disturbed in their private affairs, or their widget "
            "seized, without authority of law."
        ),
    ),
]

# --- Fictional case law ---
_CASES = [
    Authority(
        authority_id="case-northup",
        canonical_cite="State v. Northup",
        authority_type=AUTHORITY_CASE,
        court_level=COURT_STATE_SUPREME,
        parallel_cites=("199 Wn.2d 410", "510 P.3d 88"),
        text=(
            "The Supreme Court held that remote control of a widget over a network "
            "constitutes operation under RCW 70.400.010, because the statute reaches "
            "any form of control. The State must still prove the absence of a valid "
            "endorsement as an element."
        ),
    ),
    Authority(
        authority_id="case-cascade",
        canonical_cite="Cascade Widget Co. v. Dep't of Licensing",
        authority_type=AUTHORITY_CASE,
        court_level=COURT_APPEALS,
        parallel_cites=("21 Wn. App. 2d 55",),
        text=(
            "The Court of Appeals held that the safe-speed affirmative defense under "
            "RCW 70.400.030 is available only where the operator produces the "
            "provisional endorsement at the time of the stop."
        ),
    ),
    Authority(
        authority_id="case-old-meadows",
        canonical_cite="State v. Meadows",
        authority_type=AUTHORITY_CASE,
        court_level=COURT_APPEALS,
        status="overruled",  # demonstrates the negative-treatment check
        parallel_cites=("12 Wn. App. 2d 1",),
        text=(
            "An older decision holding that network-based control did NOT constitute "
            "operation. This holding was later overruled by State v. Northup."
        ),
    ),
]

_CORPUS: list[Authority] = _STATUTES + _CONSTITUTION + _CASES


def get_corpus() -> list[Authority]:
    """Return the full (fictional) demo corpus."""
    return list(_CORPUS)
