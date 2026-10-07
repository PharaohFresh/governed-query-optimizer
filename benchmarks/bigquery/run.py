"""Bounded, read-only public-data experiment; never stages or approves a SQL change."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import statistics
from uuid import uuid4

HERE = Path(__file__).resolve().parent
PROJECT = 'career-analytics-portfolio'
MAX_BYTES = 100_000_000
MAX_ROWS = 100_000
ORDER = ('original', 'preaggregate', 'preaggregate', 'original', 'original', 'preaggregate')


def typed_rows(rows):
    result = Counter()
    count = 0
    for row in rows:
        count += 1
        if count > MAX_ROWS:
            raise ValueError('Result exceeds comparison row budget')
        values = tuple(row)
        if any(value is not None and type(value) is not int for value in values):
            raise ValueError('Unexpected benchmark output type')
        result[tuple(('null', None) if value is None else ('int', value) for value in values)] += 1
    if not count:
        raise ValueError('Empty cohort cannot establish useful equivalence')
    return result


def digest(multiset):
    canonical = sorted((json.dumps(row), count) for row, count in multiset.items())
    return hashlib.sha256(json.dumps(canonical, separators=(',', ':')).encode()).hexdigest()


def summarize(samples):
    summaries = {}
    for name in ('original', 'preaggregate'):
        jobs = [sample for sample in samples if sample['query'] == name]
        if len(jobs) != 3 or any(job['cache_hit'] is not False for job in jobs):
            raise ValueError('Three uncached samples per query are required')
        summaries[name] = {metric: statistics.median(job[metric] for job in jobs)
                           for metric in ('bytes_processed', 'bytes_billed', 'slot_ms', 'execution_ms')}
    a, b = summaries['original'], summaries['preaggregate']
    summaries['interpretation'] = {
        'processed_bytes_reduction_fraction': 1 - b['bytes_processed'] / a['bytes_processed'] if a['bytes_processed'] else None,
        'execution_median_ratio_candidate_over_original': b['execution_ms'] / a['execution_ms'] if a['execution_ms'] else None,
        'scope': 'Observed public-data experiment; three samples per query, not a production speedup or realized savings claim',
    }
    return summaries


def run(output):
    # Reserve the destination before starting any billed jobs. Preserve complete evidence.
    output.mkdir(parents=True, exist_ok=False)
    snapshot = datetime.now(timezone.utc) - timedelta(minutes=2)
    report = dict(evidence_type='measured BigQuery jobs on public data', snapshot_time=snapshot.isoformat(),
                  measurement_started_at=datetime.now(timezone.utc).isoformat(), execution_project=PROJECT,
                  location='US', library_version=None, requested_server_timeout_ms=120_000,
                  cohort='Order-created date from 2026-02-01 inclusive through 2026-05-01 exclusive',
                  maximum_bytes_billed_per_job=MAX_BYTES, maximum_execution_jobs=len(ORDER),
                  query_sha256={}, dry_runs={}, execution_jobs=[], samples=[], complete=False)
    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    save()
    try:
        from google.cloud import bigquery
        report['library_version'] = bigquery.__version__
        parameters = [bigquery.ScalarQueryParameter('snapshot_time', 'TIMESTAMP', snapshot)]
        client = bigquery.Client(project=PROJECT)
        queries = {name: (HERE / f'{name}.sql').read_text(encoding='utf-8') for name in ('original', 'preaggregate')}
        report['query_sha256'] = {name: hashlib.sha256(sql.encode()).hexdigest() for name, sql in queries.items()}
        save()
        for name, sql in queries.items():
            config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=parameters)
            job = client.query(sql, location='US', job_config=config, job_retry=None)
            estimate = job.total_bytes_processed
            if type(estimate) is not int or estimate > MAX_BYTES:
                raise ValueError('Dry-run estimate unavailable or exceeds bounded experiment')
            report['dry_runs'][name] = dict(estimated_bytes_processed=estimate, evidence_type='warehouse dry-run estimate')
            save()
        reference, schema = None, None
        for name in ORDER:
            config = bigquery.QueryJobConfig(use_query_cache=False, query_parameters=parameters,
                maximum_bytes_billed=MAX_BYTES, job_timeout_ms=120_000, labels={'portfolio': 'optimizer-benchmark'})
            job_id = 'portfolio_optimizer_' + uuid4().hex
            execution = dict(query=name, job_id=job_id, state='SUBMISSION_UNCONFIRMED', comparison='pending')
            report['execution_jobs'].append(execution)
            save()
            job = client.query(queries[name], location='US', job_config=config, job_retry=None, job_id=job_id)
            execution['state'] = job.state
            save()
            def read_stats():
                execution.update(state=job.state, cache_hit=job.cache_hit,
                    bytes_processed=job.total_bytes_processed, bytes_billed=job.total_bytes_billed,
                    slot_ms=job.slot_millis,
                    started_at=job.started.isoformat() if job.started else None,
                    ended_at=job.ended.isoformat() if job.ended else None,
                    execution_ms=(job.ended-job.started).total_seconds()*1000 if job.ended and job.started else None)
                save()
            try:
                rows = job.result(timeout=150)
                read_stats()
                contract = [(field.name, field.field_type, field.mode) for field in rows.schema]
                execution['schema'] = contract
                save()
                values = typed_rows(rows)
                if reference is None:
                    reference, schema = values, contract
                if values != reference or contract != schema:
                    raise ValueError('Benchmark output multiset or column contract changed')
                if job.statement_type != 'SELECT' or job.cache_hit is not False:
                    raise ValueError('Only uncached read-only SELECT jobs count as measurement')
                execution.update(row_count=sum(values.values()), result_multiset_sha256=digest(values),
                                 comparison='equivalent')
                save()
                sample = {key: execution[key] for key in ('query','job_id','cache_hit','bytes_processed',
                          'bytes_billed','slot_ms','execution_ms','row_count','result_multiset_sha256')}
                sample['equivalent'] = True
                if any(sample[field] is None or sample[field] < 0 for field in ('bytes_processed','bytes_billed','slot_ms','execution_ms')):
                    raise ValueError('Incomplete job statistics')
            except Exception as exc:
                execution.update(comparison='failed', failure_type=type(exc).__name__)
                save()
                try:
                    execution['cancellation_requested'] = job.cancel()
                    job.reload()
                    read_stats()
                except Exception as recovery:
                    execution['readback_failure_type'] = type(recovery).__name__
                    save()
                raise
            report['samples'].append(sample)
            save()
        report.update(schema=schema, summary=summarize(report['samples']), complete=True,
                      measurement_completed_at=datetime.now(timezone.utc).isoformat())
        save()
        print(json.dumps(report['summary'], indent=2))
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        report['measurement_finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
        raise
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.output)
