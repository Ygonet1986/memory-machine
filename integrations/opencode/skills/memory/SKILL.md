---
name: memory
description: Recall, persist and manage the session memory (Memory Machine). Use when the user asks about memory, or to record/check what was decided.
---

# Memory Machine

Session memory: a numbered tape (`~/.config/opencode/memory/sessions/<id>/`)
with memory agents and a shared whiteboard. Each opencode session has its own
tape.

## Recall (automatic)
Memory is recalled automatically on every user message via a plugin. To inspect
it yourself:
- `memory_whiteboard` — summary (subject, understanding, checklist, annotations)
- `memory_list` — all tape records

## Persist (write memory)
After meaningful work, record it:
- `memory_remember --summary "..." --type decision|lesson|preference|bugfix|build`
- `memory_checkpoint` — records the current turn and refreshes the whiteboard's
  understanding + checklist

## Manage
- `memory_archive <id>` — stop agents from reminding about a stale memory
- `memory_delete <id>` — remove permanently
- `memory_consolidate` — shrink the whiteboard

## Init
The session store is initialized automatically. If missing, call `memory_init`.

## Rules
- Code wins over memory; update stale memories instead of trusting them.
- Never invent memory; never store secrets.
