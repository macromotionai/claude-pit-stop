"""Runs one arm of the handoff A/B test, headless, and logs every call.

  python3 make_task.py                       # once: generates task/build
  python3 driver.py control  [--steps N] [--tag T]
  python3 driver.py handoff  [--steps N] [--threshold 250000] [--tag T]
  python3 measure.py results/control-*.json results/handoff-*.json

Loads the plugin from ../plugin with --plugin-dir, so nothing needs installing. Runs
claude -p with bypassPermissions inside runs/<name>/ only; it spends real tokens.

Each step copies tests/test_NN.py into a fresh run folder and sends one fixed prompt.
Handoff arm: after each step (the moment the Stop hook would fire), if the last main-chain
reply's context >= threshold, send the handoff skill, find the note it wrote, and start a new
session with the same prompt open-session.sh uses. Context is read with the hook's own
session_context(), so the trigger rule is the plugin's, not a copy.
"""
import argparse, glob, importlib.util, json, os, shutil, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser('~')
BUILD = os.path.join(HERE, 'task', 'build')
PLUGIN = os.path.join(os.path.dirname(HERE), 'plugin')
HANDOFF_CMD = '/context-handoff:handoff'
MODEL = os.environ.get('AB_MODEL', 'claude-opus-5[1m]')  # what the published run used
EFFORT = os.environ.get('AB_EFFORT', 'medium')
HANDOFFS = os.path.join(HOME, '.claude', 'handoffs')
CONTINUE = ("Continue from the handoff note at {note}. Read it and the CHECKLIST.md it links, "
            "tell me in two lines what you're picking up, then carry on.")  # verbatim from open-session.sh
STEP = ("Step {n:02d}. tests/test_{n:02d}.py is new. Read legacy/mod_{n:02d}.py in full with the Read tool "
        "before changing anything. One function in it does not match its own docstring; the new test names it. "
        "Fix only that function. Then append the line `step {n:02d}: <function name>` to CHANGELOG.md. "
        "Finally run `python3 run_tests.py` and report the result in one line.")

spec = importlib.util.spec_from_file_location('cw', os.path.join(PLUGIN, 'scripts', 'context-watch.py'))
cw = importlib.util.module_from_spec(spec); spec.loader.exec_module(cw)


def transcript(sid):
    hits = glob.glob(os.path.join(HOME, '.claude/projects', '*', sid + '.jsonl'))
    return hits[0] if hits else None


def context(sid):
    path = transcript(sid)
    return cw.session_context(cw.tail_records(path))[0] if path else 0


def clean_env():
    # Strip the parent VS Code session's identity, or the child would think it is a VS Code tab
    # (open-session.sh would open a real tab) and refuse to nest.
    return {k: v for k, v in os.environ.items()
            if not (k.startswith('CLAUDE_CODE_') or k in ('CLAUDECODE', 'CLAUDE_PID', 'CLAUDE_EFFORT', 'CLAUDE_AGENT_SDK_VERSION'))}


def call(prompt, sid, new, rundir, log, label):
    cmd = ['claude', '-p', prompt, '--session-id' if new else '--resume', sid,
           '--model', MODEL, '--effort', EFFORT, '--output-format', 'json',
           '--permission-mode', 'bypassPermissions', '--allowedTools', 'Bash,Read,Edit,Write,Glob,Grep',
           '--plugin-dir', PLUGIN, '--add-dir', HANDOFFS,
           '--max-turns', '30', '--max-budget-usd', '8']
    t0 = time.time()
    p = subprocess.run(cmd, cwd=rundir, env=clean_env(), capture_output=True, text=True, timeout=2400)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        res = {'raw_stdout': p.stdout[-2000:]}
    row = dict(label=label, sid=sid, secs=round(time.time() - t0), rc=p.returncode, stderr=p.stderr[-1000:],
               ctx_after=context(sid), **{k: res.get(k) for k in (
                   'is_error', 'subtype', 'num_turns', 'total_cost_usd', 'usage', 'modelUsage', 'permission_denials', 'result')})
    if 'raw_stdout' in res:
        row['raw_stdout'] = res['raw_stdout']
    log.append(row)
    print(f"[{time.strftime('%H:%M:%S')}] {label:<10} sid {sid[:8]} rc {p.returncode} turns {row['num_turns']} "
          f"ctx {row['ctx_after']/1e3:.0f}k ${row['total_cost_usd'] or 0:.2f} {row['secs']}s", flush=True)
    return row


def newest_note(since):
    notes = [p for p in glob.glob(os.path.join(HANDOFFS, '**', '*.md'), recursive=True) if os.path.getmtime(p) >= since]
    return max(notes, key=os.path.getmtime) if notes else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('arm', choices=['control', 'handoff'])
    ap.add_argument('--steps', type=int, default=13)
    ap.add_argument('--threshold', type=int, default=cw.OFFER_AT)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    name = f"{a.arm}{'-' + a.tag if a.tag else ''}-{time.strftime('%Y%m%d-%H%M%S')}"
    rundir = os.path.join(HERE, 'runs', name)
    os.makedirs(os.path.join(rundir, 'tests'))
    shutil.copytree(os.path.join(BUILD, 'legacy'), os.path.join(rundir, 'legacy'))
    for f in ('run_tests.py', 'CHANGELOG.md'):
        shutil.copy(os.path.join(BUILD, f), rundir)
    assert not os.path.exists(os.path.join(rundir, 'CHECKLIST.md'))
    log, sessions, handoffs = [], [], []
    sid, new = str(uuid.uuid4()), True
    sessions.append(sid)
    t_start = time.time()
    for n in range(1, a.steps + 1):
        shutil.copy(os.path.join(BUILD, 'tests', f'test_{n:02d}.py'), os.path.join(rundir, 'tests'))
        call(STEP.format(n=n), sid, new, rundir, log, f'step{n:02d}')
        new = False
        if a.arm == 'handoff' and n < a.steps and context(sid) >= a.threshold:
            t0 = time.time()
            call(HANDOFF_CMD, sid, False, rundir, log, 'handoff')
            note = newest_note(t0)
            if not note:
                print('ABORT: the handoff wrote no note', flush=True); break
            handoffs.append(dict(after_step=n, from_sid=sid, note=note, ctx_at=log[-2]['ctx_after']))
            sid = str(uuid.uuid4()); sessions.append(sid)
            call(CONTINUE.format(note=note), sid, True, rundir, log, 'continue')
    tests = subprocess.run(['python3', 'run_tests.py'], cwd=rundir, capture_output=True, text=True).stdout.strip().splitlines()[-1]
    out = dict(arm=a.arm, name=name, rundir=rundir, model=MODEL, effort=EFFORT, threshold=a.threshold, steps=a.steps,
               sessions=sessions, handoffs=handoffs, tests=tests, wall_secs=round(time.time() - t_start), calls=log)
    os.makedirs(os.path.join(HERE, 'results'), exist_ok=True)
    path = os.path.join(HERE, 'results', name + '.json')
    json.dump(out, open(path, 'w'), indent=1)
    print(f'DONE {name}: tests "{tests}", {len(sessions)} session(s), log {path}', flush=True)


if __name__ == '__main__':
    main()
