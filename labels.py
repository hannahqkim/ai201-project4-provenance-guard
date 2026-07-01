"""
Transparency label generator.

Maps a fused decision (attribution + confidence tier) to the plain-language label a reader
sees. Implements the variants written verbatim in planning.md sec.4. No jargon - a
non-technical reader can understand what it means - and the *wording* changes with
confidence, not just the number.

Reachable variants:
  likely_ai   + high      -> HIGH_AI
  likely_ai   + moderate  -> MODERATE_AI
  likely_human+ high      -> HIGH_HUMAN
  likely_human+ moderate  -> MODERATE_HUMAN
  uncertain   (any tier)  -> UNCERTAIN
(likely_ai / likely_human never occur at the low tier because the scorer forces a
low-confidence result to `uncertain`.)
"""

import scoring


def _high_ai(c):
    return (
        f"🤖 Likely AI-generated. Our checks strongly suggest this text was produced by an "
        f"AI tool. Both how it's written (sentence rhythm and word variety) and how it reads "
        f"overall point the same way. Confidence: high ({c}%). This is an automated "
        f"assessment, not a certainty — if you wrote this and disagree, you can appeal."
    )


def _moderate_ai(c):
    return (
        f"🤖 Leans toward AI-generated. Some signs point to AI authorship, but this isn't a "
        f"firm call. Confidence: moderate ({c}%). If you wrote this yourself and disagree, "
        f"you can appeal."
    )


def _high_human(c):
    return (
        f"✍️ Likely written by a person. Our checks found the natural variety in rhythm and "
        f"word choice we'd expect from a human writer, and nothing that points to AI "
        f"generation. Confidence: high ({c}%). No automated check is perfect, but this reads "
        f"as human work."
    )


def _moderate_human(c):
    return (
        f"✍️ Leans toward human-written. This mostly reads like a person's writing, though "
        f"we're not fully certain. Confidence: moderate ({c}%). If anything here looks off to "
        f"you, you can appeal."
    )


def _uncertain(c):
    return (
        f"❓ We're not sure. Our checks came back mixed or borderline, so we're not putting a "
        f"label on this one. Confidence: low ({c}%). We'd rather say \"we don't know\" than "
        f"risk wrongly calling a person's work AI-generated. A human reviewer can take a "
        f"closer look if the creator requests it."
    )


def generate(attribution, confidence, tier=None):
    """Return the reader-facing label string for a decision."""
    tier = tier or scoring.tier(confidence)
    c = int(round(confidence))

    if attribution == scoring.AI:
        return _high_ai(c) if tier == "high" else _moderate_ai(c)
    if attribution == scoring.HUMAN:
        return _high_human(c) if tier == "high" else _moderate_human(c)
    return _uncertain(c)


if __name__ == "__main__":
    print("HIGH AI:\n", generate(scoring.AI, 91, "high"), "\n")
    print("MODERATE AI:\n", generate(scoring.AI, 55, "moderate"), "\n")
    print("HIGH HUMAN:\n", generate(scoring.HUMAN, 88, "high"), "\n")
    print("MODERATE HUMAN:\n", generate(scoring.HUMAN, 55, "moderate"), "\n")
    print("UNCERTAIN:\n", generate(scoring.UNCERTAIN, 20, "low"))
