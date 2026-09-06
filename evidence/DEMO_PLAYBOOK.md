# Ripple demo playbook (judges)

Target length: 6 minutes talk + 2 minutes Q&A. Everything below was dry-run on 6 Sep 2026 from
branch `ripple-next` (56 tests pass; local reviews take 1-4 s; the live Databricks comparison
took 63 s with a warm warehouse).

## 0. Known trap: `main` is still broken

`origin/main` still holds the conflict-mangled `pipeline/transactions.py` (PRs #2-#4 merged the demo
branches into it). `python3 -m ripple review --base main ...` therefore exits 3 with
`SyntaxError: unterminated triple-quoted string literal (detected at line 74)`.

Two options, pick one before the demo:

1. **Preferred:** merge the `ripple-next` PR into `main` on GitHub, then `git checkout main && git pull`.
   Every command below then works with `--base main`.
2. **No time to merge:** stay on `ripple-next` and use `--base 268c4ec` (the restored pipeline commit,
   which is also the merge-base of `demo/abs-normalize`). All commands below use this form.

If a judge asks why the base is a SHA: "main on GitHub was damaged by merging the demo branches; the fix
is on the branch you are looking at, and the review card actually catches the broken file (exit 3,
NEEDS-VERIFICATION) instead of hiding it." Show it live if there is time, it is a good story.

## 1. Pre-flight (T minus 15 minutes)

```bash
cd "/Users/hinalbagrecha/Sourabh Projects/buildathon/buildathon-2026"
git checkout ripple-next && git status --short          # only the evidence/ripple_overview.* files untracked
git worktree prune && git worktree list                 # exactly one entry
python3 -m unittest discover -s tests 2>&1 | tail -2    # "Ran 56 tests ... OK"

databricks current-user me | head -3                    # auth works ("active": true)
databricks warehouses start c9a0bd38022ced72            # warm the warehouse (cold start is about 1 min)
databricks warehouses get c9a0bd38022ced72 | grep state # "RUNNING"

# warm-up run: fills the Delta tables with a fresh run_id and proves the live path works today
python3 -m ripple review --base 268c4ec --head demo/abs-normalize --backend databricks \
  --out /tmp/ripple_warmup.md ; echo "exit=$?"          # exit=1 (BLOCK) after about 60 s
grep -E "run_id|statement ids" /tmp/ripple_warmup.md    # copy the run_id for the SQL re-query in step 5
```

Also prepare:

- Terminal: font 18pt+, one wide window, `clear` before starting. Second terminal tab ready for the
  long Databricks command (step 5) so it can run while you talk.
- Browser tabs: (a) Databricks workspace SQL editor, logged in; (b) the job run URL from
  `evidence/review_card_demo_databricks_job.md` (run 43140873411386, serverless, SUCCESS, 52.1 s);
  (c) the GitHub repo on branch `ripple-next`.
- Slides: `evidence/ripple_overview.pdf` open in Preview (15 slides). Use slides 1-3 for the hook, then
  switch to the terminal. Come back to the "limits" slide only if asked.
- Fallback cards open in the editor (do not close them): `evidence/review_card_demo.md`,
  `evidence/review_card_demo_databricks_job.md`, `evidence/review_card_dynamic.md`,
  `evidence/review_card_dynamic_safe.md`.
- Phone/laptop hotspot as backup network for Databricks.

## 2. The script

### Minute 0-1: hook (slides 1-3)

"A data engineer, or an agent, edits a small helper: 'normalize transaction amounts'. The diff is four
lines. Tests pass. Daily revenue goes up 30 percent, because refunds stopped being negative. Git shows
what changed. Nothing shows which data products changed meaning, by how much, and whether that
contradicts the original intent. Ripple answers those three questions in one review card."

Track: "Track 2, Graph Intelligence. Entire Graph finds what the change reaches, Entire Checkpoints hold
the intent, Databricks executes and compares both versions over the same snapshot."

### Minute 1-2: show the change and the intent

```bash
git diff 268c4ec demo/abs-normalize -- pipeline/transactions.py
cat pipeline/INTENT.md
```

Say: "abs() on the magnitude and abs() on the refund. Looks like cleanup. The intent file, backed by an
Entire checkpoint, says refunds must remain negative."

### Minute 2-3.5: the main review, local (3 seconds)

```bash
python3 -m ripple review --base 268c4ec --head demo/abs-normalize
echo "exit=$?"     # 1 = BLOCK; this is the CI gate
```

Walk the card top to bottom, pointing:

1. **Verdict** BLOCK and the evidence line: analysis `complete`, 4 confirmed relations, 0 heuristic.
2. **Section 1, intent**: requirement text, source file, checkpoint id.
3. **Section 2, Entire Graph**: changed function `normalize_amount` at line 13 (from `entire graph diff`),
   callers `clean_transactions` depth 1 and `run` depth 2 with call-site lines (from `entire graph
   impact`). "Every edge is labelled: confirmed means a structural CALLS edge with a recorded call site.
   Graph output is evidence, not an oracle, so the label travels onto the card."
4. **Section 3, data products**: entry point to job to tables to "Daily Revenue dashboard" and the
   month-end close extract. "This mapping is configured in ripple.toml and labelled as such; we never
   pretend the graph discovered it."
5. **Section 4, comparison**: 33 of 150 rows changed (exactly the refunds), 13 of 14 days changed, net
   revenue 13854.10 to 18033.82. Sign flips shown row by row.

Optional one-liner: "The graph analysed the head branch in a temporary worktree, so I never left this
checkout." (The card says so in the Evidence line.)

