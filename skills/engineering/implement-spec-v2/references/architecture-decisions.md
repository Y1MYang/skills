# Architecture decisions

Read this reference when producing or reviewing the architecture document in steps 4 and 5. Prioritize removing unearned abstractions, then challenge premature commitment to the first design. These are review questions with evidence-backed exceptions; the spec and compatibility requirements remain constraints.

Use the installed `codebase-design` skill's core vocabulary when available, without starting its separate design workflows. A module's interface includes the invariants, ordering, errors, and other knowledge its callers need; depth means hiding meaningful complexity behind that interface. The guidance below also works when that skill is unavailable.

## Simplify the design

Apply these locally adapted principles to consequential additions or changes to modules, interfaces, and state:

- **Laziness Protocol (`principle-laziness-protocol`).** Start with the simplest direct approach that satisfies the complete requirement. Justify each new abstraction with a concrete caller scenario from existing code or the approved spec, and the decisions, invariants, or repeated work it gathers. Speculative flexibility alone is insufficient justification. Prefer removing unnecessary mechanisms to adding another wrapper around them.
- **Minimize Reader Load (`principle-minimize-reader-load`).** Examine both the indirections a reader must trace and the hidden or mutable state they must remember. Ask what happens if a proposed layer is removed: does complexity disappear, or spread into callers? Keep a layer that earns its interface by concentrating real complexity, even with one current caller. Fewer files, lines, or layers do not by themselves establish a better design.

Judge simplicity across the implementation and its callers together. The direct approach must meet the same error, concurrency, recovery, and compatibility constraints as its alternatives; transferring those obligations to callers is not a simplification.

Keep structural changes within what this requirement needs, including adjustments that avoid introducing duplicate mechanisms. Record adjacent, independently useful cleanup as follow-up work. For example, a 12-file cleanup unrelated to a 2-file feature is separate work; changing existing structure to avoid adding another redundant layer belongs in the feature's design comparison. File count alone decides neither case.

## Compare meaningful alternatives

Apply **Exhaust the Design Space (`principle-exhaust-the-design-space`)** to important decisions with multiple viable approaches, such as a new module interface or a change in state ownership, lifecycle, or coordination. Produce two structurally different sketches under the same requirements, including the simplest viable direct approach. Show caller usage and where each design keeps its state and invariants; renaming or rearranging the same shape is not another design.

For mechanical changes following an established pattern, or constraints that admit only one viable approach, record the applicable pattern or constraint briefly and proceed. A second candidate is not required merely to fill a template.

Use a throwaway prototype only when a consequential uncertainty cannot be resolved from the available evidence and sketches. Name the question and the observation that would distinguish the candidates before building it. Keep prototype artifacts in invocation-owned notes/resources under the existing resource protocol; they are design evidence, not production implementation or formal spec tests. Sketches do not require extra agents, model roles, or an upstream pstack workflow.

## Deliver and review

Alongside the existing six-part architecture contract, record concise answers to:

1. **Direct approach:** What is the simplest viable shape, illustrated by a caller scenario?
2. **Abstraction value:** What knowledge does each consequential new or changed abstraction hide, and where would that complexity go without it?
3. **Decision and evidence:** Where comparison applies, why choose this candidate over the alternative? Otherwise, which established pattern or constraint settles the choice? Identify any principle that changed a decision and explain evidence-backed exceptions. Distinguish observed prototype results from reasoning and unresolved assumptions.

The step 5 reviewer checks these answers against the spec and exploration evidence, including whether simplicity was achieved by moving obligations to callers. Return material gaps to the architect; do not require principle name-dropping, additional alternatives, or a prototype once the choice is adequately supported. A short explanation suffices for a mechanical change.

Use this reference within the existing v2 inputs, roles, architecture approval, and test independence rules. It adds decision evidence, not another execution or human approval stage. When inherited by `adopt-spec-v2`, keep compliant existing design as the baseline and compare only open decisions or changes justified by evidence; missing historical comparisons alone do not warrant rework.

## Sources and adaptation

Locally adapted from pstack `0.15.15` at commit `ccb5507cec1546dc88135c1139c811e6c59115ba`:

- [Laziness Protocol](https://github.com/cursor/plugins/blob/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack/skills/principle-laziness-protocol/SKILL.md)
- [Minimize Reader Load](https://github.com/cursor/plugins/blob/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack/skills/principle-minimize-reader-load/SKILL.md)
- [Exhaust the Design Space](https://github.com/cursor/plugins/blob/ccb5507cec1546dc88135c1139c811e6c59115ba/pstack/skills/principle-exhaust-the-design-space/SKILL.md)

The adaptation replaces fixed layer/time heuristics and automatic wrapper removal with a complexity-and-caller assessment, uses two sketches before optional prototypes, and preserves v2's scope and workflow. This file is the runtime reference; upstream links record provenance, not additional workflows to invoke or content to fetch during each task. The upstream [MIT license](pstack-LICENSE.txt) is retained alongside it.
