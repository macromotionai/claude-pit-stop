#!/usr/bin/env python3
"""context-watch: offer a handoff to a fresh session before a Claude Code session gets expensive.

Every message re-sends the whole conversation, so the cost of each message climbs with
context. This watches the context size and, once it passes a threshold, asks whether to hand
off to a fresh session (the handoff skill writes a note, the new session starts from it).

Runs as two hooks (see ../hooks/hooks.json):
  UserPromptSubmit (no args): a one-line heads-up at WARN, notes a return after an idle break,
      and nudges CHECKLIST.md once several files changed since it was last updated.
  Stop (--stop): when a reply ends at OFFER or above (or after an idle break at IDLE_CONTEXT
      or above), tells Claude to ask "hand off or keep going" as a question box. The reply has
      already ended, so this is the break; Claude is told not to judge whether the moment is
      right, because letting it judge meant it skipped offers. Only running background work
      defers it. It re-offers at each reply end until answered.
Run by Claude: --snooze ("keep going": next offer SNOOZE tokens later); --handed-off <note>
(from open-session.sh: acts like a snooze until the new session starts with that note in its
prompt, then no more offers. A cancelled or failed tab leaves the old session offering).

Settings are environment variables; set them in the "env" block of ~/.claude/settings.json.
Defaults suit a 1M-token context window. For a 200k window, try WARN 110000, OFFER 140000.
  CONTEXT_WATCH_WARN          heads-up line           (default 180000)
  CONTEXT_WATCH_OFFER         first handoff offer     (default 250000)
  CONTEXT_WATCH_SNOOZE        "keep going" adds this  (default 75000)
  CONTEXT_WATCH_IDLE_MINUTES  break length            (default 60)
  CONTEXT_WATCH_IDLE_CONTEXT  offer after a break from this size (default 150000)
  CONTEXT_WATCH_CHECKLIST_FILES  edited files before the checklist nudge (default 5)
  CONTEXT_WATCH_SKIP_DIRS     colon-separated folders where it stays silent (unattended runs)

Reads the session transcript (JSONL). That format is internal to Claude Code and may change
in any release; if it does, this exits quietly and offers nothing.
Never blocks the user: any failure exits 0 with no output.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


WARN = env_int('CONTEXT_WATCH_WARN', 180_000)
OFFER_AT = env_int('CONTEXT_WATCH_OFFER', 250_000)
SNOOZE = env_int('CONTEXT_WATCH_SNOOZE', 75_000)
IDLE_MINUTES = env_int('CONTEXT_WATCH_IDLE_MINUTES', 60)
IDLE_CONTEXT = env_int('CONTEXT_WATCH_IDLE_CONTEXT', 150_000)
CHECKLIST_EDIT_FILES = env_int('CONTEXT_WATCH_CHECKLIST_FILES', 5)
SKIP_DIRS = [os.path.expanduser(d) for d in os.environ.get('CONTEXT_WATCH_SKIP_DIRS', '').split(':') if d]
TAIL_BYTES = 4_000_000
NEVER = 10 ** 12
HOME = os.path.expanduser('~')
SELF = os.path.abspath(__file__)
PLUGIN_ROOT = os.path.dirname(os.path.dirname(SELF))
STATE_DIR = os.path.join(HOME, '.claude/state/context-watch')  # also read by the VS Code status bar
HANDOFFS = os.path.join(HOME, '.claude/handoffs')
TEMPLATE = os.path.join(PLUGIN_ROOT, 'skills/handoff/CHECKLIST-TEMPLATE.md')
EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
HEADER = 'CONTEXT WATCH (from a hook, not the user).'

OFFER = HEADER + """ {reason} {checklist}.
Your reply has ended, so this is the break. Show the offer now, every time. Do not judge whether the phase is finished or whether you are waiting on the user: the user wants this question each time, and the handoff note carries any open question or unfinished step into the new session.
The one exception: if agents or background commands you started are still running, reply with exactly this one line and nothing else: "Context {k}k. Handoff offer once the background work finishes." This comes back when you next finish.
Otherwise call AskUserQuestion as the only thing you do: header "Context {k}k", question "{reason} Hand off to a fresh session?", options:
1. label "Hand off + new session (Recommended)", description "Update CHECKLIST.md, write a handoff note, and open a fresh tab that continues from it."
2. label "Keep going here", description "Stay in this session. I'll ask again at {next_k}k."
If they pick hand off, use the pit-stop:handoff skill. If they pick keep going, run `python3 "{self}" --snooze` and say nothing more about it."""

AMBER_LINE = HEADER + """ Start your reply with exactly this line, then continue normally:
"🟠 Context {k}k. I'll offer a handoff at the first natural break after {red_k}k.\""""

CHECKLIST_STALE = HEADER + """ {n} files edited since {path} was last updated. Before this reply ends, tick the steps you verified (evidence on each tick) and add anything new, in one short edit, and say so in one line."""

CHECKLIST_MISSING = HEADER + """ {n} files edited this session and {root} has no CHECKLIST.md. If this is a multi-step build, create one from {template} before this reply ends and say so in one line. If it isn't, ignore this."""


def tail_records(path):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().split(b'\n')
    if size > TAIL_BYTES:
        lines = lines[1:]  # the first line is cut mid-record
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            pass
    return records


def epoch(record):
    ts = record.get('timestamp')
    return dt.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp() if ts else 0


def session_context(records):
    """Context size of the latest main-chain reply, and that reply's record."""
    last = next((r for r in reversed(records)
                 if r.get('type') == 'assistant' and not r.get('isSidechain')
                 and (r.get('message') or {}).get('usage')), None)
    if last is None:
        return 0, None
    usage = last['message']['usage']
    return sum(usage.get(key, 0) for key in (
        'input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')), last


