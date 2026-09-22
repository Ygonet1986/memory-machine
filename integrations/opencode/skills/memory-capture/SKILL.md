---
name: memory-capture
description: Populate this session's memory tape. Use when the user asks to "save", "capture", "remember", "popular a fita", or "gravar" what was decided or learned in this session.
---

# Capture session memory

Write this session's durable facts to its memory tape (the `memory_*` tools).
Each opencode session has its own numbered tape.

## Process

1. **See what's already there** — call `memory_list` first so you don't duplicate.
2. **Scan the conversation** for durable, reusable facts:
   - `decision` — a choice made and why (approach, tool, architecture)
   - `lesson` — a pitfall/gotcha and the fix
   - `preference` — a convention, style or personal preference
   - `bugfix` — a root cause and its fix
   - `build` — setup steps, commands, environment notes
3. **Write each fact** with `memory_remember`:
   - `--summary`: one self-contained sentence (a future session must understand it without this conversation)
   - `--type`: decision | lesson | preference | bugfix | build
   - `--why`: the reasoning/context behind it
4. **Skip** anything trivial, already recorded, or only relevant to this exact turn.

## Bulk capture

If the user asks to "save everything", call `memory_checkpoint` once:
- `question`: the current task/message
- `summary`: a short summary of what was done
- `memories`: a JSON list of the durable facts, e.g.
  `[{"type":"decision","summary":"Use X","why":"because Y"}]`

## Rules

- Never store secrets or credentials.
- Prefer specific summaries; update existing memories instead of duplicating.
- Code wins over memory — if the code contradicts a memory, fix the memory.
