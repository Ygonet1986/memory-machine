# Roadmap: from project memory to longitudinal personal memory

## The promise (owner, 2026-09-22)

> Memory Machine does not aim to make the model recall everything at once. It
> aims to make the past **preservable, traceable and recoverable** - offering
> the model the right evidence, at the right moment, inside a limited budget.

The distinction behind it: "infinite" memory does not mean putting all the
past into the context; it means **preserve indefinitely and recover
selectively** what matters now. The closed experimental lines already showed
the shape of the problem: preserving is relatively easy; **admitting the
correct evidence to the context is the decisive problem** (a memory can keep
everything and still fail by retrieving too much, too late, or the wrong
remembrance).

## Intended progression

1. **Project memory** *(start here)* - defined scope, verifiable evidence,
   lower risk. Decisions, requirements, versions, tasks and results have
   objective records and can be evaluated. Memory value is demonstrable:
   reconstructing why a decision was made, tracking commitments across
   months, linking code/docs/experiments/conversations, detecting
   contradictions between a current and a past decision, transferring a
   project across sessions without re-explanation, and separating historical
   facts from later interpretations and summaries.
2. **Work memory** - multiple projects, habits and professional preferences.
3. **Personal assistant** *(transformational, most delicate)* - routine,
   commitments and cross-domain context. Requires answers that project memory
   can defer: what must never be recorded, what to forget automatically, what
   may be inferred, when to ask permission, how to correct a wrong memory,
   and when an old memory no longer represents the person.
4. **Integrated longitudinal memory** - only with granular control, audit and
   real forgetting.

Professional projects are the best initial validation field; the personal
assistant is the long-term application.

## How this connects to the current phase

The publication is closed and the app ships at `v0.3.3`, which also carries
the **Companion** surface (characters with synthetic lives; lab-validated,
pilot not started). The active measurement is `admission-shadow-v2`: the
window restarted from zero under §8 when turn slots were activated, the
pre-restart logs are archived and never counted, and only the coverage-only
checker runs until the frozen stop rule reaches `met:true`. Project memory
remains the first environment where those signals become meaningful; the
personal-assistant progression above is still gated on the consent,
provenance and retention contract described in step 3.

Current architecture and status: [`ARCHITECTURE.md`](ARCHITECTURE.md).
