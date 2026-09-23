# Memory Machine — OpenCode integration

Gives the [opencode](https://opencode.ai) coding agent a per-session memory:
before every user message the plugin runs `memory-cli recall` for the session
root and injects the result as a synthetic `## Session memory (recalled)`
part; after the turn the agent can use the memory tools.

## Files

| File | Purpose |
|---|---|
| `plugins/memory.ts` | The plugin (recall hook + memory tools). |
| `AGENTS.md` | The memory protocol the assistant follows. |
| `skills/memory/SKILL.md` | Skill: recall/persist session memory. |
| `skills/memory-capture/SKILL.md` | Skill: populate the tape. |
| `agent/memory.md` | Subagent for memory synthesis. |

## Install

1. Install the package first (the plugin shells out to `memory-cli`):

   ```bash
   pipx install memory-machine     # or: pip install memory-machine
   ```

2. Install the integration (backs up existing files):

   ```bash
   ./integrations/opencode/install.sh
   ```

3. Restart opencode (plugins/config load at startup).

To remove it and restore the previous files:

```bash
./integrations/opencode/uninstall.sh
```

## Configuration

- Destination: `~/.config/opencode` by default; override with
  `OPENCODE_CONFIG=/path/to/config`.
- The plugin calls `memory-cli`; make sure it is on `PATH` (pipx installs it
  into `~/.local/bin`).
- The tape lives under `~/.config/opencode/memory/sessions/<id>/`; the plugin
  rejects `/` worktrees and falls back to the session directory.
- **Turn slots (opt-in, off by default).** With
  `MEMORY_MACHINE_TURN_SLOTS=1` the plugin records both sides of every turn
  on the tape: an `ask` record for the user message and a `reply` record for
  the assistant's answer, deduped by opencode message id and paired via
  `derived_from` (`memory-cli ask` / `memory-cli reply`). Off by default: the
  default write path is unchanged and the active admission window is not
  disturbed. Restart opencode after changing the flag.

## Notes

- Restart is required for plugin changes; core CLI changes do **not** require
  a restart (the plugin spawns the CLI per message).
- Set `MEMORY_MACHINE_MOCK=1` only for smoke tests — never for real sessions.
