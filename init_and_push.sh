#!/usr/bin/env bash
# init_and_push.sh - initialize git repo and optionally create GitHub repo via gh
# Usage: ./init_and_push.sh
set -e
REPO="deepseek-multi-agent-plugin"

echo "Initializing local git repository..."
if [ ! -d .git ]; then
  git init
else
  echo "Existing git repository detected."
fi

git add --all || true
if git commit -m "Initial commit: deepseek multi-agent plugin starter"; then
  echo "Committed changes"
else
  echo "No changes to commit or commit failed"
fi

git branch -M main || true

if command -v gh >/dev/null 2>&1; then
  read -p "Enter GitHub repo full name (owner/repo) or press Enter to use '$REPO': " REPO_INPUT
  if [ -z "$REPO_INPUT" ]; then
    REPO_INPUT="$REPO"
  fi
  gh repo create "$REPO_INPUT" --public --source . --remote origin --push --confirm || {
    echo "gh repo create failed; create repo manually and then push"
  }
else
  echo "gh CLI not found. Create a repo on GitHub and run:"
  echo "  git remote add origin git@github.com:<your-username>/$REPO.git"
  echo "  git push -u origin main"
fi
