@echo off
REM init_and_push.bat - initialize git repo and optionally create GitHub repo via gh
REM Usage: double-click or run from project folder

setlocal enabledelayedexpansion
set REPO=deepseek-multi-agent-plugin

if not defined GITHUB_USER (
  set /p GITHUB_USER=Enter your GitHub username (or press Enter to skip):
)

echo Initializing local git repository...
if not exist .git (
  git init
) else (
  echo Existing git repository detected.
)

git add --all
git commit -m "Initial commit: deepseek multi-agent plugin starter" || echo "No changes to commit or commit failed"

git branch -M main 2>nul || echo "Could not rename branch (maybe git older)"

if defined GITHUB_USER (
  echo Checking gh CLI authentication...
  gh auth status >nul 2>&1
  if %ERRORLEVEL% EQU 0 (
    echo Creating repository on GitHub and pushing...
    gh repo create %GITHUB_USER%/%REPO% --public --source . --remote origin --push --confirm
  ) else (
    echo gh CLI not authenticated or not installed.
    echo Run: gh auth login
    echo Or create a repo on GitHub and run the following commands:
    echo git remote add origin git@github.com:%GITHUB_USER%/%REPO%.git
    echo git push -u origin main
  )
) else (
  echo No GitHub username provided. Create a repo on GitHub and run:
  echo git remote add origin git@github.com:^<your-username^>/%REPO%.git
  echo git push -u origin main
)

endlocal
pause