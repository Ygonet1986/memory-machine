import { join } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"

const CLI = `${process.env.HOME}/memory-machine/bin/memory-cli`
const MEM_BASE = join(process.env.HOME!, ".config", "opencode", "memory")
// Turn slots (tape records for what the user said + what was answered) are
// opt-in: off by default so the default write path is unchanged. Set
// MEMORY_MACHINE_TURN_SLOTS=1 to activate (restart opencode afterwards).
const TURN_SLOTS = process.env.MEMORY_MACHINE_TURN_SLOTS === "1"

function sessionRoot(sessionID: string): string {
  return join(MEM_BASE, "sessions", sessionID)
}

async function runCli(sessionID: string, args: string[]): Promise<string | null> {
  try {
    const proc = Bun.spawn([CLI, "-C", sessionRoot(sessionID), ...args], {
      stdout: "pipe",
      stderr: "pipe",
    })
    const out = await new Response(proc.stdout).text()
    const code = await proc.exited
    return code === 0 ? out : null
  } catch {
    return null
  }
}

function memoryContext(r: any): string {
  const parts: string[] = []
  if (r?.understanding) parts.push(`Understanding: ${r.understanding}`)
  if (r?.checklist) parts.push(`Checklist (must remember):\n${r.checklist}`)
  if (r?.annotations?.length) {
    parts.push("Remembered (from memory agents):")
    for (const a of r.annotations) parts.push(`- ${a.memory_id}: ${a.note}`)
  }
  if (r?.attached_content?.length) {
    parts.push("Attached text (relevant chunks):")
    for (const c of r.attached_content) parts.push(`- [${c.memory_id}] ${c.text}`)
  }
  if (r?.past_hits?.length) {
    parts.push("From previous sessions:")
    for (const h of r.past_hits) parts.push(`- [${h.session_id}/${h.memory_id}] ${h.summary}`)
  }
  return parts.join("\n")
}

function attachmentPath(part: any): string | null {
  if (part?.type !== "file") return null
  const name = String(part.filename || part.source?.path || "")
  const mime = String(part.mime || "")
  const isTxt = name.toLowerCase().endsWith(".txt") || mime === "text/plain"
  if (!isTxt) return null
  const path =
    part.source?.path ||
    (typeof part.url === "string" && part.url.startsWith("file://")
      ? decodeURIComponent(part.url.slice(7))
      : "")
  return path || null
}