### Minute 3.5-5: Databricks, the reproducible part

Start this in the second terminal tab as soon as step 3 finishes, then talk while it runs (about 60 s):

```bash
python3 -m ripple review --base 268c4ec --head demo/abs-normalize --backend databricks \
  --out evidence/review_card_live.md ; echo "exit=$?"
```

While it runs, show the pre-run job card `evidence/review_card_demo_databricks_job.md` and the browser
tab with the serverless job run: "With `--execute databricks` both versions of the pipeline run inside a
serverless one-time job over the Delta snapshot and write both outputs through Spark. The comparison
is SQL on the warehouse, every statement id is on the card, and the run is tagged with a run_id."

When the live command finishes, scroll to the Databricks block: rows differing 33, totals, the run_id,
the three statement ids. Then re-query in the SQL editor (paste the run_id from the card):

```sql
SELECT version, ROUND(SUM(net_revenue), 2) AS net_revenue, COUNT(*) AS days
FROM workspace.ripple.daily_revenue
WHERE run_id = '<run_id from the card>'
GROUP BY version;
```

Say: "The BLOCK decision is a SQL result a reviewer can re-run. Unity Catalog lineage is queried too and
shown as observed, separately labelled; it never replaces the configured mapping."

If the warehouse is slow or down: skip the live run, show `evidence/review_card_demo_databricks_job.md`
and `evidence/databricks/last_run.json`, and say the card falls back to the local comparison and says so
in Notes.

### Minute 5-6.5: the Curveball, graph is evidence not oracle

"Now the same regression in a pipeline that dispatches through a string registry and globals(). The
graph reports zero callers and completeness ok. It does not know it missed anything."

```bash
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-abs ; echo "exit=$?"
```

Point at: the **partial-analysis banner** (registry line, `globals()` line), the line "absence of callers
is not evidence of safety", the entry point marked `[fallback (graph did not reach it)]`, and BLOCK with
the same 33 rows. "Safe fallback is execute anyway. PASS on graph evidence alone is impossible when
analysis is partial."

Then the behaviour-preserving refactor on the same dynamic pipeline:

```bash
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-safe ; echo "exit=$?"
```

Verdict "PASS ... verified by execution; graph analysis partial". "Same banner, same fallback, zero rows
changed, exit 0. Fully resolved code is unaffected: the first card had no banner and four confirmed edges."

Control case if time allows (1 second):

```bash
python3 -m ripple review --base 268c4ec --head 268c4ec ; echo "exit=$?"    # PASS, exit 0
```

### Minute 6.5-7: close

- Exit codes 0 PASS, 1 BLOCK, 3 NEEDS-VERIFICATION, 2 graph error: "drop it in CI as a gate".
- 56 tests, stdlib only, no pip dependencies, fixtures include real graph output for the dynamic case.
- Five Entire checkpoints in `BUILDATHON.md`, each with the commit and the semantic diff
  (`entire graph diff`) it proves. Show `evidence/graph/` if a judge wants raw JSON.

## 3. Likely questions

- **Why configure the mapping instead of discovering it?** Explicit and inspectable. Lineage from Unity
  Catalog is shown next to it as observed evidence, but lineage only sees consumers that ran a query in
  the last 30 days, so the configured mapping stays the contract.
- **Why not run every pipeline on every change?** The graph narrows it to reachable entry points. When the
  graph is partial, Ripple runs the configured entry points it could not reach. That is the fallback,
  and it is bounded by the configuration.
- **What does the graph get wrong?** Real examples on the card and in BUILDATHON.md: dynamic dispatch
  gives 0 callers with completeness ok; a module-alias call (`cardmod.decide`) was missed. Hence the
  tri-state labels and the Ripple-side AST scan for string constants plus reflection.
- **Is the data real?** Synthetic, seed 2026, 150 rows, generator checked in. No personal data.
- **Scale?** Inserts are literal VALUES (fine for 150 rows, not millions); the Databricks job embeds a
  single entry file. Both are listed under limitations with the next step.
- **Why is base a SHA / why is main broken?** See section 0. Ripple caught the broken file as
  NEEDS-VERIFICATION (exit 3); demo it in 4 seconds if asked:
  `python3 -m ripple review --base main --head demo/abs-normalize`.

## 4. If something breaks

| Symptom | Do this |
|---|---|
| `exit=2` graph error | `entire graph diff --base 268c4ec --head demo/abs-normalize --json` to show the raw call; if the CLI is down, show `evidence/graph/*.json` and the checked-in cards. |
| Databricks auth or warehouse error | Card already fell back to local and says so in Notes. Show `evidence/review_card_demo_databricks_job.md` and the job run URL in the browser. |
| Command hangs on `entire checkpoint search` | Add `--no-entire-checkpoint` (intent still comes from `pipeline/INTENT.md`). |
| Leftover worktree after an interrupted run | `git worktree prune`. |
| Lineage lookup slow | Add `--no-lineage`. |
| Wrong branch checked out | `git checkout ripple-next`; the demo never needs another checkout. |

Cheat sheet of every command, in order:

```bash
git diff 268c4ec demo/abs-normalize -- pipeline/transactions.py
python3 -m ripple review --base 268c4ec --head demo/abs-normalize
python3 -m ripple review --base 268c4ec --head demo/abs-normalize --backend databricks --out evidence/review_card_live.md
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-abs
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-safe
python3 -m ripple review --base 268c4ec --head 268c4ec
python3 -m ripple review --base main --head demo/abs-normalize        # only if asked about main
```
