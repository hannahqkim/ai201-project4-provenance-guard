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

# Sub-signal weights (sum to 1.0). Variance is the strongest structural tell.
W_VARIANCE = 0.50
W_TTR = 0.35
W_PUNCT = 0.15

# Length below which the statistics are unreliable -> lower self_confidence.
MIN_RELIABLE_WORDS = 80
MIN_WORDS = 20


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

    # --- map each metric to an "AI-ness" contribution in [0,1] (1 = looks AI) ---
    ai_variance = _map_range(stdev_len, STDEV_HUMAN, STDEV_AI)   # low stdev -> high
    ai_ttr = _map_range(ttr, TTR_HUMAN, TTR_AI)                  # low diversity -> high
    ai_punct = _map_range(punct_density, PUNCT_HUMAN, PUNCT_AI)  # low density -> high

    p_ai = W_VARIANCE * ai_variance + W_TTR * ai_ttr + W_PUNCT * ai_punct
    p_ai = round(_clamp(p_ai), 4)

    # --- self-confidence: statistics are unreliable on short text ---
    if n_words <= MIN_WORDS:
        self_conf = 0.2
    else:
        self_conf = _clamp((n_words - MIN_WORDS) / (MIN_RELIABLE_WORDS - MIN_WORDS), 0.2, 1.0)
    self_conf = round(self_conf, 3)

    lean = "human" if p_ai < 0.4 else ("AI" if p_ai > 0.6 else "neither strongly")
    note = (
        f"sentence-length stdev={stdev_len:.1f} words, vocab diversity(ttr)={ttr:.2f}, "
        f"punctuation density={punct_density:.3f} -> structurally leans {lean}"
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
