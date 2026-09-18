---
name: handoff
description: Hand a long session to a fresh one without losing detail. Updates the project's CHECKLIST.md, writes a handoff note that carries the pending request, and opens a new session that continues from it. Use when the context-watch hook's "Hand off + new session" option is picked, or when the user says handoff, hand off, fresh session or new session.
argument-hint: "What will the next session be used for?"
---

A fresh session re-reads a few thousand tokens instead of this whole conversation. The checklist carries what is done and what is next; the note carries only what a checklist can't. Do the three steps in order, and do no further work in this session afterwards.

Never hand off mid-phase. If an edit is half-applied or a test is mid-fix, first bring the work to a consistent state (files parse, nothing half-written), and record in the note exactly what is still unverified.

## 1. Update the checklist

The project root is `git rev-parse --show-toplevel` run from the working directory, or the working directory itself if that fails or returns the home folder. The checklist is `CHECKLIST.md` there. If it is missing, create it from [CHECKLIST-TEMPLATE.md](CHECKLIST-TEMPLATE.md) and seed Next from any open items in PLAN.md or NEXT.md.

- Tick `[x]` only what was verified this session, naming the evidence (commit, file, test output). Unverified work stays `[~]` with what is left.
- Add steps discovered this session to Next. Move rejected ideas to Parked with the reason.
- Update the `Updated:` line in the user's local time.
- Keep it under ~1.5k tokens: past ~15 Done lines, collapse each finished phase to one line.
- Other tabs may be working in the same project. Re-read the file right before editing, and change only your workstream's block with exact-match edits.

## 2. Write the note

Save it to `~/.claude/handoffs/<project-folder-in-kebab-case>/<YYYY-MM-DD-HHMM>-<topic-in-kebab-case>.md`. It lives outside the project on purpose: some repos are shared, and the note carries private working context.

Sections, each skipped when empty:

- **Pending request**: the user's latest message, verbatim, if it has not been done.
- **Checklist**: the absolute path to CHECKLIST.md and which item is Now.
- **Where the current step stands**: exact files, lines, commands and last output, enough to resume without re-deriving anything.
- **Dead ends**: what was tried and why it failed, so it is not retried.
- **Unverified assumptions**, labelled as such.
- **Decisions and why**: agreed with the user this session and not recorded anywhere else.
- **Gotchas**: constraints learned the hard way.
- **Suggested skills** for the next session.
- **References**: docs, commits and artifacts by path or URL. Never copy their content.

Aim for 1–3k tokens. Redact secrets and personal data. If the user passed arguments, tailor the note to what they say the next session is for.

## 3. Open the next session

Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/open-session.sh" "<absolute note path>"`. Then tell the user in one line that the new tab is open with the note and this tab can be closed. If the script printed a prompt to paste instead, give them that prompt.
