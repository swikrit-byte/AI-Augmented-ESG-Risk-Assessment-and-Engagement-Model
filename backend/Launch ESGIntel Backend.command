#!/bin/bash
# Double-click this file to start the ESGIntel backend server.
# macOS may ask you to confirm opening — click Open.

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ESGIntel Backend Launcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check for API key
if grep -q "PASTE_YOUR_KEY_HERE\|your-key-here" .env 2>/dev/null; then
  echo ""
  echo "⚠️  No API key found in .env"
  echo "    Open backend/.env and replace the placeholder with your Claude API key."
  echo "    Then double-click this file again."
  echo ""
  read -p "Press Enter to close..."
  exit 1
fi

# Create venv if needed
if [ ! -d venv ]; then
  echo "→ Creating Python virtual environment..."
  python3 -m venv venv
fi

# Install / upgrade dependencies
echo "→ Installing dependencies (first run takes ~30 seconds)..."
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "✅ Server starting at http://localhost:8000"
echo "   API docs: http://localhost:8000/docs"
echo "   Press Ctrl+C to stop."
echo ""

uvicorn app:app --reload --port 8000
