#!/bin/bash
# ESGIntel Frontend — one-time setup + start
cd "$(dirname "$0")"

echo "Checking frontend dependencies..."
python3 -m pip install -q -r requirements.txt

# Pre-answer Streamlit's first-run "email" onboarding prompt with a blank line
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo ""
echo "Starting Streamlit on http://localhost:8501"
echo ""
python3 -m streamlit run app.py --server.port 8501
