#!/bin/bash
# Re-draft watcher (founder 2026-10-22, "option B": instant-ish Re-draft with the founder's own Claude
# account, no API key). launchd runs this every 2 minutes (~/Library/LaunchAgents/com.goocampus.redraft-watch.plist).
# It asks the portal how many re-drafts are queued (plain HTTP, no AI); only when there are some does it
# start Claude Code headless with the same instructions as the scheduled news run. Claude may only run
# the news-fetcher commands and read/write its own work files.
PORTAL="/Users/Santosh/Desktop/Claude Code/goocampus-portal"
WORK="$HOME/goocampus-news"
LOCK="$WORK/.redraft.lock"
LOG="$WORK/redraft-watch.log"
SKILL="$HOME/.claude/scheduled-tasks/goocampus-news-fetch/SKILL.md"
mkdir -p "$WORK"

# one run at a time (a lock older than 40 minutes is a leftover)
if [ -f "$LOCK" ] && [ $(( $(date +%s) - $(stat -f %m "$LOCK") )) -lt 2400 ]; then exit 0; fi

cd "$PORTAL" || exit 0
Q=$(./venv/bin/python tools/news_fetcher/newsfetch.py queue 2>/dev/null | sed -n 's/^QUEUED \([0-9]*\)$/\1/p')
if [ -z "$Q" ] || [ "$Q" = "0" ]; then exit 0; fi

# a scheduled news run is in the middle of its work (fresh pending items) — let it finish first
if [ -s "$WORK/pending.json" ] && [ "$(tr -d '[:space:]' < "$WORK/pending.json")" != "[]" ] \
   && [ $(( $(date +%s) - $(stat -f %m "$WORK/pending.json") )) -lt 1800 ]; then exit 0; fi

touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT
echo "=== $(date '+%d %b %H:%M') — $Q re-draft(s) queued, starting Claude" >> "$LOG"
PROMPT="$(awk 'f;/^---$/{c++; if(c==2) f=1}' "$SKILL")"
"$HOME/.local/bin/claude" -p "$PROMPT" \
  --model opus \
  --permission-mode dontAsk \
  --add-dir "$WORK" \
  --allowedTools "Bash(cd *)" "Bash(./venv/bin/python tools/news_fetcher/newsfetch.py *)" "Read" "Write" \
  >> "$LOG" 2>&1
echo "=== $(date '+%d %b %H:%M') — finished (exit $?)" >> "$LOG"
