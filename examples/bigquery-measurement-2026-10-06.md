# Native BigQuery result: equivalent answers, no observed scan reduction

The [complete raw report](bigquery-report-2026-10-06.json) comes from [the hosted public experiment](https://github.com/PharaohFresh/analytics-engineering-portfolio/actions/runs/37569217037), using optimizer source commit `feedca9ae2d88db6d9718bed6c7d26f6f8048937`. Measurement completed October 7 at 03:58:49 UTC (October 6 in Austin); SDK 3.42.1, US location, personal portfolio execution project. The report records the earlier common time-travel snapshot, both query hashes and six actual job IDs.

Every uncached result contains **10,123 rows**, with the same typed multiset digest and column name/type/mode contract. All six jobs pass the comparator. This establishes the observed cohort result for this fixed pair and snapshot, not universal equivalence.

| Median of three uncached jobs | Original join/aggregate | Preaggregate then join |
|---|---:|---:|
| Bytes processed | 5,894,360 | 5,894,360 |
| Bytes billed | 20,971,520 | 20,971,520 |
| Execution time | 288 ms | 285 ms |
| Slot milliseconds | 76 | 120 |

The rewrite has **zero observed scan reduction**. A 3 ms median execution difference in three samples does not establish a dependable speedup; slot use was higher. These results do not substantiate realized savings or a production performance gain. They are useful evidence precisely because the candidate must earn its benefit, even after correctness passes.

Dry-run estimates remain separate from actual job measurements in the raw report. Monetary results round each public item to integer cents. No public row-level result, employer SQL/data or private credential is exported. This experiment does not approve or deploy a query.

Two earlier native dry runs failed on SQL alias placement and the raw orders key name before any execution jobs ran. The corrected successful run is identified above; failures are retained in their original workflow artifacts, not relabeled as success. New executions choose new snapshots and may produce different data or timing. Read the [method and boundaries](../benchmarks/bigquery/README.md) before interpreting the numbers.
