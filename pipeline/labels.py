"""Shared label taxonomy and definitions.

Single source of truth for every stage (classify / verify / group / rank / memo)
and for the evaluation + grading export. Mirrors the assignment's fixed taxonomy.
These MUST be kept in sync with GRADING_CONTRACT.md once the dataset ZIP is read;
any divergence found there overrides the wording below (not the label set).

LABEL_CONFIG_VERSION is stamped onto every record so cache reuse is only valid
under an unchanged config (model/effort/prompt/schema all tracked separately).
"""

LABEL_CONFIG_VERSION = "labels-v1"

# --- Eight exact primary topics (closed set) ---
TOPICS = {
    "access":    "login / account access",
    "usability": "controls / navigation / ads",
    "playback":  "playback failures / crashes / lag",
    "downloads": "offline / saved music",
    "catalog":   "content / search / recommendations / lyrics",
    "billing":   "price / charges / paywalls / premium entitlement",
    "support":   "support contact / response",
    "other":     "none of the above / unclear",
}

# --- Intents in PRECEDENCE order (first listed wins on a tie) ---
# cancellation > complaint > request > praise > unclear
INTENTS = ["cancellation", "complaint", "request", "praise", "unclear"]

# --- Severity scale 1..5 (integer). Stars/anger/cancellation alone != severity. ---
SEVERITY = {
    1: "no reported problem, praise, unclear content, or a pure feature request",
    2: "annoyance or generic criticism",
    3: "degraded/restricted function with some use remaining",
    4: "a core task clearly blocked",
    5: "explicit serious financial, privacy, or data harm",
}

# --- Sentiment is a float in [-1, 1]. Declared tolerance for golden-set eval. ---
SENTIMENT_MIN, SENTIMENT_MAX = -1.0, 1.0
SENTIMENT_TOLERANCE = 0.25  # |pred - expected| <= tolerance counts as agreement

# --- Tie-break / precedence rules from "How We Check Your Work" ---
# Topic: choose the highest-severity specific problem, then the first mentioned.
# Praise: use the first specific praised feature.
# A paid-plan mention ALONE is not billing.
# Bare boycott slogans are "unclear" unless a product complaint or personal
# departure is expressed.

# Issues classed as "complaint/cancellation" are the ones that enter grouping/ranking.
RANKABLE_INTENTS = {"complaint", "cancellation"}

ALLOWED_STATUSES = {"pending", "completed", "quarantined"}

# Reason code for the 13 empty-text rows (assignment-mandated).
QUARANTINE_EMPTY = "empty_review_text"