export const MemoryPlugin: Plugin = async ({ client }) => {
  return {
    // Deterministic recall on every new user message, scoped to this session's
    // tape plus relevant memories from previous sessions. Attached .txt files
    // are ingested into the tape (as labeled chunk memories) before recall.
    "chat.message": async (input, output) => {
      const textParts = (output.parts as any[]).filter(
        (p) => p.type === "text" && typeof p.text === "string",
      )
      const text = textParts.map((p) => p.text).join("\n").trim()

      for (const part of output.parts as any[]) {
        const path = attachmentPath(part)
        if (path) {
          await runCli(input.sessionID, ["attach", path])
        }
      }

      if (!text) return

      const started = Date.now()
      const out = await runCli(input.sessionID, ["recall", text, "--cross-session"])
      // Slot 1: what the user said. Written *after* recall so the turn does
      // not retrieve itself as a candidate; runs even if recall fails.
      if (TURN_SLOTS) {
        await runCli(input.sessionID, [
          "ask",
          "--text",
          text,
          "--message-id",
          output.message.id || "",
        ])
      }
      if (!out) return
      let r: any
      try {
        r = JSON.parse(out)
      } catch {
        return
      }
      if (r?.ok !== true) return

      try {
        await client.app.log({
          body: {
            service: "memory",
            level: "info",
            message: "recall",
            extra: {
              ms: Date.now() - started,
              cached: !!r.cached,
              annotations: r.annotations?.length ?? 0,
              past_sessions: r.past_hits?.length ?? 0,
              tape: r.tape_records,
            },
          },
        })
      } catch {
        // logging must never break recall
      }

      const ctx = memoryContext(r)
      if (!ctx) return

      output.parts.unshift({
        id: `prt_${crypto.randomUUID().replace(/-/g, "")}`,
        sessionID: output.message.sessionID,
        messageID: output.message.id,
        type: "text",
        text: `## Session memory (recalled)\n${ctx}`,
        synthetic: true,
      } as any)
    },

    // Slot 2: what was answered. On assistant completion only, and only with
    // the flag on; dedup by message id happens in the CLI (`reply`).
    event: async ({ event }) => {
      if (!TURN_SLOTS) return
      const e = event as any
      if (e?.type !== "message.updated") return
      const info = e?.properties?.info
      if (!info || info.role !== "assistant") return
      if (!info.time?.completed || info.error) return
      if (!info.parentID) return
      let parts: any[] = []
      try {
        const res: any = await (client as any).session.message({
          path: { id: info.sessionID, messageID: info.id },
        })
        parts = res?.data?.parts ?? []
      } catch {
        return
      }
      const text = parts
        .filter(
          (p) =>
            p?.type === "text" && typeof p.text === "string" && !p.synthetic,
        )
        .map((p) => p.text)
        .join("\n")
        .trim()
      if (!text) return
      await runCli(info.sessionID, [
        "reply",
        "--text",
        text,
        "--message-id",
        info.id,
        "--pair",
        info.parentID,
      ])
    },

    "experimental.session.compacting": async (input, output) => {
      const out = await runCli(input.sessionID, ["whiteboard", "--no-annotations"])
      if (out && out.trim()) {
        output.context.push(`## Session memory\n${out}`)
      }
    },

    tool: {
      memory_init: tool({
        description: "Initialize the memory tape for this session.",
        args: {},
        async execute(_args, context) {
          const out = await runCli(context.sessionID, ["init"])
          return out ?? "memory_init failed"
        },
      }),

      memory_remember: tool({
        description:
          "Append a durable memory to this session's tape (type: decision, lesson, preference, bugfix, build). Use after meaningful work so the session remembers it.",
        args: {
          summary: tool.schema.string(),
          type: tool.schema.string().optional(),
          why: tool.schema.string().optional(),
        },
        async execute(args, context) {
          const out = await runCli(context.sessionID, [
            "remember",
            "--summary",
            args.summary,
            "--type",
            args.type || "decision",
            "--why",
            args.why || "",
          ])
          return out ?? "memory_remember failed"
        },
      }),

      memory_checkpoint: tool({
        description:
          "Record the current turn back to this session's memory after answering: the question, a summary of what was done, and optional durable memories (JSON list). Updates the whiteboard's understanding and checklist.",
        args: {
          question: tool.schema.string(),
          summary: tool.schema.string(),
          memories: tool.schema.string().optional(),
        },
        async execute(args, context) {
          const cmd = ["checkpoint", args.question, args.summary]
          if (args.memories) cmd.push("--memories", args.memories)
          const out = await runCli(context.sessionID, cmd)
          return out ?? "memory_checkpoint failed"
        },
      }),

      memory_list: tool({
        description: "List this session's tape records.",
        args: {},
        async execute(_args, context) {
          const out = await runCli(context.sessionID, ["list"])
          return out ?? "memory_list failed"
        },
      }),

      memory_whiteboard: tool({
        description:
          "Read this session's whiteboard (subject, understanding, checklist and the memory agents' annotations).",
        args: {},
        async execute(_args, context) {
          const out = await runCli(context.sessionID, ["whiteboard"])
          return out ?? "memory_whiteboard failed"
        },
      }),

      memory_archive: tool({
        description: "Archive a memory record so the memory agents stop reminding about it.",
        args: { memory_id: tool.schema.string() },
        async execute(args, context) {
          const out = await runCli(context.sessionID, ["archive", args.memory_id])
          return out ?? "memory_archive failed"
        },
      }),

      memory_delete: tool({
        description: "Delete a memory record permanently from the tape.",
        args: { memory_id: tool.schema.string() },
        async execute(args, context) {
          const out = await runCli(context.sessionID, ["delete", args.memory_id])
          return out ?? "memory_delete failed"
        },
      }),

      memory_consolidate: tool({
        description: "Consolidate the whiteboard (reduce it without losing continuity).",
        args: {},
        async execute(_args, context) {
          const out = await runCli(context.sessionID, ["consolidate"])
          return out ?? "memory_consolidate failed"
        },
      }),
    },
  }
}
