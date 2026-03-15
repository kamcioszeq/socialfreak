#!/bin/bash
# Sends a Telegram notification on SSH login.
# Setup: add to /etc/pam.d/sshd:
#   session optional pam_exec.so /path/to/ssh_notify.sh
# Or source from /etc/profile.d/ssh_notify.sh (user logins only, not non-interactive).

# Load credentials from the .env file next to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    BOT_TOKEN=$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'" | tr -d '[:space:]')
    OWNER_ID=$(grep -E '^OWNER_ID=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'" | tr -d '[:space:]')
fi

if [ -z "$BOT_TOKEN" ] || [ -z "$OWNER_ID" ]; then
    exit 0
fi

# Only notify on login (PAM_TYPE=open_session), skip close_session
if [ -n "$PAM_TYPE" ] && [ "$PAM_TYPE" != "open_session" ]; then
    exit 0
fi

LOGIN_USER="${PAM_USER:-$USER}"
LOGIN_IP="${PAM_RHOST:-unknown}"
HOSTNAME_STR="$(hostname)"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

MESSAGE="🔐 <b>SSH Login</b>

👤 <b>User:</b> <code>${LOGIN_USER}</code>
🌐 <b>From:</b> <code>${LOGIN_IP}</code>
🖥 <b>Host:</b> <code>${HOSTNAME_STR}</code>
🕐 <b>Time:</b> ${TIMESTAMP}"

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${OWNER_ID}" \
    -d "parse_mode=HTML" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

exit 0
