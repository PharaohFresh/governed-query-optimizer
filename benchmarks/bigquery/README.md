# Measured public BigQuery experiment

The offline lab uses explicitly modeled fixture costs. This separate adapter measures two fixed, read-only SQL queries on Google's public theLook ecommerce dataset. It tests whether preaggregating order-item cents before an outer join changes observed bytes, slot time or execution time **without changing the typed result multiset**.

Both queries use the same `FOR SYSTEM_TIME AS OF` timestamp for every source table and repetition. Both select the same February-April 2026 order-created cohort. The candidate preserves itemless orders and null totals and does not shorten the item date range. Six jobs alternate original/candidate order; every result is compared to the first original result, including repeated originals. No source rows are written or staged.

## Run and inspect

```text
python -m pip install -e ".[bigquery]"
python benchmarks/bigquery/run.py --output artifacts/bigquery-experiment
```

Supply portfolio-authorized Application Default Credentials. The runner deliberately fixes the execution project to `career-analytics-portfolio`, the personal portfolio project. It never falls back to a default Cloud project. The warehouse companion's manual benchmark workflow uses its existing portfolio CI service-account secret; this repo does not need a copied secret. Do not use an unrelated business Cloud identity.

Each query is dry-run first. If either estimate is missing or above 100,000,000 bytes, no execution jobs run. Execution permits at most six jobs, each with that billing cap and disabled query cache. It requests a 120-second server timeout; the provider treats this as best-effort. The client waits up to 150 seconds for results and attempts cancellation/readback on failure. Comparison allows at most 100,000 rows. The output directory is reserved before execution and cannot overwrite earlier evidence. A failure retains a partial report marked `complete: false`, including submitted job IDs and any available statistics.

Complete reports record measurement start/end UTC, the execution project/location, SDK version and source snapshot. Failed runs retain the client-side finish timestamp; remote completion can remain unknown. Job IDs are recorded before submission, so a lost response remains traceable as SUBMISSION_UNCONFIRMED. A new run selects a new snapshot; historical reruns are possible only while the tables retain that timestamp within their configured time-travel window. Public-source regeneration or later data changes can alter new results. The requested timeout and cancellation attempt do not guarantee that a remote job has stopped; partial evidence records the observed state.

The report separates:

- **Dry-run estimates:** actual warehouse estimates, not measured execution bytes.
- **Per-job measurements:** processed/billed bytes, slot milliseconds, execution duration, cache flag and job ID.
- **Correctness:** column name/type contract, typed duplicate-sensitive result digest and row count for every repetition.
- **Summary:** median of three samples per query, processed-byte reduction and candidate/original execution-time ratio.

The raw public result rows are compared in memory and not exported; only their typed multiset digest and count appear in the report. Monetary query values round per item to integer cents before summing. This experiment is separate from the local approval/staging policy: a successful run does not approve a rewrite or deploy a cloud object.

## Interpret the evidence

The warehouse optimizer may produce similar plans for both queries. Equal byte scans are a valid result; a faster median in three runs does not establish a general speedup. Billing can differ from bytes processed because of billing minimums. Slot use and execution time vary with shared capacity, query compilation and engine conditions. No annual savings, invoice reduction, production workload performance or universal SQL equivalence follows from this experiment.

Actual result reports are retained as artifacts of the [companion workflow](https://github.com/PharaohFresh/analytics-engineering-portfolio/actions/workflows/optimizer-benchmark.yml). A committed result snapshot, if present, must be marked complete and identify its measurement timestamp, query hashes, public-data snapshot and raw jobs. Do not replace a failed or unrun experiment with synthetic measurements.

Provider references: [estimate and control query costs](https://docs.cloud.google.com/bigquery/docs/best-practices-costs), [time travel queries](https://docs.cloud.google.com/bigquery/docs/access-historical-data).
