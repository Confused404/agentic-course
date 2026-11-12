# promo backlog

Implement in order. Each feature must keep every earlier feature working. Money is integer cents; "floor" means
round down to a whole cent. Coupon codes compare case-insensitively.

## F1: Percentage coupons with minimum spend
- `Coupon(code, "percent", percent=P, min_spend_cents=M)`: takes P% off the **discountable amount**, which is the
  cart subtotal minus any buy-X-get-Y discounts (F2; none exist yet). The discount is floored to a whole cent.
- `percent` must be 1–100; otherwise the coupon is rejected with reason `"invalid"`.
- If the cart **subtotal** is below `min_spend_cents`, reject with reason `"min_spend"`. A subtotal exactly equal to
  the minimum qualifies.

## F2: Buy-X-get-Y coupons
- `Coupon(code, "bogo", buy_sku=S, buy_qty=X, free_qty=Y)`: for every complete group of X+Y units of SKU S in the
  cart, Y of them are free. Discount = (units of S // (X+Y)) × Y × S's unit price.
- If S is not in the cart, or no complete group exists, reject with reason `"not_applicable"`.
- X and Y must both be ≥ 1, otherwise reject with `"invalid"`.

## F3: Stacking rules
- Order of application, whatever order the coupons are given in: all bogo coupons first, then at most ONE percent
  coupon, then fixed coupons in the order given.
- If several percent coupons are valid, apply the one with the largest discount (ties: the first given); reject the
  others with reason `"stacking"`.
- A code that appears more than once (case-insensitively) applies at most once; later copies are rejected with
  `"duplicate"`. Duplicates are checked before anything else, in the order given.
- The total never goes below 0 (a fixed coupon's recorded discount is what it actually took off).
- `Result.applied` lists applied coupons in the order they were applied; `Result.rejected` in the order given.

## F4: Expiry
- `expires_at` is an ISO 8601 timestamp WITH a UTC offset (e.g. `2026-11-30T23:59:59-05:00`). A coupon is valid
  only if `now` is strictly before `expires_at`. Expired: reject with `"expired"`.
- A timestamp without an offset is ambiguous: reject with `"invalid"`. `None` means it never expires.
- `apply(..., now=None)` uses the current UTC time. A naive `now` passed by the caller is a programming error: raise
  `ValueError`.
- Expiry is checked after duplicates and before everything else.

## F5: `explain` CLI
`python -m promo explain CART.json` prints how a cart was priced:
```
APPLIED <CODE> -$<dollars with 2 decimals>
REJECTED <CODE> (<reason>)
TOTAL $<dollars with 2 decimals>
```
APPLIED lines in application order, then REJECTED lines in input order, then TOTAL. Codes are printed as given.
The file is JSON: `{"lines": [{"sku", "unit_cents", "qty"}], "coupons": [{...Coupon fields...}], "now": "..."}`.
`lines` is required; `coupons` is optional (default none); `now` is optional and, when present, an ISO 8601 timestamp
WITH a UTC offset (a naive `now` is malformed). Each coupon needs at least `code` and `kind`.
Exit code 0. A missing file, invalid JSON or a malformed cart/coupon: one line starting with `error:` on stderr,
nothing on stdout, exit code 2.
