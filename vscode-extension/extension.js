// Status bar item: how much context this window's Claude Code sessions carry.
// Colours match the context-watch hook: orange from its warning point (180k by default),
// red once a session reaches its next handoff offer (250k by default, or later after
// "keep going"). Both come from the hook's state files. Handed-off sessions drop out.
// Tabs are read from Claude's process registry, watched, so opening or closing a tab shows
// at once; a brand-new tab reads "new" until its first reply lands.
// Click it to force a handoff in one of those sessions, for when the hook's offer was
// missed or a handoff tab failed to open. The Claude extension
// refuses a prompt for a session whose tab is already open ("Your prompt was not
// applied"), and closing the tab shuts the session down, so the click brings the tab
// forward and puts /handoff on the clipboard: Cmd+V, Enter.
const vscode = require('vscode');
const fs = require('fs');
const { sessionsFor, REGISTRY } = require('./sessions');

const MAX_SHOWN = 3;
const HANDOFF_PROMPT = '/context-handoff:handoff';
const k = n => n ? `${Math.round(n / 1000)}k` : 'new';
const ago = s => `${Math.round((Date.now() - s.updated) / 60000)} min ago`;

function activate(context) {
  let sessions = [];
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  item.name = 'Claude context';
  item.command = 'claudeContextStatus.handoff';

  const update = () => {
    // The Claude tabs are children of this extension host, so its pid picks this window's.
    // Newest three if more are open; shown oldest tab first so the order doesn't jump.
    sessions = sessionsFor(process.pid).slice(-MAX_SHOWN);
    if (!sessions.length) return item.hide();
    item.text = '$(sparkle) ' + sessions.map(s => k(s.context)).join(' · ');
    const red = sessions.some(s => s.context >= s.nextOffer);
    const amber = sessions.some(s => s.context >= s.warnAt);
    item.backgroundColor = red ? new vscode.ThemeColor('statusBarItem.errorBackground')
      : amber ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    item.tooltip = new vscode.MarkdownString(sessions.map(s =>
      `**${k(s.context)}** · offer at ${k(s.nextOffer)} · ${ago(s)}  \n${s.title || s.id}`
    ).join('\n\n') + '\n\n---\nClick to hand off a session now.');
    item.show();
  };

  const handoff = async () => {
    update();
    if (!sessions.length) return vscode.window.showInformationMessage('No active Claude session in this window.');
    // Always pick, even with one session: a stray click shouldn't start a handoff.
    const pick = await vscode.window.showQuickPick(sessions.map(s => ({
      label: `$(arrow-swap) Hand off ${k(s.context)}`,
      description: s.title || s.id,
      detail: `offer at ${k(s.nextOffer)} · updated ${ago(s)}`,
      id: s.id,
    })), { placeHolder: 'Which session should hand off to a fresh one?' });
    if (!pick) return;
    await vscode.env.clipboard.writeText(HANDOFF_PROMPT);
    await vscode.commands.executeCommand('claude-vscode.primaryEditor.open', pick.id); // no prompt: reveal only
    await vscode.commands.executeCommand('claude-vscode.focus');
    vscode.window.showInformationMessage('Handoff ready: paste, then press Enter, in that Claude tab.');
  };

  update();
  let pending;
  const soon = () => { clearTimeout(pending); pending = setTimeout(update, 150); };
  let watcher;
  try { watcher = fs.watch(REGISTRY, soon); } catch { /* no registry yet; the timer still runs */ }
  const timer = setInterval(update, 2000); // context grows inside transcripts, which aren't watched
  context.subscriptions.push(item, { dispose: () => { clearInterval(timer); clearTimeout(pending); if (watcher) watcher.close(); } },
    vscode.commands.registerCommand('claudeContextStatus.handoff', handoff));
}

module.exports = { activate, deactivate() {} };
