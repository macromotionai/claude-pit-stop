"""Counts every token a run spent, two independent ways, and compares arms.

  python3 measure.py results/<run>.json [results/<run2>.json ...]

Source 1, transcripts: every usage record in every session of the run (main chain and
subagents), deduplicated on (message.id, requestId) because one API response is written
as several records. Source 2: the per-call totals claude -p returned (modelUsage).
"""
import glob, json, os, sys

HOME = os.path.expanduser('~')
CLASSES = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')


def files_for(sid):
    root = os.path.join(HOME, '.claude/projects')
    return glob.glob(os.path.join(root, '*', sid + '.jsonl')) + glob.glob(os.path.join(root, '*', sid, '**', '*.jsonl'), recursive=True)


def from_transcripts(sessions):
    seen, tot, main_ctx, side, compactions = set(), dict.fromkeys(CLASSES, 0), [], 0, 0
    for sid in sessions:
        for f in files_for(sid):
            for line in open(f, errors='ignore'):
                if 'compact_boundary' in line:
                    compactions += 1
                if '"usage"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                m = r.get('message') or {}
                key = (m.get('id'), r.get('requestId'))
                if r.get('type') != 'assistant' or not m.get('id') or key in seen or m.get('model') == '<synthetic>':
                    continue
                seen.add(key); u = m.get('usage') or {}
                for c in CLASSES:
                    tot[c] += u.get(c, 0)
                n = sum(u.get(c, 0) for c in CLASSES)
                if r.get('isSidechain') or '/subagents/' in f:
                    side += n
                else:
                    main_ctx.append(n - u.get('output_tokens', 0))
    return dict(total=sum(tot.values()), **tot, api_calls=len(seen), subagent_tokens=side,
                peak_ctx=max(main_ctx or [0]), mean_ctx=round(sum(main_ctx) / max(1, len(main_ctx))), compactions=compactions)


def from_calls(calls, labels=None):
    tot, cost = 0, 0.0
    for c in calls:
        if labels and c['label'] not in labels:
            continue
        cost += c.get('total_cost_usd') or 0
        for mu in (c.get('modelUsage') or {}).values():
            tot += sum(mu.get(k, 0) for k in ('inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens'))
    return tot, cost


def main():
    rows = []
    for path in sys.argv[1:]:
        run = json.load(open(path))
        t = from_transcripts(run['sessions'])
        calls_tot, cost = from_calls(run['calls'])
        over_tot, over_cost = from_calls(run['calls'], {'handoff', 'continue'})
        rows.append(dict(name=run['name'], arm=run['arm'], tests=run['tests'], sessions=len(run['sessions']),
                         handoffs=len(run['handoffs']), wall_min=round(run['wall_secs'] / 60),
                         transcript_total=t['total'], cli_total=calls_tot,
                         agree=f"{abs(t['total'] - calls_tot) / max(1, calls_tot):.2%} apart",
                         cost_usd=round(cost, 2), handoff_overhead_tokens=over_tot, handoff_overhead_usd=round(over_cost, 2),
                         **{k: v for k, v in t.items() if k != 'total'}))
    print(json.dumps(rows, indent=1))
    if len(rows) == 2:
        c, h = sorted(rows, key=lambda r: r['arm'] != 'control')
        print(f"\ncontrol {c['transcript_total']/1e6:.2f}M tokens ${c['cost_usd']}, handoff {h['transcript_total']/1e6:.2f}M tokens ${h['cost_usd']}"
              f" -> handoff arm spent {1 - h['transcript_total']/c['transcript_total']:.0%} fewer tokens, {1 - h['cost_usd']/max(c['cost_usd'], 1e-9):.0%} less $ (overhead included)")


if __name__ == '__main__':
    main()
