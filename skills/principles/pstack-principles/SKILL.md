---
name: pstack-principles
description: "Before starting any non-trivial coding, design, or review task, consult the principles index below and apply the relevant pstack principles; re-check whenever the session moves to a new task. Also invoked explicitly via /pstack-principles to just show the index."
---

# Pstack Principles

Twenty-four engineering principles from poteto/pstack, snapshotted verbatim under `principles/`. This file is the only entry point: the index below is the routing layer, the full texts are read on demand.

## Rescan protocol

At the start of **every non-trivial task in this session** (not just when explicitly invoked):

1. Scan the index and pick the principles whose "Apply when…" matches the current task — usually 2 to 4, not all of them.
2. Read each match in full from `principles/<name>.md` before acting on the task.
3. When the session moves to a different task, rescan from step 1 — earlier selections do not carry over automatically.

Do not read principle files for tasks where nothing in the index matches; the index scan is the whole cost then.

## Application

- Name the chosen principles in one line when you start the task ("Applying principle-x and principle-y because…"), then work. Mention a principle again only when it materially changes a decision — for example, when it rejects an otherwise attractive approach.
- Relationship to process skills: `/tdd`, `/code-review`, and similar skills govern **how** the work runs; these principles govern **whether the work is right**. Never use a principle to veto a process the user explicitly requested.
- When two principles conflict in a situation, prefer the more specific one ("Apply when…" narrower in scope) and say which one won.

## Index

| Principle | Apply when |
| --- | --- |
| principle-attack-the-premise | Two or more fixes sharing one premise have failed the same gate: write the premise down and test it directly before another fix that assumes it. |
| principle-boundary-discipline | Wiring validation, error handling, or framework adapters: concentrate guards at system boundaries, trust internal types, keep business logic in pure functions. |
| principle-build-the-lever | Any non-trivial work (edits, migrations, analyses, checks): build the tool that does it or proves it instead of working by hand. |
| principle-encode-lessons-in-structure | You write the same instruction twice or notice a recurring correction: encode the rule as a lint, flag, runtime check, or script. |
| principle-exhaust-the-design-space | A novel UI interaction or an architectural decision with no codebase precedent: build 2-3 competing prototypes and compare side by side. |
| principle-experience-first | Product, UX, or feature-scope tradeoffs: choose user delight over implementation convenience. |
| principle-explain-the-number | Before you trust, report, or act on a measured number: find what limits it and rule out that it measured something else. |
| principle-fix-root-causes | Debugging: trace each symptom to the first place the system went wrong and fix it there. |
| principle-foundational-thinking | Before writing logic: get core types and data structures right so downstream code becomes obvious. |
| principle-guard-the-context-window | Context is filling up (large outputs, long files, fan-out planning): route bulk to subagents, keep summaries in the main thread. |
| principle-laziness-protocol | Refactoring, evaluating diff size, or tempted to add abstractions: bias toward deletion and the smallest change that solves the problem. |
| principle-make-operations-idempotent | Designing commands, lifecycle steps, or loops that run amid crashes and retries: converge to the same end state regardless of partial prior runs. |
| principle-migrate-callers-then-delete-legacy-apis | Introducing a new internal API while old callers exist: migrate callers and delete the old API in the same wave. |
| principle-minimize-reader-load | Code is hard to trace: count layers between question and answer, collapse one-caller wrappers, shrink mutable scope. |
| principle-model-the-domain | Writing stateful logic, or code branches a lot or repeats a shape assumption across files. |
| principle-never-block-on-the-human | Tempted to ask "should I do X?" on reversible work: decide and proceed. |
| principle-outcome-oriented-execution | Planned rewrites and migrations with explicit phase boundaries: converge on the target architecture, no throwaway compatibility code. |
| principle-prove-it-works | After completing a task, before declaring done: verify against the real artifact, not a proxy or self-report. |
| principle-redesign-from-first-principles | Integrating a new requirement into an existing design. |
| principle-separate-before-serializing-shared-state | Concurrent actors might write the same file, branch, key, or state object: eliminate the sharing first. |
| principle-sequence-verifiable-units | Multi-step work (sweeps, migrations, stacked PRs): break into small units that each end in a verifiable state, check each before the next. |
| principle-subtract-before-you-add | Sequencing an addition, refactor, or rewrite: remove dead code and redundant validators first, then build. |
| principle-test-behavior-not-implementation | Writing or changing a test: assert what the code's users can observe, not the internals. |
| principle-type-system-discipline | Designing types or writing statically-typed code: make illegal states unrepresentable, parse external data at boundaries. |

Full texts: `principles/<principle-name>.md` — each is the upstream SKILL.md verbatim, including its own "Apply when…" guidance and rules of thumb.

---

Principles verbatim from [poteto/pstack](https://github.com/cursor/plugins/tree/main/pstack) (cursor/plugins repo, `pstack` directory), MIT License, Copyright (c) 2026 Lauren Tan. This router and the index wording are local additions; the principle texts are unmodified.
