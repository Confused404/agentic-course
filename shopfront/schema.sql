-- Shopfront schema. SQLite. Money is always integer cents (never floats; see nodes/03 seeded bugs for why).
-- Timestamps are ISO-8601 UTC strings. The data is deliberately a little messy (see FIXTURES.md).

CREATE TABLE IF NOT EXISTS customers (
  id          INTEGER PRIMARY KEY,
  email       TEXT NOT NULL,            -- NOT unique on purpose: real data has case-duplicates
  name        TEXT NOT NULL,
  tier        TEXT NOT NULL DEFAULT 'standard',  -- 'standard' | 'plus'
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id           INTEGER PRIMARY KEY,
  sku          TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  category     TEXT NOT NULL,
  description  TEXT NOT NULL,          -- some contain stray HTML
  price_cents  INTEGER NOT NULL,
  stock        INTEGER NOT NULL,
  reorder_level INTEGER NOT NULL DEFAULT 5,
  active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
  id               INTEGER PRIMARY KEY,
  customer_id      INTEGER NOT NULL REFERENCES customers(id),
  status           TEXT NOT NULL,      -- messy casing in raw data: 'delivered', 'Delivered', 'DELIVERED'
  placed_at        TEXT NOT NULL,
  shipped_at       TEXT,               -- NULL if not shipped yet
  delivered_at     TEXT,               -- NULL if not delivered
  total_cents      INTEGER NOT NULL,
  shipping_address TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  order_id          INTEGER NOT NULL REFERENCES orders(id),
  product_id        INTEGER NOT NULL REFERENCES products(id),
  qty               INTEGER NOT NULL,
  unit_price_cents  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
  id           INTEGER PRIMARY KEY,
  order_id     INTEGER NOT NULL REFERENCES orders(id),
  amount_cents INTEGER NOT NULL,
  reason       TEXT NOT NULL,
  status       TEXT NOT NULL,          -- 'issued' | 'pending_approval' | 'denied'
  actor        TEXT NOT NULL,          -- who asked: 'agent:<name>' | 'human:<name>' | 'system'
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id           INTEGER PRIMARY KEY,
  product_id   INTEGER NOT NULL REFERENCES products(id),
  customer_id  INTEGER NOT NULL REFERENCES customers(id),
  rating       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  body         TEXT NOT NULL,          -- UNTRUSTED user content. Some reviews are adversarial (Node 08).
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
  id           INTEGER PRIMARY KEY,
  customer_id  INTEGER REFERENCES customers(id),
  subject      TEXT NOT NULL,
  body         TEXT NOT NULL,
  channel      TEXT NOT NULL,          -- 'email' | 'chat' | 'form'
  status       TEXT NOT NULL,          -- 'open' | 'escalated' | 'resolved'
  category     TEXT,                   -- filled in by your router in Node 09
  priority     TEXT,                   -- filled in by your router in Node 09
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emails_outbox (
  id          INTEGER PRIMARY KEY,
  to_addr     TEXT NOT NULL,
  subject     TEXT NOT NULL,
  body        TEXT NOT NULL,
  actor       TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

-- Every state-changing service call writes here. Evals grade THIS, not the agent's prose (Node 04 §3).
CREATE TABLE IF NOT EXISTS audit_log (
  id       INTEGER PRIMARY KEY,
  ts       TEXT NOT NULL,
  actor    TEXT NOT NULL,
  action   TEXT NOT NULL,
  payload  TEXT NOT NULL              -- JSON
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_refunds_order ON refunds(order_id);
-- The "one refund per order" invariant, enforced by the database itself. Even two parallel tool calls
-- racing past the eligibility check cannot both insert (services.issue_refund turns the error into POLICY).
CREATE UNIQUE INDEX IF NOT EXISTS one_live_refund_per_order ON refunds(order_id)
  WHERE status IN ('issued', 'pending_approval');
