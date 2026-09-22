# Memory Machine — session memory

This project uses the Memory Machine: a persistent, numbered tape of memories
plus memory agents that recall relevant facts before you answer. **Each opencode
session has its own tape** (`~/.config/opencode/memory/sessions/<id>/`). Memory
is recalled automatically on every user message, scoped to the current session.

## Reading memory
- Memory is injected into your context automatically (plugin hook). Treat the
  "## Session memory (recalled)" block as authoritative context.
- To inspect it yourself: `memory_whiteboard` (summary: subject, understanding,
  checklist, agent annotations) or `memory_list` (all tape records).

## Writing memory
- After meaningful work — a decision, a lesson, a convention, a bugfix — call
  `memory_remember` (or `memory_checkpoint`) to persist it.
- `memory_checkpoint` records the current turn and refreshes the whiteboard's
  understanding + checklist.

## Managing memory
- `memory_archive <id>` stops the agents from reminding about a stale memory.
- `memory_delete <id>` removes it permanently.
- `memory_consolidate` shrinks the whiteboard when it grows too large.

## Rules
- Code wins over memory. If the code contradicts a memory, update the memory;
  never trust a stale memory over the actual code.
- Never invent memory hits. Only surface what is actually on the tape.
- Never store secrets or credentials in memory.

## First use
- The session store is initialized automatically. If it is missing, call
  `memory_init` once.
