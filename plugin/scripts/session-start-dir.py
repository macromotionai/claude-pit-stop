"""Print the folder a Claude Code session started in, from its transcript's first cwd."""
import glob, json, os, sys

session = sys.argv[1] if len(sys.argv) > 1 else ''
for path in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{session}.jsonl')) if session else []:
    with open(path, errors='ignore') as f:
        for line in f:
            if '"cwd"' not in line:
                continue
            try:
                print(json.loads(line)['cwd'])
                sys.exit()
            except (ValueError, KeyError):
                pass
