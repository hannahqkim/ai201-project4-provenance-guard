#!/usr/bin/env bash
# Fire the four Milestone-4 calibration inputs at a running Provenance Guard server
# and pretty-print each response. Start the server first (in your venv):
#   python app.py
# then, in another terminal:
#   ./test_samples.sh            # defaults to http://localhost:5000
#   ./test_samples.sh http://localhost:5001   # if you moved off port 5000 (AirPlay)

set -u
BASE="${1:-http://localhost:5000}"
PY="$(command -v python3 || command -v python)"

# Quick reachability check so you get a clear message instead of a JSON parse error.
if ! curl -s -o /dev/null "$BASE/"; then
  echo "ERROR: no server responding at $BASE"
  echo "Start it first:  source .venv/bin/activate && python app.py"
  exit 1
fi

declare -a NAMES=(
  "CLEARLY AI (formal essay)"
  "CLEARLY HUMAN (casual)"
  "BORDERLINE (formal human)"
  "BORDERLINE (lightly edited AI)"
)
declare -a TEXTS=(
  "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment."
  "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably wont go back unless someone drags me there"
  "The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations."
  "I have been thinking a lot about remote work lately. There are genuine tradeoffs - flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type."
)
declare -a CREATORS=("test-ai" "test-human" "test-formal" "test-edited")

for i in "${!NAMES[@]}"; do
  echo "======================================================================"
  echo "== ${NAMES[$i]}"
  echo "======================================================================"
  # Build a valid JSON body safely (handles quotes/newlines) with python, then POST it.
  BODY="$("$PY" -c 'import json,sys; print(json.dumps({"text": sys.argv[1], "creator_id": sys.argv[2]}))' "${TEXTS[$i]}" "${CREATORS[$i]}")"
  curl -s -X POST "$BASE/submit" -H "Content-Type: application/json" -d "$BODY" | "$PY" -m json.tool
  echo
done

echo "======================================================================"
echo "== AUDIT LOG (GET /log)"
echo "======================================================================"
curl -s "$BASE/log" | "$PY" -m json.tool
