# Test Doubles at Boundaries

Prefer real components inside the boundary under test. Replace dependencies when doing so controls an external system, nondeterminism, cost, or a failure condition relevant to the example. Ownership alone does not determine the boundary: an owned service can still be an external dependency of the system being tested.

Use a test database or filesystem when their real behavior matters to the promise. Use a fake clock or random source for deterministic examples. An API stub can exercise consumer behavior, but cannot prove the real provider's protocol or an adapter's integration; verify those separately when they are in scope.

## Keep the double faithful

- Replace a dependency at its public interface; preserve relevant errors and response shapes.
- Supply dependencies through the project's existing injection or adapter conventions. Add an interface only when the boundary needs one.
- Keep setup limited to the current example. A double that reproduces production business logic is another implementation to debug.
- Assert the external effect the contract promises. Requests, payloads, and counts can be behavior; private collaborator interactions usually describe structure.

For example, when the contract says that placing a valid order requests one charge for its total, a recording payment client can expose that request:

```typescript
test("requests one charge for the order total", async () => {
  const payments = recordingPaymentClient(); // Implements the payment boundary.
  await placeOrder({ total: 25 }, { payments });

  expect(payments.requests).toEqual([{ amount: 25 }]);
});
```

This checks what the payment system receives. A spy on a private `calculateCharge` helper would constrain the internal route to that result. The payment double's recorded requests must come from the exercised code, not from test setup.
