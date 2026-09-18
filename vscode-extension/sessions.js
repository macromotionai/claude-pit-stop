// Reads Claude Code's process registry and transcripts to find the sessions open in a window.
// No VS Code dependency, so it can be tested with plain node.
// ~/.claude/sessions/<pid>.json exists for every running Claude process (one per open tab)
// and names its sessionId. Each tab's process is a child of its window's extension host,
// so a window's sessions are the registered processes whose parent is that host's pid.
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const REGISTRY = path.join(os.homedir(), '.claude/sessions');
const PROJECTS = path.join(os.homedir(), '.claude/projects');
const STATE = path.join(os.homedir(), '.claude/state/context-watch');
const RED = 250000; // context-watch's default offer point
const WARN = 180000; // and its default warning point
const NEVER = 1e12; // context-watch marks a handed-off session with this
const TAIL_BYTES = 2000000;
const titles = new Map();
const parents = new Map(); // pid -> parent pid; a process never changes parent
const transcripts = new Map(); // session id -> transcript path
const contexts = new Map(); // transcript path -> { size, context }

function readSlice(file, start, length) {
  const fd = fs.openSync(file, 'r');
  try {
    const buf = Buffer.alloc(length);
    fs.readSync(fd, buf, 0, length, start);
    return buf.toString('utf8').split('\n');
  } finally {
    fs.closeSync(fd);
  }
}

function contextOf(file, size) {
  const cached = contexts.get(file);
  if (cached && cached.size === size) return cached.context;
  let context = 0;
  const length = Math.min(size, TAIL_BYTES);
  const lines = readSlice(file, size - length, length);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].includes('"usage"')) continue;
    let r;
    try { r = JSON.parse(lines[i]); } catch { continue; }
    const u = r.type === 'assistant' && !r.isSidechain && r.message && r.message.usage;
    if (u) {
      context = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
        + (u.cache_creation_input_tokens || 0) + (u.output_tokens || 0);
      break;
    }
  }
  contexts.set(file, { size, context });
  return context;
}

function titleOf(file, size) {
  if (titles.has(file)) return titles.get(file);
  let title = '';
  for (const line of readSlice(file, 0, Math.min(size, 300000))) {
    if (!line.includes('"type":"user"')) continue;
    let r;
    try { r = JSON.parse(line); } catch { continue; }
    const c = r.message && r.message.content;
    const text = typeof c === 'string' ? c : Array.isArray(c) ? (c.find(b => b && b.type === 'text') || {}).text : '';
    if (text && !text.startsWith('<') && !text.startsWith('Base directory for this skill')) { // skip slash-command expansions
      const note = text.match(/^Continue from the handoff note at \S*\/([^/\s]+)\.md/); // every handoff tab opens with this
      title = (note ? 'handoff: ' + note[1] : text.replace(/\s+/g, ' ')).slice(0, 60);
      break;
    }
  }
  if (title) titles.set(file, title);
  return title;
}

function offerPoints(id) {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(STATE, id + '.json'), 'utf8'));
    return { next: s.next_red || RED, warn: s.warn_at || WARN };
  } catch { return { next: RED, warn: WARN }; }
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

function parentsOf(pids) {
  const unknown = pids.filter(p => !parents.has(p));
  if (unknown.length) {
    try {
      const out = execFileSync('ps', ['-o', 'pid=,ppid=', '-p', unknown.join(',')], { encoding: 'utf8' });
      for (const line of out.trim().split('\n')) {
        const [pid, ppid] = line.trim().split(/\s+/).map(Number);
        if (pid) parents.set(pid, ppid);
      }
    } catch { /* ps exits 1 when a pid has already gone */ }
  }
  return pids.map(p => parents.get(p));
}

function transcriptOf(id) {
  if (!transcripts.has(id)) {
    for (const dir of fs.readdirSync(PROJECTS)) {
      const file = path.join(PROJECTS, dir, id + '.jsonl');
      if (fs.existsSync(file)) { transcripts.set(id, file); break; }
    }
  }
  return transcripts.get(id); // undefined until a brand-new tab writes its first message
}

// Sessions with a tab open under extension host `hostPid`, not handed off, oldest tab first.
function sessionsFor(hostPid) {
  let entries;
  try { entries = fs.readdirSync(REGISTRY).filter(n => n.endsWith('.json')); } catch { return []; }
  const procs = [];
  for (const name of entries) {
    try {
      const p = JSON.parse(fs.readFileSync(path.join(REGISTRY, name), 'utf8'));
      if (p.sessionId && alive(p.pid)) procs.push(p);
    } catch { /* being rewritten; skip this tick */ }
  }
  const ppids = parentsOf(procs.map(p => p.pid));
  const out = [];
  procs.forEach((p, i) => {
    if (ppids[i] !== hostPid) return;
    const { next, warn } = offerPoints(p.sessionId);
    if (next >= NEVER) return;
    const file = transcriptOf(p.sessionId);
    let context = 0, updated = p.startedAt, title = '';
    if (file) {
      try {
        const stat = fs.statSync(file);
        context = contextOf(file, stat.size);
        updated = stat.mtimeMs;
        title = titleOf(file, stat.size);
      } catch { /* being rewritten; show what we have */ }
    }
    out.push({ id: p.sessionId, context, nextOffer: next, warnAt: warn, updated, started: p.startedAt, title });
  });
  return out.sort((a, b) => a.started - b.started);
}

module.exports = { sessionsFor, REGISTRY };
