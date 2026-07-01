"""
Provenance Guard - Flask API.

Milestone 3 scope: POST /submit runs the first detection signal (stylometry),
returns a structured response with content_id + attribution + placeholder confidence
+ placeholder label, and writes a structured entry to the SQLite audit log.
GET /log surfaces recent entries.

Confidence fusion (M4) and the real transparency labels + appeals + rate limiting
(M5) are added in later milestones; they are marked as PLACEHOLDER below so the
seams are obvious.
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import audit
from signals import stylometry

load_dotenv()

app = Flask(__name__)
audit.init_db()


# --- PLACEHOLDER helpers (replaced in M4/M5) -------------------------------------

def _placeholder_attribution(p_ai):
    """Provisional single-signal verdict until M4 fusion. Asymmetric bands come in M4."""
    if p_ai >= 0.6:
        return "likely_ai"
    if p_ai <= 0.4:
        return "likely_human"
    return "uncertain"


def _placeholder_confidence(p_ai, self_confidence):
    """Placeholder until M4: distance-from-0.5, damped by the signal's self-confidence."""
    return round(abs(p_ai - 0.5) * 2 * self_confidence, 2)


def _placeholder_label(attribution):
    return f"[placeholder label - real transparency text arrives in M5] attribution={attribution}"


# --- routes ----------------------------------------------------------------------

@app.get("/")
def health():
    return jsonify({"service": "provenance-guard", "status": "ok", "milestone": 3})


@app.post("/submit")
def submit():
    body = request.get_json(silent=True) or {}
    # Accept "text" (grading curl) or "content" (planning.md sec.8) for the body field.
    text = body.get("text") or body.get("content")
    creator_id = body.get("creator_id")

    if not text or not str(text).strip():
        return jsonify({"error": "field 'text' is required and must be non-empty"}), 400

    content_id = str(uuid.uuid4())

    # Signal 1 - stylometry (structural).
    stylo = stylometry.analyze(text)

    # PLACEHOLDER attribution/confidence/label (single signal only in M3).
    attribution = _placeholder_attribution(stylo["p_ai"])
    confidence = _placeholder_confidence(stylo["p_ai"], stylo["self_confidence"])
    label = _placeholder_label(attribution)

    timestamp = audit.utc_now_iso()
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "stylometry_score": stylo["p_ai"],
        "status": "classified",
        "signals": {"stylometry": stylo},
        "text_excerpt": str(text)[:160],
    }
    audit.log_classification(entry)

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "signals": {"stylometry": stylo},
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
