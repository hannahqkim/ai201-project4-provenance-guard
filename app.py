"""
Provenance Guard - Flask API.

Milestone 4 scope: POST /submit runs BOTH detection signals - stylometry (structural)
and the Groq LLM classifier (semantic) - and fuses them into a real calibrated
confidence score + attribution (scoring.py). The audit log now records both individual
signal scores alongside the combined confidence. GET /log surfaces recent entries.

The real transparency labels + appeals + rate limiting (M5) are still PLACEHOLDER below.
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import audit
import scoring
from signals import llm, stylometry

load_dotenv()

app = Flask(__name__)
audit.init_db()


# --- PLACEHOLDER helper (real transparency labels arrive in M5) -------------------

def _placeholder_label(attribution, tier):
    return (
        f"[placeholder label - real transparency text arrives in M5] "
        f"attribution={attribution}, confidence_tier={tier}"
    )


# --- routes ----------------------------------------------------------------------

@app.get("/")
def health():
    return jsonify({"service": "provenance-guard", "status": "ok", "milestone": 4})


@app.post("/submit")
def submit():
    body = request.get_json(silent=True) or {}
    # Accept "text" (grading curl) or "content" (planning.md sec.8) for the body field.
    text = body.get("text") or body.get("content")
    creator_id = body.get("creator_id")

    if not text or not str(text).strip():
        return jsonify({"error": "field 'text' is required and must be non-empty"}), 400

    content_id = str(uuid.uuid4())

    # Two independent signals: structural + semantic.
    stylo = stylometry.analyze(text)
    llm_result = llm.analyze(text)

    # Fuse into a calibrated confidence score + attribution (planning.md sec.3).
    decision = scoring.score(stylo, llm_result)
    attribution = decision["attribution"]
    confidence = decision["confidence"]
    label = _placeholder_label(attribution, decision["confidence_tier"])

    timestamp = audit.utc_now_iso()
    signals = {"stylometry": stylo, "llm": llm_result}
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "ai_likelihood": decision["ai_likelihood"],
        "agreement": decision["agreement"],
        "stylometry_score": stylo["p_ai"],
        "llm_score": llm_result.get("p_ai"),
        "llm_available": decision["llm_available"],
        "status": "classified",
        "signals": signals,
        "text_excerpt": str(text)[:160],
    }
    audit.log_classification(entry)

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "ai_likelihood": decision["ai_likelihood"],
            "confidence": confidence,
            "confidence_tier": decision["confidence_tier"],
            "agreement": decision["agreement"],
            "label": label,
            "signals": signals,
            "status": "classified",
            "timestamp": timestamp,
        }
    )


@app.get("/log")
def get_log():
    limit = request.args.get("limit", default=50, type=int)
    status = request.args.get("status", default=None, type=str)
    return jsonify({"entries": audit.get_recent(limit=limit, status=status)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
