# Desktop app (macOS)


A native macOS menu-bar + window chatbot that runs the Memory Machine in
process (PySide6), packaged as a self-contained `.app`.

### Install

1. Open `dist/Memory Machine.dmg`, drag `Memory Machine.app` to `/Applications`.
2. First launch: right-click the app → **Open** (ad-hoc signed, not notarized —
   Gatekeeper requires this once).

### Build from source

```bash
./app/build.sh        # creates dist/Memory Machine.app (and re-verifies icon)
```

### App specifics

- The DeepSeek API key is stored in the **macOS Keychain**
  (`security find-generic-password -s memory-machine`), never in a file. The
  model and memory root live in
  `~/Library/Application Support/MemoryMachine/settings.json` (chmod 600,
  never in the repo). Edit them in the app's **Settings** dialog.
- Persistent memory is stored under
  `~/Library/Application Support/MemoryMachine/data/`.
- **Each topic owns its own tape.** A topic is a self-contained memory store
  (`data/topics/<id>/`) named by its creation date/time (with an optional
  label); memory agents are created per topic as that topic's tape grows.
- **Auto topic (multi-topic)** — when enabled, an LLM router infers which topic
  each message refers to (by time reference like "yesterday" and by subject)
  and switches tapes internally, falling back to today's topic when nothing
  matches. When disabled, use the topic selector manually.
- **Automatic topic creation** — by default one topic per day is created
  automatically (`auto_topic: day`). Alternatives in Settings: `idle` (a new
  topic after N hours without activity) or `off` (fully manual).
- **RAG documents + tape attachments** — the **Add files** button imports `.txt`
  files: they are added as RAG reference material (`data/documents/`, retrieved
  per message with BM25) **and** split into chunks that are appended to the
  session's tape as labeled `attachment` memories, so the memory agents can
  recall them. Attached chunks are secret-scanned and deduplicated by file
  hash. (This is the one intentional exception to "external context never
  touches the tape".)
- **Web search** — a keyless DuckDuckGo lookup for the current message. In
  **Auto** mode (default) it runs only when the question looks like it needs
  current info; the checkbox forces it on. Results go to the chatbot for that
  turn only (kept out of long-term memory).
- The app runs in the menu bar; closing the window hides it. Use the tray menu
  to reopen, open Settings, or quit.
- Each reply shows **Remembered** memory ids (from the memory agents) and
  **Saved to tape** ids (durable memories the chatbot produced).
