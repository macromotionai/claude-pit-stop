#!/bin/bash
# Opens a fresh Claude Code session that continues from a handoff note.
# Usage: open-session.sh <handoff note path>
# In the VS Code extension on macOS it opens a new Claude tab through the extension's
# vscode://anthropic.claude-code/open?prompt= link; anywhere else it prints the prompt to paste.
here="$(cd "$(dirname "$0")" && pwd)"
note="$1"
python3 "$here/context-watch.py" --handed-off "$note"  # offers end once the new session starts
prompt="Continue from the handoff note at $note. Read it and the CHECKLIST.md it links, tell me in two lines what you're picking up, then carry on."
if [ "$CLAUDE_CODE_ENTRYPOINT" = "claude-vscode" ] && [ "$(uname)" = "Darwin" ]; then
  # VS Code hands vscode:// links to whichever window is in front, which may be another
  # project. Opening this session's folder first brings its window forward. Use the folder
  # the session started in, not $PWD: the shell may have cd'd into a subfolder, and opening
  # that would spawn a new window.
  dir=$(python3 "$here/session-start-dir.py" "$CLAUDE_CODE_SESSION_ID")
  [ -d "$dir" ] || dir="$PWD"
  open -b com.microsoft.VSCode "$dir" && sleep 1
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$prompt")
  open "vscode://anthropic.claude-code/open?prompt=$encoded" && echo "Opened a new Claude Code tab."
else
  echo "Paste this into a new session:"
  echo "$prompt"
fi
