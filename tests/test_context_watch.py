"""Scenario tests for plugin/scripts/context-watch.py. Run: python3 tests/test_context_watch.py

Each scenario feeds the hook a fake transcript and checks what it prints: an offer (Stop
hook blocks with the question), a line (UserPromptSubmit adds context), or nothing.
HOME points at a temporary folder, so your real ~/.claude state is never touched.
"""
import datetime as dt, json, os, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'plugin', 'scripts', 'context-watch.py')
HOME = tempfile.mkdtemp()
PROJ = os.path.join(HOME, 'proj'); os.makedirs(PROJ)
failures = 0


def rec(ctx, mins_ago=0, edits=()):
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=mins_ago)).isoformat().replace('+00:00', 'Z')
    content = [{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': p}} for p in edits] or [{'type': 'text', 'text': 'hi'}]
    return {'type': 'assistant', 'timestamp': ts, 'message': {'id': 'm', 'content': content,
            'usage': {'input_tokens': 2, 'cache_read_input_tokens': ctx - 2, 'cache_creation_input_tokens': 0, 'output_tokens': 0}}}


def env(**extra):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE_CODE_', 'CONTEXT_WATCH_'))}
    e.update(HOME=HOME, **extra)
    return e


def hook(name, want, sid, recs, stop=False, active=False, entry='claude-vscode', prompt='hi', **extra_env):
    global failures
    t = os.path.join(HOME, sid + '.jsonl')
    open(t, 'w').write('\n'.join(json.dumps(r) for r in recs) + '\n')
    payload = {'session_id': sid, 'transcript_path': t, 'cwd': PROJ, 'prompt': prompt}
    if stop:
        payload['stop_hook_active'] = active
    out = subprocess.run([sys.executable, HOOK] + (['--stop'] if stop else []), input=json.dumps(payload),
                         capture_output=True, text=True, env=env(CLAUDE_CODE_ENTRYPOINT=entry, **extra_env)).stdout.strip()
    got = 'nothing' if not out else ('offer' if json.loads(out).get('decision') == 'block' else 'line')
    ok = got == want
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name:55} want {want:7} got {got}")


def cmd(flag, sid, *extra):
    out = subprocess.run([sys.executable, HOOK, flag, *extra], capture_output=True, text=True,
                         env=env(CLAUDE_CODE_SESSION_ID=sid)).stdout.strip()
    print(f"     (Claude runs {flag}) {out or 'ok'}")


hook('prompt at 120k', 'nothing', 'a', [rec(120_000)])
hook('reply ends at 120k', 'nothing', 'a', [rec(120_000)], stop=True)
hook('prompt at 190k: heads-up', 'line', 'b', [rec(190_000)])
hook('prompt at 200k: heads-up only once', 'nothing', 'b', [rec(200_000)])
hook('prompt at 230k', 'line', 'c', [rec(230_000)])
hook('reply ends at 280k: offer', 'offer', 'c', [rec(280_000)], stop=True)
hook('same turn, already offered: let it stop', 'nothing', 'c', [rec(281_000)], stop=True, active=True)
hook('next reply ends at 290k, unanswered: offer again', 'offer', 'c', [rec(290_000)], stop=True)
cmd('--snooze', 'c')
hook('reply ends at 320k (snoozed to 365k)', 'nothing', 'c', [rec(320_000)], stop=True)
hook('reply ends at 370k: offer', 'offer', 'c', [rec(370_000)], stop=True)
NOTE = os.path.join(HOME, '.claude/handoffs/proj/2026-01-01-0000-note.md')
cmd('--handed-off', 'c', NOTE)
hook('old tab at 380k, new tab not started yet', 'nothing', 'c', [rec(380_000)], stop=True)
hook('old tab at 450k, new tab never started: offer', 'offer', 'c', [rec(450_000)], stop=True)
hook('unrelated new session', 'nothing', 'h', [], prompt='fix the button')
hook('new session starts with the note', 'nothing', 'i', [], prompt=f'Continue from the handoff note at {NOTE}. Read it')
hook('old tab at 900k after new session started', 'nothing', 'c', [rec(900_000)], stop=True)
hook('prompt at 170k after 2h away', 'nothing', 'd', [rec(170_000, mins_ago=120)])
hook('that reply ends at 175k: break offer', 'offer', 'd', [rec(175_000)], stop=True)
hook('headless run (claude -p) at 900k', 'nothing', 'e', [rec(900_000)], stop=True, entry='sdk-cli')
hook('skipped folder at 900k', 'nothing', 'j', [rec(900_000)], stop=True, CONTEXT_WATCH_SKIP_DIRS=PROJ)
hook('custom offer point 140k, reply ends at 150k', 'offer', 'k', [rec(150_000)], stop=True, CONTEXT_WATCH_OFFER='140000')
hook('5 files edited, no checklist: nudge', 'line', 'f', [rec(50_000, edits=[f'/x/f{i}.py' for i in range(5)])])
open(os.path.join(PROJ, 'CHECKLIST.md'), 'w').write('# c\n'); time.sleep(1)
hook('edits made before the checklist existed', 'nothing', 'g', [rec(50_000, mins_ago=5, edits=[f'/x/f{i}.py' for i in range(5)])])
hook('5 edits after the checklist: nudge', 'line', 'g', [rec(50_000, edits=[f'/x/g{i}.py' for i in range(5)])])
state = json.load(open(os.path.join(HOME, '.claude/state/context-watch/c.json')))
ok = state.get('warn_at') == 180000 and state.get('next_red') == 10 ** 12
failures += not ok
print(f"{'ok  ' if ok else 'FAIL'} state file carries warn_at and the handed-off marker")
print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
