# On-demand Expert protocol

## Qualify the blocker

Complete one evidence-backed investigation before requesting help: inspect the allowed materials, test plausible hypotheses, and record what remains unexplained. Request an Expert only when a specific technical blocker still prevents delivery and there is no known executable way to proceed; the problem may be an unexplained cause or difficulty addressing a known cause. A failed test or unsuccessful fix alone is not a trigger when the responsible agent already knows how to proceed.

These are examples of qualifying blockers, not automatic dispatch rules:

| Requester | Example after the initial investigation |
| --- | --- |
| Exploration | A critical call chain, hidden constraint, or technical contradiction between sources remains unexplained and blocks architecture work. |
| Architect | Compared designs still cannot reconcile the spec, compatibility constraints, and testability at a concrete interface or state model. |
| Test implementer | The spec and architecture still do not yield a workable observation point, deterministic fixture, or construction of a difficult boundary case. |
| Implementer | Hypothesis checks or a minimal reproduction still cannot explain an algorithm, state transition, concurrency, or integration problem. |
| Coverage audit | Requirement-to-test tracing still cannot establish whether a complex test actually covers a specific acceptance criterion. |
| Standards reviewer | Investigation still cannot substantiate or rule out a concrete suspected defect under an applicable repository rule. |
| Spec reviewer | Behavior tracing still cannot substantiate or rule out a specific suspected violation that affects acceptance. |
| Merger | Examining the common base, both changes' intent, and the architecture contract still leaves a semantic merge conflict unexplained. |
| Checkpoint | Collected integration evidence still cannot locate the cause or distinguish environment, test, and implementation-contract failures. |
| Fixer | One diagnostic round yields no executable repair approach, whether the cause remains unknown or the known cause is difficult to address. |
| Main conversation | Conflicting technical evidence from subagents prevents an informed adjudication. |

Known coverage gaps, ordinary text conflicts, unavailable materials or credentials, and missing business decisions follow the existing workflow. The Expert supplies technical analysis; scope, priority, spec interpretation, and ownership decisions remain with the main conversation.

## Request and dispatch

1. The responsible agent delivers a **needs-help** report containing:
   - one concrete question and the delivery it blocks;
   - the observed failure, completed hypothesis checks, and relevant evidence;
   - context pointers to permitted inputs and the applicable branch, worktree, or revision;
   - the input restrictions, intended recipients of the diagnosis, any current round count or remaining budget, and the applicable protocol requirements for the main conversation's dispatch and handoff.
   Report through the coordinating subagent if nested. Keep the original task and worktree; pause only work dependent on the blocker and preserve unrelated work and running tests or builds. For a main-conversation request, assemble the same report from materials that phase permits the main conversation to access; in steps 6-10 use subagent reports rather than querying files.
2. The main conversation checks whether the report satisfies the trigger. If it lacks an initial investigation or a concrete blocker, return it to the responsible agent for ordinary work. Dispatch at most **one active Expert per blocker**, using the explicitly selected Expert model and a fresh, narrowly scoped context containing the report, permitted pointers, and this protocol. Do not inherit the requester's entire conversation history or enlarge its permissions. The requesting agent does not dispatch an Expert itself.

## Diagnose and finish

- The Expert may read permitted materials and run **read-only diagnostic commands**. It provides diagnosis, reasoning, proposed checks, and brief illustrative examples when useful. It does not modify any files, including notes; apply fixes; commit; merge; or perform commands that create files, caches, or other mutations. Delegate any required mutating experiment to the responsible agent through the proposed checks.
- Preserve the requesting task's input boundaries in both the investigation and the delivered advice. For test authoring, derive advice only from the spec, architecture, and permitted test-side artifacts; do not inspect implementation code. While helping an implementer author code, do not inspect formal spec tests. Review and integration requests use only inputs and recipients permitted at that phase; advice sent back to an author must preserve that author's isolation. Expert access does not override test-failure ownership or architecture/spec adjudication rules.
- Deliver one final response with a supported diagnosis, or clearly labeled candidate hypotheses or an **unresolved** status; cite the evidence and give executable next verification steps where possible. Distinguish confirmed facts from speculation. Evidence insufficiency is a valid unresolved outcome, not a reason to extend the instance into an ongoing debugging conversation.
- After this response, the Expert instance ends, whether or not it found the cause. Do not resume it, send follow-up tasks, or retain it as a standing advisor. The Expert does not request or dispatch another Expert. Any later consultation uses a **new instance** through the main conversation.

## Handoff, budgets, and escalation

- The main conversation returns the diagnosis to the original responsible agent to execute the proposed checks, make any justified changes, verify the result, and record useful findings in the shared notes. Ownership stays with the original role. If that agent has failed or timed out and cannot continue, dispatch a replacement with the original role's model and checkpoint, including the Expert report.
- A second consultation for the **same blocker** requires substantive new evidence from the responsible agent's investigation or verification of the prior advice. When an unresolved Expert response or its verification produces new evidence, first return it to the original responsible agent for another attempt; do not immediately dispatch another Expert. If that attempt still meets the help trigger, a new instance may be requested with the new evidence. Changing instances alone is not a retry strategy. A distinct new blocker may qualify separately under the same trigger.
- Consultation takes place within the current attempt: it does not reset or extend the checkpoint's **1-2 rounds** or the fixer's **3 rounds**, nor does replacing either agent. The responsible agent's resulting repair and verification remain in that budget; an attempt that cannot proceed after diagnosis is reported as a failed round. At exhaustion, return to the main conversation for adjudication as the existing steps require.
- If the Expert cannot resolve the blocker but provides substantive new evidence or findings, or verification of its advice produces them, return that evidence to the original responsible agent for another attempt within the applicable budget. If there are no new findings but the main conversation has another executable approach, dispatch the responsible role to try it. **Escalate to the user only when all three conditions hold: the Expert's help has left the blocker unresolved, there are no new findings to pursue, and the main conversation has no other executable approach.** Report the blocker, evidence, attempted approaches, Expert findings, and the specific remaining question or action needed; do not cycle through more Experts without new evidence.
