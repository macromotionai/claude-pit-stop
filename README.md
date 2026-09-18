# Pit Stop (context saver) for Claude Code

Long Claude Code sessions get expensive in a way that is easy to miss: every message re-sends the whole conversation. At 400k tokens of context, a one-line question still re-reads 400k tokens. This plugin watches the context size and, once it passes a threshold, asks whether to hand off. If you say yes, Claude writes a short note of where things stand and opens a fresh session that picks up from that note.

## Does it work?

We ran the same 13-step build twice with the same scripted prompts, model and settings. One run stayed in one session. The other handed off at 250k. Both finished with every test passing.

| | Without handoff | With handoff |
|---|---|---|
| Total tokens | 13.74M | 9.35M |
| Cost at list price | $11.33 | $9.72 |
| Peak context | 457k | 272k |
| Cost of the handoff itself | none | 1.31M tokens, $1.23 |

The handoff run used **32% fewer tokens and 14% less money, with the handoff's own cost included.** The saving grows with every message after the handoff, so longer sessions save more. The method, per-step numbers and caveats are in [experiment/RESULTS.md](experiment/RESULTS.md), and the harness is there to re-run it yourself.

Money falls less than tokens because the fresh session has to be written into the prompt cache once, and a cache write costs far more per token than a cache read.

## In real use

Over the plugin's first three days in daily use (2026-09-15 to 17), compared with the week before:

| | Before | With the plugin |
|---|---|---|
| Average conversation size per message | 350k | 184k |
| Share of all reading done past 300k | 75% | 21% |
| Cost per message at list price | $0.274 | $0.176 |

There were 18 handoffs in those three days. The biggest took a 521k session down to 77k. The re-reading avoided adds up to about $111, or 20% of those days' cost, before subtracting what the handoffs cost. The two periods covered different projects and workloads, which is why the controlled test above was run.

## How it works

1. **Watch.** Two hooks read the session's size after every message. At 180k you get a one-line heads-up.
2. **Offer.** When a reply ends at 250k or more, Claude asks, as a question box: hand off, or keep going. "Keep going" snoozes it for another 75k. Returning after an hour away with a big session also triggers an offer.
3. **Hand off.** The `handoff` skill updates the project's `CHECKLIST.md`, writes a note to `~/.claude/handoffs/<project>/`, and opens a new session with one prompt: continue from the note. The old session stops offering once the new one starts.
4. **See it.** An optional VS Code status bar item shows every open session's context size and lets you trigger a handoff by clicking it.

The note carries what a checklist can't: the pending request word for word, where the current step stands, dead ends, decisions and gotchas. It is kept outside the project on purpose, because some repos are shared and the note holds private working context.

## Install

In Claude Code:

```
/plugin marketplace add macromotionai/claude-pit-stop
/plugin install pit-stop@pit-stop
```

Restart Claude Code. That is all the plugin needs. Python 3 must be on your PATH.

**Optional, the VS Code status bar.** Requires Node.js.

```
cd vscode-extension
npx @vscode/vsce package
code --install-extension claude-context-status-1.0.0.vsix
```

Or, in VS Code, run "Extensions: Install from VSIX..." and pick the file. Reload the window.

**Optional, a line for your `CLAUDE.md`.** It helps Claude keep the checklist current between handoffs:

```
- Multi-step builds keep a CHECKLIST.md at the project root, ticked only with evidence.
  The handoff note holds only what the checklist can't. A handoff beats /compact.
```

## Settings

Set these in the `env` block of `~/.claude/settings.json`. The defaults suit a 1M-token context window.

| Variable | Default | What it does |
|---|---|---|
| `CONTEXT_WATCH_WARN` | 180000 | One-line heads-up |
| `CONTEXT_WATCH_OFFER` | 250000 | First handoff offer |
| `CONTEXT_WATCH_SNOOZE` | 75000 | "Keep going" moves the next offer this far |
| `CONTEXT_WATCH_IDLE_MINUTES` | 60 | A break this long counts as coming back |
| `CONTEXT_WATCH_IDLE_CONTEXT` | 150000 | Offer after a break if the session is at least this big |
| `CONTEXT_WATCH_CHECKLIST_FILES` | 5 | Edited files before a reminder to update `CHECKLIST.md` |
| `CONTEXT_WATCH_SKIP_DIRS` | none | Colon-separated folders where it stays silent, for unattended runs |

With a 200k context window, auto-compaction arrives before 250k, so lower the thresholds. Around 110000 and 140000 is a reasonable start.

## What to know

- **Tested on macOS** with the Claude Code VS Code extension and CLI v2.1.276. On macOS in VS Code the new session opens by itself. Everywhere else, including the terminal, Claude gives you the one-line prompt to paste into a new session.
- **It reads the session transcript files** in `~/.claude/projects/`. Anthropic documents that format as internal, so an update could change it. If that happens the hooks exit quietly and offer nothing; they never block you.
- **The status bar** reads Claude Code's process registry in `~/.claude/sessions/` and uses an internal command of the Claude Code extension to bring a tab forward. Both are undocumented and could break on an update.
- **Headless runs** (`claude -p`) never get an offer, because nobody is there to answer it.
- State lives in `~/.claude/state/context-watch/`, one small file per session. Notes live in `~/.claude/handoffs/`. Nothing leaves your machine.

## Tests

```
python3 tests/test_context_watch.py
```

25 scenarios, run against a temporary home folder so your real state is untouched.

## Uninstall

```
/plugin uninstall pit-stop@pit-stop
```

Then delete `~/.claude/state/context-watch/` and, if you want, `~/.claude/handoffs/`.

## License

MIT
