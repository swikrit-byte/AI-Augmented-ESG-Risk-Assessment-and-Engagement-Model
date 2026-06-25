#!/bin/bash
# ESGIntel Backend — one-time setup + start
set -e

cd "$(dirname "$0")"

# 1. Create .env if it doesn't exist
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  Created .env — paste your Claude API key into backend/.env before continuing"
  echo "    CLAUDE_API_KEY=sk-ant-api03-..."
  exit 1
fi

# 2. Create venv if needed
if [ ! -d venv ]; then
  echo "→ Creating virtual environment..."
  python3 -m venv venv
fi

# 3. Install / upgrade deps
echo "→ Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# 4. Start server
echo ""
echo "✅ ESGIntel API starting at http://localhost:8000"
echo "   Docs: http://localhost:8000/docs"
echo ""
uvicorn app:app --reload --port 8000
