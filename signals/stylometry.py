"""
Signal 1 - Stylometric heuristics (structural).

Measures surface-form statistics of the text and estimates the probability it is
AI-generated. Pure Python, no external calls. See planning.md sec.2.

Output shape (matches planning.md sec.2):
    {
      "p_ai": float in [0,1],            # signal's own estimate of P(AI)
      "self_confidence": float in [0,1], # low on short text where stats are noisy
      "metrics": {sentence_len_variance, ttr, punct_density},
      "note": str                        # plain-language read of the metrics
    }

Rationale: human writing is "bursty" (uneven sentence length), lexically varied, and
irregularly punctuated; instruction-tuned LLMs regress toward the mean (uniform length,
evenly-deployed vocabulary, tidy punctuation). Low variance + smooth uniformity -> AI.
Blind spots: short texts, intentionally-uniform human forms (formal prose, constrained
poetry), and it is trivially gameable. That is why it is only 1 of 2 signals.
"""

import re
import string

# --- metric thresholds (documented so the mapping is transparent, not a black box) ---
# Sentence-length standard deviation (in words): >= HUMAN => looks human, <= AI => looks AI.
STDEV_HUMAN = 8.0
STDEV_AI = 3.0
# Type-token ratio (vocabulary diversity): >= HUMAN => human, <= AI => AI.
TTR_HUMAN = 0.70
TTR_AI = 0.40
# Punctuation density (marks per word): very low uniform punctuation leans AI (weak signal).
PUNCT_HUMAN = 0.12
PUNCT_AI = 0.04

# AI-cliche / formulaic-connective density (matches per sentence). Added in M4 calibration:
# TTR is inflated on short text and can't flag uniform AI listicles/essays, so this lexical
# tell does the work at short lengths. High density of these connectives/buzzwords -> AI.
CLICHE_HUMAN = 0.0
CLICHE_AI = 0.6
CLICHE_TERMS = (
    "furthermore", "moreover", "in conclusion", "in summary", "additionally",
    "it is important to note", "it is worth noting", "it is essential",
    "firstly", "secondly", "thirdly", "in today's", "plays a crucial role",
    "plays a vital role", "plays a significant role", "delve", "navigating the",
    "a myriad of", "ever-evolving", "paradigm shift", "testament to",
    "when it comes to", "overall,", "in essence", "notably,",
)

# Sub-signal weights (sum to 1.0). Variance and cliche density are the strongest tells;
# TTR is down-weighted because it is length-inflated on short passages.
W_VARIANCE = 0.35
W_TTR = 0.20
W_PUNCT = 0.10
W_CLICHE = 0.35

# Length calibration for self_confidence: statistics are reliable from ~FULL words up,
# and near-useless below MIN words (a haiku or one-liner).
FULL_CONF_WORDS = 40   # >= this many words -> full self_confidence
MIN_WORDS = 10         # <= this many words -> floor self_confidence
FLOOR_CONF = 0.2


def _split_sentences(text):
    parts = re.split(r"[.!?]+(?:\s+|$)", text.strip())
    return [p for p in parts if p.strip()]


def _words(text):
    return re.findall(r"[a-zA-Z']+", text.lower())


def _stdev(values):
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return var ** 0.5


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _map_range(value, at_zero, at_one):
    """Linear map: returns 0 when value==at_zero, 1 when value==at_one, clamped to [0,1]."""
    if at_one == at_zero:
        return 0.0
    return _clamp((value - at_zero) / (at_one - at_zero))


def analyze(text):
    text = (text or "").strip()
    words = _words(text)
    sentences = _split_sentences(text)
    n_words = len(words)

    if n_words == 0:
        return {
            "p_ai": 0.5,
            "self_confidence": 0.0,
            "metrics": {"sentence_len_variance": 0.0, "ttr": 0.0, "punct_density": 0.0},
            "note": "empty text - no structural signal available",
        }

    # --- metrics ---
    sent_word_counts = [len(_words(s)) for s in sentences] or [n_words]
    stdev_len = _stdev(sent_word_counts)
    ttr = len(set(words)) / n_words
    punct_count = sum(1 for ch in text if ch in string.punctuation)
    punct_density = punct_count / n_words
    lowered = text.lower()
    cliche_hits = sum(lowered.count(term) for term in CLICHE_TERMS)
    cliche_density = cliche_hits / max(len(sentences), 1)

    # --- map each metric to an "AI-ness" contribution in [0,1] (1 = looks AI) ---
    ai_variance = _map_range(stdev_len, STDEV_HUMAN, STDEV_AI)      # low stdev -> high
    ai_ttr = _map_range(ttr, TTR_HUMAN, TTR_AI)                     # low diversity -> high
    ai_punct = _map_range(punct_density, PUNCT_HUMAN, PUNCT_AI)     # low density -> high
    ai_cliche = _map_range(cliche_density, CLICHE_HUMAN, CLICHE_AI)  # more cliches -> high

    p_ai = (W_VARIANCE * ai_variance + W_TTR * ai_ttr
            + W_PUNCT * ai_punct + W_CLICHE * ai_cliche)
    p_ai = round(_clamp(p_ai), 4)

    # --- self-confidence: statistics are unreliable on short text ---
    if n_words >= FULL_CONF_WORDS:
        self_conf = 1.0
    elif n_words <= MIN_WORDS:
        self_conf = FLOOR_CONF
    else:
        self_conf = FLOOR_CONF + (n_words - MIN_WORDS) / (FULL_CONF_WORDS - MIN_WORDS) * (1.0 - FLOOR_CONF)
    self_conf = round(_clamp(self_conf, FLOOR_CONF, 1.0), 3)

    lean = "human" if p_ai < 0.4 else ("AI" if p_ai > 0.6 else "neither strongly")
    note = (
        f"sentence-length stdev={stdev_len:.1f} words, vocab diversity(ttr)={ttr:.2f}, "
        f"punctuation density={punct_density:.3f}, ai-cliche density={cliche_density:.2f}/sentence "
        f"-> structurally leans {lean}"
    )
    if n_words <= MIN_WORDS:
        note += " (text is short, so this signal is low-confidence)"

    return {
        "p_ai": p_ai,
        "self_confidence": self_conf,
        "metrics": {
            "sentence_len_variance": round(stdev_len, 3),
            "ttr": round(ttr, 4),
            "punct_density": round(punct_density, 4),
            "cliche_density": round(cliche_density, 4),
        },
        "note": note,
    }


if __name__ == "__main__":
    # Independent test harness (planning.md sec.9, M3 verification step).
    samples = {
        "human-ish (bursty, varied)": (
            "The sun dipped below the horizon. I sat on the porch, coffee cooling in my "
            "hands, and watched the whole street go quiet - one dog barking, then nothing. "
            "Funny how evenings do that. They arrive without asking."
        ),
        "ai-ish (uniform, smooth)": (
            "The sunset was very beautiful and calming to observe. The colors in the sky "
            "were bright and vivid. Sitting on the porch was a relaxing experience. The "
            "neighborhood became quiet and peaceful as the evening continued to progress."
        ),
        "short haiku": "An old silent pond. A frog jumps into the pond. Splash! Silence again.",
    }
    for name, txt in samples.items():
        r = analyze(txt)
        print(f"\n[{name}]")
        print(f"  p_ai={r['p_ai']}  self_confidence={r['self_confidence']}")
        print(f"  metrics={r['metrics']}")
        print(f"  {r['note']}")
