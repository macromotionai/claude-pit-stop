# Claude Context Status

A VS Code status bar item showing how much context each Claude Code session in this window carries, for example `✦ 232k · 119k`. It turns orange at the context-handoff plugin's warning point and red when a session reaches its handoff offer. Clicking it lets you pick a session, brings that tab forward and puts the handoff command on your clipboard: paste, then press Enter.

It needs the [context-handoff](https://github.com/macromotionai/claude-context-handoff) Claude Code plugin for the colours and the handoff; without it the numbers still show.
