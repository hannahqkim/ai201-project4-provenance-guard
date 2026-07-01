"""
Confidence scorer - fuses the two detection signals into a single calibrated result.

Implements planning.md sec.3 exactly. Two numbers are reported because they answer two
different questions:
  - ai_likelihood in [0,1]: which direction / how strongly the evidence points to AI.
  - confidence   in [0,100]: how much to trust the verdict (100 = sure, 0 = coin flip).

Fusion:
  ai_likelihood = W_LLM * p_ai_llm + W_STYLO * p_ai_stylo     (LLM weighted higher)
  agreement     = 1 - |p_ai_llm - p_ai_stylo|
  confidence    = |ai_likelihood - 0.5| * 2 * agreement * stylo_self_confidence * 100

Three independent things drive confidence down: a borderline combined score, disagreeing
signals, and too-short input (via stylometry's self_confidence).

Asymmetric verdict thresholds (false positives - calling a human's work AI - are worse on a
writing platform, so AI is *hard to earn*):
  AI      if ai_likelihood >= AI_THRESHOLD (0.75) and agreement >= MIN_AGREEMENT (0.5)
  HUMAN   if ai_likelihood <= HUMAN_THRESHOLD (0.35)
  UNCERTAIN otherwise, OR whenever confidence is in the Low tier (< 35)

Graceful degradation: if the LLM signal is unavailable, fuse stylometry alone and hard-cap
confidence into the Low tier (single-signal results are never "high confidence").
"""

# --- fusion weights (sum to 1.0) ---
# M4 calibration: bumped LLM 0.60->0.65 after live Groq data showed real llama-3.3-70b
# tops out near p_ai=0.8 on clearly-AI text (the plan assumed ~0.9), so the semantic
# signal needed slightly more pull to surface AI without help from a maxed-out score.
W_LLM = 0.65
W_STYLO = 0.35

# --- verdict thresholds (asymmetric) ---
# M4 calibration: lowered AI 0.75->0.70 for the same reason. Still asymmetric (AI is much
# harder to earn than HUMAN) and still gated on signal agreement, and the stylometry cliche
# signal keeps clearly-AI text (stylo ~0.53) cleanly above formal-human text (stylo ~0.27),
# so this does not reintroduce false positives on polished human writing.
AI_THRESHOLD = 0.70
HUMAN_THRESHOLD = 0.35
MIN_AGREEMENT = 0.50

# --- confidence tiers (drive which label wording M5 shows) ---
HIGH_TIER = 65
MODERATE_TIER = 35
LOW_TIER_CAP = 34  # ceiling for single-signal (LLM unavailable) results

# attribution strings surfaced in the API + audit log
AI = "likely_ai"
HUMAN = "likely_human"
UNCERTAIN = "uncertain"


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _direction_agreement(p_llm, p_stylo):
    """Direction-aware agreement in [0,1] (M4 calibration refinement of planning.md sec.3's
    original `1 - |p_llm - p_stylo|`). Two signals only truly conflict when they point in
    OPPOSITE directions relative to the neutral 0.5. A signal sitting near 0.5 is abstaining,
    not disagreeing, so it should not drag confidence down. Conflict is scaled by the strength
    of the weaker opposing signal."""
    d_llm = p_llm - 0.5
    d_stylo = p_stylo - 0.5
    same_direction = (d_llm >= 0) == (d_stylo >= 0)
    if same_direction:
        return 1.0
    conflict = 2.0 * min(abs(d_llm), abs(d_stylo))  # in [0,1]
    return _clamp(1.0 - conflict)


def tier(confidence):
    if confidence >= HIGH_TIER:
        return "high"
    if confidence >= MODERATE_TIER:
        return "moderate"
    return "low"


def score(stylo, llm):
    """stylo: dict from signals.stylometry.analyze; llm: dict from signals.llm.analyze.
    Returns the fused decision dict."""
    p_stylo = stylo["p_ai"]
    self_conf = stylo.get("self_confidence", 1.0)
    llm_available = bool(llm.get("available"))
    p_llm = llm.get("p_ai")

    if llm_available and p_llm is not None:
        ai_likelihood = W_LLM * p_llm + W_STYLO * p_stylo
        agreement = _direction_agreement(p_llm, p_stylo)
    else:
        # Degrade to stylometry alone.
        ai_likelihood = p_stylo
        agreement = self_conf  # no second signal to corroborate

    ai_likelihood = _clamp(ai_likelihood)
    agreement = _clamp(agreement)

    confidence = abs(ai_likelihood - 0.5) * 2 * agreement * self_conf * 100
    if not llm_available:
        confidence = min(confidence, LOW_TIER_CAP)
    confidence = int(round(confidence))

    # --- verdict ---
    if confidence < MODERATE_TIER:
        verdict = UNCERTAIN
    elif ai_likelihood >= AI_THRESHOLD and agreement >= MIN_AGREEMENT:
        verdict = AI
    elif ai_likelihood <= HUMAN_THRESHOLD:
        verdict = HUMAN
    else:
        verdict = UNCERTAIN

    return {
        "attribution": verdict,
        "ai_likelihood": round(ai_likelihood, 4),
        "confidence": confidence,
        "confidence_tier": tier(confidence),
        "agreement": round(agreement, 4),
        "llm_available": llm_available,
        "signal_scores": {
            "stylometry": p_stylo,
            "llm": p_llm if llm_available else None,
        },
    }
