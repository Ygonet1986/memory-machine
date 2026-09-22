# CLI reference

All commands run as `python3 -m memory_machine <cmd>` (installed: `memory-cli <cmd>`).

| Command | Purpose |
|---------|---------|
| `init` | Create an empty project (config + tape + manifest + whiteboard) |
| `add --type T --summary S [--why W] [--files a,b]` | Append a memory to the tape |
| `subject S [--objective O]` | Set the current whiteboard subject |
| `run --task T` | Run one full cycle (agents -> whiteboard -> chatbot) |
| `consolidate [--llm]` | Consolidate the whiteboard (one consolidator agent) |
| `status` | Show tape / groups / agents / whiteboard state |
| `whiteboard` | Print the whiteboard |
| `context` | Print the main chatbot's conversation context |
| `recall Q [--cross-session] [--views v1,v2]` | Run memory agents for a question (JSON); optionally search other sessions / filter by views |
| `checkpoint Q S [--memories JSON]` | Record a turn back to memory (JSON) |
| `remember --summary S [--type T] [--why W] [--views v1,v2]` | Append a memory (JSON) |
| `list` / `archive ID` / `delete ID` | Manage tape records (JSON) |
| `attach PATH [--chunk-size N]` | Ingest a `.txt` into the tape as labeled chunk memories |
| `sessions` | List sessions (JSON) |
| `views` | List memory views / projections (JSON) |
| `rollup [--keep-recent N]` | Consolidate older tape records into one summary |
| `rehydrate ID [--reactivate]` | Recover the original memories behind a rollup |

Use `-C <dir>` to operate on a specific project directory. Run
`python3 -m memory_machine <cmd> --help` for details.