def checklist_info(cwd):
    root = cwd
    try:
        out = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=3)
        top = out.stdout.strip()
        if out.returncode == 0 and top and top not in (HOME, '/'):
            root = top
    except (OSError, subprocess.SubprocessError):
        pass
    path = os.path.join(root, 'CHECKLIST.md')
    return root, path, (os.path.getmtime(path) if os.path.exists(path) else 0)


def checklist_age(mtime):
    if not mtime:
        return 'No CHECKLIST.md in this project yet'
    minutes = (time.time() - mtime) / 60
    return (f'CHECKLIST.md last updated {minutes:.0f} min ago' if minutes < 90
            else f'CHECKLIST.md last updated {minutes / 60:.0f}h ago')


def load_state(session):
    try:
        with open(os.path.join(STATE_DIR, session + '.json')) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'amber': False, 'next_red': OFFER_AT, 'checklist_mtime': None}


def save_state(session, state):
    state['warn_at'] = WARN  # the VS Code status bar turns orange from here
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, session + '.json'), 'w') as f:
        json.dump(state, f)


def set_next_offer(note=None):
    session = os.environ.get('CLAUDE_CODE_SESSION_ID')
    if not session:
        return
    state = load_state(session)
    state.pop('idle_return', None)
    state['amber'] = True
    state['next_red'] = state.get('last_context', OFFER_AT) + SNOOZE
    if note:
        state['pending_note'] = note  # offers stop for good once the new session starts
    save_state(session, state)
    if not note:
        print(f"Snoozed until {round(state['next_red'] / 1000)}k.")


def confirm_handoff(prompt):
    """A session that opens with a handoff note ends offers in the session that wrote it."""
    # Matches the note path in full or in its ~ form, since users sometimes paste the
    # old tab's closing line instead of letting the new tab open by itself.
    if '.claude/handoffs/' not in prompt or not os.path.isdir(STATE_DIR):
        return
    for name in os.listdir(STATE_DIR):
        session = name[:-len('.json')]
        state = load_state(session)
        note = state.get('pending_note')
        if note and (note in prompt or note.replace(HOME, '~', 1) in prompt):
            del state['pending_note']
            state['next_red'] = NEVER
            save_state(session, state)


def on_prompt(data, session, records):
    context, last = session_context(records)
    if last is None:
        return
    away = (time.time() - epoch(last)) / 60
    state = load_state(session)
    root, checklist, mtime = checklist_info(data.get('cwd') or os.getcwd())
    notes = []

    if away >= IDLE_MINUTES and context >= IDLE_CONTEXT:
        state['idle_return'] = True  # offered when this reply finishes
    elif WARN <= context < state['next_red'] and not state['amber']:
        state['amber'] = True
        notes.append(AMBER_LINE.format(k=round(context / 1000), red_k=round(state['next_red'] / 1000)))

    edited = set()
    for r in records:
        if r.get('type') != 'assistant' or r.get('isSidechain') or epoch(r) <= mtime:
            continue
        for block in (r.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') in EDIT_TOOLS:
                args = block.get('input') or {}
                path = args.get('file_path') or args.get('notebook_path')
                if path and not path.endswith('CHECKLIST.md') and not path.startswith(HANDOFFS):
                    edited.add(path)
    if len(edited) >= CHECKLIST_EDIT_FILES and state.get('checklist_mtime') != mtime:
        state['checklist_mtime'] = mtime
        notes.append(CHECKLIST_STALE.format(n=len(edited), path=checklist) if mtime
                     else CHECKLIST_MISSING.format(n=len(edited), root=root, template=TEMPLATE))

    state['last_context'] = context
    save_state(session, state)
    if notes:
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit', 'additionalContext': '\n\n'.join(notes)}}))


def on_stop(data, session, records):
    if data.get('stop_hook_active'):
        return  # Claude already had its chance this turn; let it stop
    context, last = session_context(records)
    if last is None:
        return
    state = load_state(session)
    k = round(context / 1000)
    reason = None
    if context >= state['next_red']:
        reason = f'Context is at {k}k, and every message re-reads all of it.'
    elif state.get('idle_return') and context >= IDLE_CONTEXT:
        reason = f'You came back after a break to {k}k of context, a natural point to switch.'
    state['last_context'] = context
    save_state(session, state)
    if reason:
        _, _, mtime = checklist_info(data.get('cwd') or os.getcwd())
        print(json.dumps({'decision': 'block', 'reason': OFFER.format(
            reason=reason, checklist=checklist_age(mtime), k=k, next_k=round((context + SNOOZE) / 1000), self=SELF)}))


def main():
    if '--snooze' in sys.argv:
        return set_next_offer()
    if '--handed-off' in sys.argv:
        return set_next_offer(note=sys.argv[-1] if sys.argv[-1] != '--handed-off' else None)
    if os.environ.get('CLAUDE_CODE_ENTRYPOINT') == 'sdk-cli':
        return  # headless runs (claude -p): nobody is there to answer a question box
    data = json.load(sys.stdin)
    cwd = data.get('cwd') or os.getcwd()
    if any(cwd == d or cwd.startswith(d.rstrip(os.sep) + os.sep) for d in SKIP_DIRS):
        return
    if '--stop' not in sys.argv:
        confirm_handoff(data.get('prompt') or '')
    session, transcript = data.get('session_id'), data.get('transcript_path')
    if not session or not transcript or not os.path.exists(transcript):
        return
    records = tail_records(transcript)
    (on_stop if '--stop' in sys.argv else on_prompt)(data, session, records)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
