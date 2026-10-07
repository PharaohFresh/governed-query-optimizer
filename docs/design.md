# Query verification and staging design

## Result contract

The evaluator compares an ordered tuple of column names and an unordered multiset of typed rows. Every value is tagged as integer, float, text or null. Float values use their exact binary representation; non-finite values are rejected. The example financial measures use integer cents, so their arithmetic is exact.

This contract permits result-row reordering. It does not prove the same sequence for an ordered report or top-N consumer. Duplicate output names are rejected because they make the downstream contract ambiguous. Equal empty outputs still have to preserve their column names; no type is inferred for an empty column.

Both queries read the same in-memory source. Differences retain occurrence counts and at most five example rows in each direction. A distinct-set comparison would miss repeated values removed by an unsafe `DISTINCT` rewrite.

## Execution boundary

Trusted packaged seed SQL creates the two fixture tables before the authorizer is installed. Candidate execution allows SELECT/recursive query evaluation, reads from `orders` and `order_items`, and the documented function allowlist. Other SQLite actions are denied. An execution-time progress handler and a result-size cap bound evaluation.

The authorizer is removed after each query so a failed candidate does not poison later evaluations. No extensions are loaded and no functions with external side effects are registered. This is a local fixture boundary, not a production multi-tenant sandbox.

## Cost evidence

Each case contains integer original/candidate byte estimates and a 50 percent demonstration threshold. The estimates are invented inputs to a policy test. They are not derived from SQLite runtime, EXPLAIN plans or provider billing. Negative and non-finite policy inputs fail.

Workload intake preserves one row per job ID, excludes child jobs to avoid counting both script-parent and child work, and groups on an explicitly supplied logical workload ID. Cadence and annual savings are deliberately absent. A real optimizer needs actual workload identity, recurrence and billing evidence before projecting savings.

## Content-bound staging

```text
evaluate -> eligible plan -> explicit local approval -> revalidate -> stage -> read back
              |
              +-> blocked candidates cannot produce a plan
```

The plan embeds the full candidate, evaluation and input hashes. Approval binds the canonical plan SHA-256. Before staging, the engine rebuilds the plan from the current packaged case and requires exact equality. It then checks the approval and writes a new output directory. The staged file hash must match the candidate bytes.

Existing evidence directories and approval files are not overwritten. A stale or modified plan must be reviewed again. This demonstrates binding between a reviewed change and execution; caller-supplied approver text is not authenticated identity.

## Adapting to an enterprise warehouse

Decide the business cohort and output contract first. Fix the source snapshot or compare inside a consistent read window. Preserve nulls and multiplicity. If numeric tolerance is required, make the unit, absolute/relative bound and business justification explicit. Compare actual target-dialect output and use dry-run estimates plus observed job statistics without mixing their meanings. Keep proposal, approval and deployment records independently verifiable.

Provider documentation for the mechanisms used here: [Python SQLite authorizer and progress handler](https://docs.python.org/3/library/sqlite3.html), [SQLite authorizer actions](https://www.sqlite.org/c3ref/set_authorizer.html).
