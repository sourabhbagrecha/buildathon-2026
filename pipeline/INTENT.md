# Intent: transaction pipeline

**Requirement:** Refunds must remain negative. `normalize_amount` derives the sign of
an amount from the transaction kind: purchases positive, refunds negative. Daily net
revenue (`daily_revenue`) is `sum(amount)` per day and is only correct if this holds.

**Source of intent:** Entire checkpoint `01M1TVFK5MAS7B1JFN41QA2JQ8`
(Ripple product definition: "A checkpoint says refunds must remain negative").

**Downstream consumers:** `workspace.ripple.clean_transactions`,
`workspace.ripple.daily_revenue`, "Daily Revenue dashboard" (see `ripple.toml`).
