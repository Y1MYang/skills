# Tests That Specify Behavior

A useful test fails when the promised behavior breaks and keeps passing when only internal structure changes. Judge it against both hypothetical edits before relying on it.

## One example, one outcome

Give each new cycle one concrete example with independently justified expectations. Several assertions may describe the same result, such as an order's status and receipt. Add another input or failure case in a later cycle; combine already verified examples when refactoring makes the tests clearer.

```typescript
// Requirement: shipping is 10 below a total of 100, otherwise free.
test("charges shipping below the free-shipping threshold", () => {
  expect(shippingCost(99)).toBe(10);
});

// Add this in the next cycle, after the first example is Green.
test("waives shipping at the threshold", () => {
  expect(shippingCost(100)).toBe(0);
});
```

Expected values come from the requirement, a worked example, or an independent oracle. Recomputing the production algorithm in the assertion, or copying the current implementation's output, can preserve the same defect on both sides.

## Observe the promised boundary

Choose assertions from the contract, not from the kind of assertion:

| Public promise | Useful observation |
| --- | --- |
| A created user is retrievable | Read the user through the public lookup API |
| An adapter persists an agreed row format for another consumer | Inspect that row through the database boundary |
| A payment is requested once with the correct amount | Observe the external payment request, payload, and count |
| No payment occurs for an empty cart | Observe the absence of payment requests; include a separate valid-cart example showing the observer detects requests |
| An event is published for downstream consumers | Observe the message's public schema and destination |

Database reads, call counts, and message assertions are appropriate when they observe the promised external effect. They are coupled to implementation when they pin private storage, helper calls, or ordering that the contract leaves free to change. Use the public lookup API when persistence details are private.

Check that the test actually reaches the boundary and that the assertion distinguishes the expected result from plausible wrong results. Assert exact payloads, errors, ordering, or timing only to the precision the contract requires. Keep shared fixtures and helpers from calculating the answer with production logic.
