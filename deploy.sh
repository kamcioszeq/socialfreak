#!/bin/bash

# CI/CD Deployment Script
# Watches local file changes + git remote pushes, rebuilds and redeploys on either
# Usage:
#   ./deploy.sh              — start & watch for changes
#   ./deploy.sh force-pull   — reset to origin/main
#   ./deploy.sh setup        — create .env template & directories

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="socialfreak"
CONTAINER_NAME="${PROJECT_NAME}_curator_1"
FRONTEND_NAME="${PROJECT_NAME}_frontend_1"
SSH_KEY="$HOME/.ssh/id_ed25519"
POLL_INTERVAL=5

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
info()  { echo -e "${YELLOW}[INFO]${NC} $1"; }

cd "$REPO_DIR"

# ── Setup: create .env template & required directories ────────
if [ "${1:-}" = "setup" ]; then
    log "Creating directories..."
    mkdir -p session data reels_cache

    if [ ! -f .env ]; then
        log "Creating .env template..."
        cat > .env << 'ENVEOF'
# Telegram (required)
API_ID=0
API_HASH=
BOT_TOKEN=
OWNER_ID=0
CHANNEL_ID=0

# Claude AI (required for text generation)
CLAUDE_API_KEY=

# Source channels to monitor (comma-separated, e.g. @channel1,@channel2)
SOURCE_CHANNELS=

# Facebook (optional)
FB_PAGE_ACCESS_TOKEN=
FB_PAGE_ID=

# Web panel
WEB_HOST=0.0.0.0
WEB_PORT=5174

# Approval workflow (optional, comma-separated Telegram user IDs)
REVIEWER_IDS=
ENVEOF
        log ".env created — edit it with your credentials before running"
    else
        info ".env already exists, skipping"
    fi

    log "Setup done. Edit .env then run: ./deploy.sh"
    exit 0
fi

# ── Ensure directories exist ─────────────────────────────────
mkdir -p session data reels_cache

# ── Check .env exists (warn but don't block) ─────────────────
if [ ! -f .env ]; then
    info "No .env file found. Run './deploy.sh setup' to create one, or set env vars directly."
    info "Continuing with environment variables from shell/compose..."
fi

export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o BatchMode=yes"

# Force pull: discard local changes, reset to origin/main
if [ "${1:-}" = "force-pull" ]; then
    log "Force pull: git fetch origin main && git reset --hard origin/main"
    git fetch origin main 2>/dev/null || git fetch origin
    git reset --hard origin/main
    log "Done. Repo is now at origin/main."
    exit 0
fi

# Switch remote to SSH if HTTPS
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if [[ "$REMOTE_URL" == https://github.com/* ]]; then
    SSH_URL="git@github.com:${REMOTE_URL#https://github.com/}"
    git remote set-url origin "$SSH_URL"
    log "Switched remote to SSH: $SSH_URL"
fi

# ── Local file mtime tracking ────────────────────────────────

get_mtime() {
    local root_mtime
    root_mtime=$(find "$REPO_DIR" -maxdepth 1 \
        \( -name "*.py" -o -name "*.txt" -o -name "Containerfile" -o -name "*.yml" -o -name ".env" \) \
        -exec stat -c %Y {} \; 2>/dev/null | sort -n | tail -1)
    local frontend_mtime
    frontend_mtime=$(find "$REPO_DIR/frontend" -type f 2>/dev/null | xargs stat -c %Y 2>/dev/null | sort -n | tail -1)
    echo "${root_mtime:-0}" "${frontend_mtime:-0}" | tr ' ' '\n' | sort -n | tail -1
}

# ── Log streaming ────────────────────────────────────────────

LOG_PID=""

start_logs() {
    [ -n "$LOG_PID" ] && kill "$LOG_PID" 2>/dev/null
    podman logs -f --tail=50 "$CONTAINER_NAME" 2>&1 \
        | sed "s/^/$(printf "${BLUE}[app]${NC} ")/" &
    LOG_PID=$!
}

stop_logs() {
    [ -n "$LOG_PID" ] && kill "$LOG_PID" 2>/dev/null
    LOG_PID=""
}

cleanup() {
    stop_logs
    exit 0
}
trap cleanup INT TERM

# ── Deploy (builds from local directory) ────────────────────

deploy() {
    stop_logs

    log "Building images (curator + frontend)..."
    if ! podman-compose -p "$PROJECT_NAME" build --no-cache; then
        error "Build failed."
        start_logs
        return 1
    fi

    log "Restarting service..."
    if ! podman-compose -p "$PROJECT_NAME" up -d --force-recreate; then
        error "Deploy failed."
        start_logs
        return 1
    fi

    log "Deployed. Web API: port 5174 | Web UI: http://localhost:5173. Streaming logs..."
    start_logs
}

# ── Initial start ────────────────────────────────────────────

RUNNING=$(podman ps --format '{{.Names}}' 2>/dev/null)
if ! echo "$RUNNING" | grep -q "${PROJECT_NAME}.*curator"; then
    log "Curator not running. Running full deploy..."
    deploy
elif ! echo "$RUNNING" | grep -q "${PROJECT_NAME}.*frontend"; then
    log "Frontend not running. Starting frontend..."
    podman-compose -p "$PROJECT_NAME" up -d --build frontend
fi

log "Watching local files + git remote for changes..."
start_logs

LAST_MTIME=$(get_mtime)
LAST_GIT_REV=$(git rev-parse HEAD 2>/dev/null)

# ── Poll loop ────────────────────────────────────────────────

while true; do
    sleep "$POLL_INTERVAL"

    # 1) Local file changes — rebuild immediately, no git push needed
    CURRENT_MTIME=$(get_mtime)
    if [ "$CURRENT_MTIME" != "$LAST_MTIME" ]; then
        log "Local files changed. Rebuilding..."
        LAST_MTIME="$CURRENT_MTIME"
        deploy
        LAST_GIT_REV=$(git rev-parse HEAD 2>/dev/null)
        continue
    fi

    # 2) Git remote — fetch and rebuild only if remote moved (do not overwrite local commits)
    if git fetch origin main 2>/dev/null; then
        REMOTE_REV=$(git rev-parse origin/main)
        # Update only if remote has new commits we don't have locally (pull scenario)
        if [ "$LAST_GIT_REV" != "$REMOTE_REV" ]; then
            # If we have local commits (HEAD ahead of origin/main), do not reset — let user push first
            if git merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
                log "Local commits exist (not pushed). Skipping reset. Push from server first."
                LAST_GIT_REV=$(git rev-parse HEAD)
                continue
            fi
            log "New git commit: $LAST_GIT_REV -> $REMOTE_REV"
            git reset --hard origin/main
            LAST_GIT_REV="$REMOTE_REV"
            LAST_MTIME=$(get_mtime)
            deploy
        fi
    fi
done
