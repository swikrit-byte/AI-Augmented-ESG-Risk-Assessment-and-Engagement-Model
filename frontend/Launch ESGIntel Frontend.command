#!/bin/bash
# Launch ESGIntel Streamlit Frontend
# Double-click this file to run

cd "$(dirname "$0")"

echo "======================================"
echo "  ESGIntel — Streamlit Frontend"
echo "======================================"
echo ""
echo "NOTE: Make sure the FastAPI backend is running first:"
echo "  cd ../backend && uvicorn app:app --reload --port 8000"
echo ""

# Install deps if needed
if ! python3 -c "import streamlit" 2>/dev/null; then
  echo "Installing frontend dependencies..."
  pip3 install -r requirements.txt
fi

echo "Starting Streamlit on http://localhost:8501"
echo ""
streamlit run app.py --server.port 8501 --server.headless false
