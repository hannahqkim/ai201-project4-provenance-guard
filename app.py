"""
Provenance Guard - Flask API.

Full system (Milestone 5). POST /submit runs both detection signals - stylometry
(structural) and the Groq LLM classifier (semantic) - fuses them into a calibrated
confidence score + attribution (scoring.py), renders a plain-language transparency
label (labels.py), and writes a structured entry to the SQLite audit log (audit.py).
POST /appeal lets a creator contest a decision. Flask-Limiter rate-limits /submit.

Endpoints:
  GET  /                    health check
  POST /submit              classify text -> attribution, confidence, label
  POST /appeal              contest a decision -> status "under_review"
  GET  /log                 structured audit log (decisions + appeals)
  GET  /submission/<id>     one submission + any appeal (appeal-queue / reviewer view)
"""

import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit
import labels
import scoring
from signals import llm, stylometry

load_dotenv()

app = Flask(__name__)
audit.init_db()

# Rate limiting (planning.md sec.7). In-memory store is fine for local/dev + grading.
# Limits are applied per-route below; no global default so /log and /appeal stay open.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)
app.limiter = limiter

SUBMIT_LIMITS = "10 per minute;100 per hour"


@app.errorhandler(429)
def ratelimit_handler(e):
    resp = jsonify(
        {
            "error": "rate limit exceeded",
            "detail": str(e.description),
            "limit": SUBMIT_LIMITS,
            "message": "Too many submissions. Please slow down and try again shortly.",
        }
    )
    resp.status_code = 429
    # Flask-Limiter sets Retry-After on the response headers automatically; surface it too.
    return resp


# --- routes ----------------------------------------------------------------------

@app.get("/")
def health():
    return jsonify({"service": "provenance-guard", "status": "ok", "milestone": 5})


@app.post("/submit")
@limiter.limit(SUBMIT_LIMITS)
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

    # Fuse -> calibrated confidence + attribution, then render the reader-facing label.
    decision = scoring.score(stylo, llm_result)
    attribution = decision["attribution"]
    confidence = decision["confidence"]
    tier = decision["confidence_tier"]
    label = labels.generate(attribution, confidence, tier)

    timestamp = audit.utc_now_iso()
    signals = {"stylometry": stylo, "llm": llm_result}
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "confidence_tier": tier,
        "ai_likelihood": decision["ai_likelihood"],
        "agreement": decision["agreement"],
        "stylometry_score": stylo["p_ai"],
        "llm_score": llm_result.get("p_ai"),
        "llm_available": decision["llm_available"],
        "label": label,
        "appealed": False,
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
            "confidence_tier": tier,
            "agreement": decision["agreement"],
            "label": label,
            "signals": signals,
            "status": "classified",
            "timestamp": timestamp,
        }
    )


@app.post("/appeal")
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = body.get("content_id")
    creator_reasoning = body.get("creator_reasoning")

    if not content_id:
        return jsonify({"error": "field 'content_id' is required"}), 400
    if not creator_reasoning or not str(creator_reasoning).strip():
        return jsonify({"error": "field 'creator_reasoning' is required and must be non-empty"}), 400

    history = audit.get_by_content_id(content_id)
    original = next((e for e in history if e.get("event_type") == "classification"), None)
    if original is None:
        return jsonify({"error": f"unknown content_id: {content_id}"}), 404

    appeal_id = str(uuid.uuid4())
    logged_at = audit.utc_now_iso()
    appeal_entry = {
        "appeal_id": appeal_id,
        "content_id": content_id,
        "creator_id": original.get("creator_id"),
        "timestamp": logged_at,
        # store under both keys so it is easy to find in the log
        "creator_reasoning": str(creator_reasoning),
        "appeal_reasoning": str(creator_reasoning),
        # snapshot of the decision being contested, for the human reviewer
        "contested_attribution": original.get("attribution"),
        "contested_confidence": original.get("confidence"),
        "stylometry_score": original.get("stylometry_score"),
        "llm_score": original.get("llm_score"),
        "status": "under_review",
    }
    audit.log_appeal(content_id, appeal_entry)
    audit.update_status(content_id, "under_review")

    return jsonify(
        {
            "appeal_id": appeal_id,
            "content_id": content_id,
            "status": "under_review",
            "creator_reasoning": str(creator_reasoning),
            "logged_at": logged_at,
            "message": "Appeal received. This content is now under review by a human moderator.",
        }
    )


@app.get("/submission/<content_id>")
def submission(content_id):
    """Appeal-queue / reviewer view: the original decision plus any appeals, joined."""
    history = audit.get_by_content_id(content_id)
    if not history:
        return jsonify({"error": f"unknown content_id: {content_id}"}), 404
    original = next((e for e in history if e.get("event_type") == "classification"), None)
    appeals = [e for e in history if e.get("event_type") == "appeal"]
    return jsonify(
        {
            "content_id": content_id,
            "status": (appeals and "under_review") or (original or {}).get("status", "classified"),
            "original_decision": original,
            "appeals": appeals,
        }
    )


@app.get("/log")
def get_log():
    limit = request.args.get("limit", default=50, type=int)
    status = request.args.get("status", default=None, type=str)
    return jsonify({"entries": audit.get_recent(limit=limit, status=status)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
