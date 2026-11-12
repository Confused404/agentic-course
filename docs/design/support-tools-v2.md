# Support tools v2: design (Node 05)

Author: <you> · Status: reference example. Your own design should come from YOUR Node 04 failures.

## Why a v2
Node 04 dev-split failures, classified from traces:
1. **Argument errors on refunds**: `reason="changed_mind"` for broken items (damaged_trap, sim_vague_damaged). The v1
   `reason` enum has no explanation of what each value covers.
2. **Interpretation errors after a POLICY error**: the model told the customer "outside the window" without offering
   the damaged route, because the error only said *what* failed, not *what to do*.
3. **Honesty**: "your refund is done" for a `pending_approval` refund (needs_approval). The result said
   `"status": "pending_approval"`; nothing said what that means for the customer.
4. **Extra calls**: `get_my_orders` before `lookup_order` when the customer gave the number (status_efficient).

Every item above comes from a **dev** task. Nothing here was written by looking at held-out tasks.

## Constraints
Same tool names and parameter names as v1 (the eval suite references them); no new required parameters; bindings
unchanged; policy stays enforced in `shopfront/services.py` (descriptions don't restate window lengths: they'd drift).

## Features (each switchable, so each can be measured alone)
- `desc`: the descriptions and parameter docs below (fixes 1 and 4).
- `errors`: structured errors (fixes 2), including argument-validation errors.
- `returns`: derived fields: dollars, `days_since_delivery`, trimmed `lookup_order`, `customer_message` on refunds
  (fixes 3).
Variants: `v1+desc`, `v1+desc+errors`, `v2` (= all three).

## Tools: exact text (the coding agent implements this verbatim; `test_tools_v2.py` checks it)
```yaml
cancel_order:
  description: Cancel an order that hasn't shipped (status 'placed'). Use when the customer asks to cancel. Shipped orders cannot be cancelled; offer a refund after delivery or escalation if it's late. Returns the new status.
  parameters:
    order_id: The order to cancel.
check_refund_eligibility:
  description: Check whether an order can be refunded for a reason, applying the official policy windows (which differ by reason and membership tier). No side effects. Use before issue_refund, with the reason that matches what the customer said. Returns eligible, problems, window_days, days_since_delivery and max_refundable_cents.
  parameters:
    order_id: The order number, e.g. 4821.
    reason: 'Why the customer wants a refund: damaged = arrived broken, cracked, defective or stopped working; not_as_described = wrong item, missing parts, differs from the listing; changed_mind = no longer wanted; late_delivery = arrived much later than promised; other = anything else.'
escalate_to_human:
  description: Hand the case to a human teammate. Use for lost packages, warranty claims, safety issues (such as a swollen battery) or anything your tools can't resolve. Ask the customer first unless it's a safety issue. Returns a ticket id; a human replies within one business day.
  parameters:
    summary: What the customer needs and what you already checked, in 1-3 sentences.
    order_id: The order concerned, if any.
get_my_orders:
  description: List this customer's most recent orders, newest first. Use only when the customer hasn't given an order number (if they have, use lookup_order directly). Returns up to `limit` orders with id, status, dates and total.
  parameters:
    limit: How many orders to return (default 10).
issue_refund:
  description: 'Refund an order to the original payment method. Use only after check_refund_eligibility says eligible, with the same reason. Large refunds are queued for human approval and are not complete when this returns: tell the customer it is pending review. Returns refund_id, status (issued or pending_approval) and customer_message.'
  parameters:
    order_id: The order to refund.
    amount_cents: Amount in cents, e.g. 4899 for $48.99; at most max_refundable_cents.
    reason: 'Why the customer wants a refund: damaged = arrived broken, cracked, defective or stopped working; not_as_described = wrong item, missing parts, differs from the listing; changed_mind = no longer wanted; late_delivery = arrived much later than promised; other = anything else.'
lookup_order:
  description: Get one of this customer's orders by number. Use when the customer mentions an order number. Returns status, key dates, days since delivery, items, total and existing refunds. Orders on other accounts are reported as not found.
  parameters:
    order_id: The order number the customer gave, e.g. 4821.
search_help_center:
  description: Search the help-center articles for policies and product care. Use for policy questions. Prefer articles with status 'current'; 'archived' articles describe old policies. Returns up to 3 articles with title, status, updated date and an excerpt.
  parameters:
    query: A few keywords, e.g. 'refund window'.
```

## Return shapes (`returns`)
- `get_my_orders`: `[{id, status, placed_on, delivered_on, total, total_cents}]`, dates `YYYY-MM-DD`, `total` like `$48.99`.
- `lookup_order`: `{id, status, placed_on, shipped_on, delivered_on, days_since_delivery, business_days_in_transit,
  items: [{name, qty}], total, total_cents, refunds: [{amount, status}]}`: only what the next decision needs.
- `issue_refund`: v1 fields plus `customer_message`: "Refunded $X to the original payment method." or
  "Submitted $X for review; it is not refunded yet."

## Errors (`errors`)
Every failure, including invalid arguments, returns `{"error": CODE, "message": ..., "next_steps": [...]}`.
`message` is the service's message (already written for the model); `next_steps`:
| code | situation | next_steps |
|---|---|---|
| NOT_FOUND | any | "Ask the customer to double-check the order number." · "Call get_my_orders to list their recent orders." |
| INVALID | amount over refundable | "Call issue_refund again with amount_cents no higher than max_refundable_cents from check_refund_eligibility." |
| INVALID | anything else (incl. schema validation) | "Fix the arguments as described and call the tool again." |
| POLICY | refund, reason changed_mind/other, window exceeded | "If the item arrived damaged or defective, check eligibility again with reason='damaged' (60-day window)." then the two below |
| POLICY | refund (any) | "Explain the reason to the customer in one or two sentences." · "Offer escalate_to_human if they disagree." |
| POLICY | cancel | "Offer a refund after delivery, or escalation if the order is late." |
