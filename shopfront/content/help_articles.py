"""Help-center articles. `python -m shopfront.seed` writes each to data/help_center/<slug>.md.

Deliberate realism for Node 07 (retrieval):
- One ARCHIVED article contradicts the current policy (14-day returns vs 30). Good retrieval
  must prefer the current article; good answers must not cite the archived one.
- Some facts live in only one article (e.g. gift cards are non-refundable), some are spread
  over several (damaged items: refund window in one article, photo requirement in another).
- Product-care articles use vocabulary customers don't (customers say "my pan is rusty",
  the article says "oxidation" and "re-seasoning"), which is where lexical search fails.
"""

ARTICLES = [
    {
        "slug": "refund-policy",
        "title": "Refund policy",
        "updated": "2026-09-01",
        "status": "current",
        "body": """
You can request a refund for a delivered order within **30 days of delivery**. Shopfront Plus
members get **45 days**. The clock starts on the delivery date shown in your order history,
not the date you placed the order.

**Damaged or defective items** have a longer window: **60 days from delivery**, for every
customer. See "Damaged or defective items" for what we need from you.

What cannot be refunded:
- Orders that were cancelled or already returned.
- Gift cards (see "Gift cards").
- Orders that have not been delivered yet. If your order is late, see "Lost or late packages".

Each order can receive **one refund**. If you need to return only part of an order, tell us
which items and we will refund those items in a single refund.

Refunds over **$200** are reviewed by a member of our team before they are issued. This
usually takes one business day. Smaller refunds are issued immediately and appear on your
statement within 5 to 10 business days depending on your bank.
""",
    },
    {
        "slug": "returns-policy-2025",
        "title": "Returns policy (2025)",
        "updated": "2025-02-10",
        "status": "archived",
        "body": """
ARCHIVED: this article describes our 2025 policy and is kept for reference only.

Items may be returned within **14 days** of delivery for a refund. Items must be unused and in
the original packaging. A 10% restocking fee applies to electronics accessories. Plus members
receive free return shipping labels.
""",
    },
    {
        "slug": "damaged-items",
        "title": "Damaged or defective items",
        "updated": "2026-08-15",
        "status": "current",
        "body": """
We are sorry if something arrived broken. To make a claim:

1. Take a clear **photo of the damage** and, if possible, of the shipping box.
2. Contact support with your order number and the photo.
3. We will offer a replacement or a refund. You do not need to send the item back unless we ask.

In chat, our assistant can refund an eligible damaged item right away; we may follow up by email to
ask for the photo.

Claims for damaged or defective items are accepted for **60 days from delivery**. Items that
stop working later may still be covered by the product warranty (see "Warranty coverage").

If the item is dangerous (for example a swollen power bank or a cracked glass lid), stop using
it immediately and read "Battery safety" where relevant.
""",
    },
    {
        "slug": "shipping-times",
        "title": "Shipping times and costs",
        "updated": "2026-06-01",
        "status": "current",
        "body": """
Standard shipping within the US and Canada takes **3 to 7 business days** after the order ships.
Orders ship within 1 business day when items are in stock.

- Standard shipping is free on orders over $50, otherwise $6.95.
- Express shipping (1 to 3 business days) costs $19.95.
- Shopfront Plus members get free express shipping on every order.

Large items such as standing desks and tents ship separately and may take up to 10 business
days. You will receive one tracking number per package.
""",
    },
    {
        "slug": "international-shipping",
        "title": "International shipping",
        "updated": "2026-06-01",
        "status": "current",
        "body": """
We ship to the UK, the EU, Australia and Japan. International delivery takes **7 to 21 business
days**. Customs duties and import taxes are charged by the destination country and are paid by
the customer on delivery; we cannot refund them.

Some items cannot ship internationally: power banks over 100Wh, fuel canisters and anything
with a lithium battery larger than airline limits.
""",
    },
    {
        "slug": "order-tracking",
        "title": "Tracking your order",
        "updated": "2026-05-20",
        "status": "current",
        "body": """
When your order ships we email you a tracking link. You can also see the status of every order
in your account under **Orders**. Statuses mean:

- **placed**: we received your order and are preparing it.
- **shipped**: it is with the carrier. Tracking may take 24 hours to update.
- **delivered**: the carrier marked it delivered.
- **cancelled**: the order was cancelled before shipping.
- **returned**: the order was returned and refunded.

If tracking says delivered but you cannot find the package, check with neighbours and your
building's mailroom, then contact us within 7 days.
""",
    },
    {
        "slug": "lost-packages",
        "title": "Lost or late packages",
        "updated": "2026-07-02",
        "status": "current",
        "body": """
If your order has been in **shipped** status for more than **10 business days** (domestic) or
**25 business days** (international) with no tracking updates, it is considered lost. Contact
support: a team member will open a carrier claim and either reship the items or refund you.

Late packages are handled by a person, not by automated refunds, because we have to confirm
the carrier status first. Expect a reply within one business day.
""",
    },
    {
        "slug": "cancellations",
        "title": "Cancelling an order",
        "updated": "2026-03-11",
        "status": "current",
        "body": """
You can cancel an order while it is in **placed** status. Once an order has **shipped** it can no
longer be cancelled, but you can request a refund after it is delivered (see "Refund policy").

Cancelled orders are refunded in full to the original payment method within 3 business days.
""",
    },
    {
        "slug": "plus-membership",
        "title": "Shopfront Plus membership",
        "updated": "2026-09-01",
        "status": "current",
        "body": """
Shopfront Plus costs $49 per year and includes:

- Free express shipping on every order.
- A **45-day** refund window instead of 30 days.
- The PLUS15 discount code: 15% off one order per month.
- Early access to seasonal sales.

Plus membership fees are refundable within 14 days of purchase if you have not used any
Plus benefits.
""",
    },
    {
        "slug": "promo-codes",
        "title": "Discount and promo codes",
        "updated": "2026-04-04",
        "status": "current",
        "body": """
Enter codes at checkout. Current codes: SAVE10 (10% off), SAVE20 (20% off, seasonal), FLAT5
($5 off orders over $25) and PLUS15 (15% off, Plus members only).

Only **one percentage discount** applies per order. If you enter more than one, we apply the
best one automatically. Flat discounts like FLAT5 can be combined with a percentage code.
Codes cannot be applied after an order is placed.
""",
    },
    {
        "slug": "price-adjustments",
        "title": "Price adjustments",
        "updated": "2026-04-04",
        "status": "current",
        "body": """
If an item you bought drops in price on Shopfront within **14 days of your order**, we will refund
the difference once per item. We do not match competitors' prices. Price adjustments are not
available for clearance items or during the first 48 hours of a sale.
""",
    },
    {
        "slug": "gift-cards",
        "title": "Gift cards",
        "updated": "2026-01-15",
        "status": "current",
        "body": """
Shopfront gift cards never expire and can be used on any order. Gift cards are **not refundable**
and cannot be exchanged for cash, except where the law requires it. Lost gift cards can be
replaced if you have the original order number.
""",
    },
    {
        "slug": "warranty",
        "title": "Warranty coverage",
        "updated": "2026-02-20",
        "status": "current",
        "body": """
Warranty periods by category, counted from delivery:

- Electronics accessories (chargers, cables, power banks): **1 year**.
- Lighting: **2 years**.
- Outdoor gear (tents, packs, stoves): **2 years**, excluding wear and tear.
- Home office furniture: **5 years** on frames, 1 year on motors and electronics.
- Kitchen: **lifetime** on cast iron; 1 year on everything else.

Warranty claims are handled by a team member. Include your order number and a description or
photo of the fault. Misuse, accidents and normal wear are not covered.
""",
    },
    {
        "slug": "payment-methods",
        "title": "Payment methods",
        "updated": "2026-05-01",
        "status": "current",
        "body": """
We accept Visa, Mastercard, American Express, PayPal, Apple Pay and Shopfront gift cards. Your
card is charged when the order ships, not when you place it. Refunds always go back to the
original payment method; we cannot refund to a different card.
""",
    },
    {
        "slug": "account-help",
        "title": "Account and password help",
        "updated": "2026-05-01",
        "status": "current",
        "body": """
To reset your password, use "Forgot password" on the sign-in page. Shopfront staff and our
assistant will **never ask for your password** or full card number.

If you created two accounts with the same email in different capitalisation (for example
Jane@x.com and jane@x.com), contact us and we will merge them.
""",
    },
    {
        "slug": "privacy",
        "title": "Privacy and your data",
        "updated": "2026-07-30",
        "status": "current",
        "body": """
We only discuss an order with the customer who placed it. Our assistant can see your orders
and account details but will not share anything about other customers, and it will not send
your information to any email address other than the one on your account.

You can request a copy of your data or ask us to delete your account at any time.
""",
    },
    {
        "slug": "contact",
        "title": "Contacting support",
        "updated": "2026-05-01",
        "status": "current",
        "body": """
Our assistant is available 24/7 in the chat window. Human support works Monday to Friday,
9am to 6pm Eastern. Escalated requests receive a reply within one business day.
""",
    },
    {
        "slug": "cast-iron-care",
        "title": "Caring for cast iron cookware",
        "updated": "2026-03-01",
        "status": "current",
        "body": """
Cast iron develops a protective layer of polymerised oil called **seasoning**. Oxidation
(orange spots) appears if the pan is left wet or soaked.

To restore a pan with oxidation: scrub the affected area with steel wool, rinse, dry completely
on low heat, rub a thin film of neutral oil over every surface and bake upside down at 230°C
(450°F) for one hour. Repeat for a darker finish. This **re-seasoning** process is normal
maintenance and is not a defect covered by warranty.

Never put cast iron in the dishwasher.
""",
    },
    {
        "slug": "tent-care",
        "title": "Tent care and waterproofing",
        "updated": "2026-04-18",
        "status": "current",
        "body": """
Always dry your tent fully before storing it; packing it wet causes mildew and delamination of
the coating. To refresh water repellency, clean the fly with a non-detergent tech wash, then
apply a DWR (durable water repellent) spray while damp. Seam sealer should be reapplied every
2 to 3 seasons. Leaks at seams after heavy use are wear and tear, not a manufacturing defect.
""",
    },
    {
        "slug": "standing-desk-setup",
        "title": "Standing desk assembly and troubleshooting",
        "updated": "2026-06-22",
        "status": "current",
        "body": """
Assembly takes about 40 minutes with two people. If the desk stops moving or shows an error code
on the controller, unplug it for 30 seconds, then hold the DOWN button for 10 seconds until it
beeps to reset the height memory. Error code E2 means the legs are out of sync; E5 means the
motor overheated and needs 20 minutes to cool. Weight limit: 120 kg.
""",
    },
    {
        "slug": "led-bulbs",
        "title": "LED bulb compatibility and flicker",
        "updated": "2026-02-02",
        "status": "current",
        "body": """
Our dimmable LED bulbs work with trailing-edge (ELV) dimmers. Older leading-edge dimmers can
cause flicker or buzzing. If a bulb flickers, check the dimmer type before reporting a defect.
Non-dimmable bulbs must not be used on dimmer circuits.
""",
    },
    {
        "slug": "battery-safety",
        "title": "Battery safety for power banks",
        "updated": "2026-08-01",
        "status": "current",
        "body": """
Stop using any power bank that is swollen, hot to the touch while idle, or smells of chemicals.
Do not charge it again and do not throw it in household trash; take it to a battery recycling
point. Contact support for a replacement: swollen batteries are always treated as a defect
regardless of the 60-day damaged-item window, within the 1-year warranty.
""",
    },
]
