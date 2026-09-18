"""Generates the fixed test task: big legacy modules, one planted bug each, one test per step.

Deterministic (seeded), so every run gets byte-identical files. Output: task/build/.
Each module is large on purpose: the step prompt asks Claude to read it in full, which
is what makes context climb past the 250k handoff point in a modest number of calls.
"""
import os, random, shutil

STEPS = 13
FUNCS = 130
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'task', 'build')
ZONES = ['north', 'south', 'east', 'west', 'central', 'coastal', 'inland', 'metro', 'rural', 'island']
KINDS = ['freight', 'parcel', 'pallet', 'courier', 'bulk', 'express', 'return', 'cold', 'hazard', 'oversize']


def func(n, i, rng, bug):
    zone, kind = rng.choice(ZONES), rng.choice(KINDS)
    r = round(rng.uniform(1.01, 1.99), 3)
    c = round(rng.uniform(0.5, 9.5), 2)
    cap = rng.randint(200, 900)
    code_c = round(c + 1.25, 2) if bug else c
    name = f'{kind}_{zone}_rate_{n:02d}_{i:03d}'
    return name, r, c, cap, f'''

def {name}(amount):
    """Charge for a {kind} consignment in the {zone} zone (tariff sheet {n:02d}, line {i:03d}).

    Spec: multiply amount by {r}, add a flat fee of {c}, cap the result at {cap},
    and round to 2 decimal places. Negative amounts are treated as zero.
    """
    amount = max(0.0, float(amount))
    rate = {r}
    fee = {code_c}
    total = amount * rate + fee
    return round(min(total, {cap}), 2)
'''


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, 'legacy'))
    os.makedirs(os.path.join(OUT, 'tests'))
    for n in range(1, STEPS + 1):
        rng = random.Random(1000 + n)
        bug_at = rng.randrange(FUNCS // 3, FUNCS)
        parts = [f'"""Tariff sheet {n:02d}: consignment charges by kind and zone. Legacy, hand-maintained."""\n']
        for i in range(FUNCS):
            name, r, c, cap, src = func(n, i, rng, i == bug_at)
            parts.append(src)
            if i == bug_at:
                target = (name, r, c, cap)
        open(os.path.join(OUT, 'legacy', f'mod_{n:02d}.py'), 'w').write(''.join(parts))
        name, r, c, cap = target
        want = round(min(100 * r + c, cap), 2)
        extra = ''
        if n == STEPS:
            extra = f'''

def test_changelog_complete():
    lines = [l.strip() for l in open('CHANGELOG.md') if l.strip()]
    assert [l.split(':')[0] for l in lines] == [f'step {{k:02d}}' for k in range(1, {STEPS + 1})], lines
'''
        open(os.path.join(OUT, 'tests', f'test_{n:02d}.py'), 'w').write(f'''from legacy.mod_{n:02d} import {name}


def test_{name}():
    assert {name}(100) == {want}
    assert {name}(-5) == {round(min(c, cap), 2)}
{extra}''')
    open(os.path.join(OUT, 'legacy', '__init__.py'), 'w').write('')
    open(os.path.join(OUT, 'run_tests.py'), 'w').write('''"""Runs every test_* function in tests/. Prints 'N passed, M failed'."""
import glob, importlib.util, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = bad = 0
for path in sorted(glob.glob('tests/test_*.py')):
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        bad += 1; print('ERROR', path); traceback.print_exc(limit=1); continue
    for name in dir(mod):
        if name.startswith('test_'):
            try:
                getattr(mod, name)(); ok += 1
            except Exception as e:
                bad += 1; print('FAIL', path, name, repr(e)[:200])
print(f'{ok} passed, {bad} failed')
''')
    open(os.path.join(OUT, 'CHANGELOG.md'), 'w').write('')


if __name__ == '__main__':
    main()
