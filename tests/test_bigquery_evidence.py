import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / 'benchmarks/bigquery/run.py'
SPEC = importlib.util.spec_from_file_location('benchmark', PATH)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_multiset_keeps_duplicate_null_and_contract_types():
    assert benchmark.typed_rows([(1, None), (1, None)]) != benchmark.typed_rows([(1, None)])
    assert benchmark.typed_rows([(1, None), (2, 9)]) == benchmark.typed_rows([(2, 9), (1, None)])
    for rows in ([], [(True, 2)], [(1, 2.0)]):
        with pytest.raises(ValueError):
            benchmark.typed_rows(rows)


def test_bounded_comparison(monkeypatch):
    monkeypatch.setattr(benchmark, 'MAX_ROWS', 1)
    with pytest.raises(ValueError):
        benchmark.typed_rows([(1,), (2,)])


def samples():
    return [dict(query=name, cache_hit=False, bytes_processed=100, bytes_billed=1000,
                 slot_ms=50, execution_ms=100+i) for i, name in enumerate(benchmark.ORDER)]


def test_no_false_byte_savings_and_distinct_billed_bytes():
    summary = benchmark.summarize(samples())
    assert summary['interpretation']['processed_bytes_reduction_fraction'] == 0
    assert summary['original']['bytes_billed'] == 1000
    assert summary['original']['execution_ms'] == 103


def test_cached_or_incomplete_experiments_fail():
    changed = samples()
    changed[0]['cache_hit'] = True
    with pytest.raises(ValueError):
        benchmark.summarize(changed)
    with pytest.raises(ValueError):
        benchmark.summarize(samples()[:-1])


def test_queries_use_same_snapshot_cohort_and_preserve_outer_join():
    for name in ('original', 'preaggregate'):
        sql = (PATH.parent / f'{name}.sql').read_text(encoding='utf-8')
        assert '@snapshot_time' in sql
        assert "DATE '2026-02-01'" in sql and "DATE '2026-05-01'" in sql
        assert 'LEFT JOIN' in sql
        assert 'DELETE' not in sql and 'CREATE' not in sql


class Rows(list):
    schema = [SimpleNamespace(name='order_id', field_type='INTEGER', mode='NULLABLE'),
              SimpleNamespace(name='customer_id', field_type='INTEGER', mode='NULLABLE'),
              SimpleNamespace(name='revenue_cents', field_type='INTEGER', mode='NULLABLE')]


class Job:
    state = 'DONE'
    cache_hit = False
    statement_type = 'SELECT'
    total_bytes_processed = 100
    total_bytes_billed = 1000
    slot_millis = 20
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ended = started + timedelta(milliseconds=10)
    def __init__(self, number, fail=None):
        self.job_id = f'fake-job-{number}'
        self.number, self.fail = number, fail
    def result(self, **kwargs):
        if self.fail == 'timeout':
            raise TimeoutError('Simulated timeout')
        return Rows([(1, 2, 30 if self.fail != 'mismatch' else 31)])
    def cancel(self):
        return True
    def reload(self):
        return None


def fake_cloud(monkeypatch, fail=None):
    cloud, google, module = ModuleType('google.cloud'), ModuleType('google'), ModuleType('google.cloud.bigquery')
    class Client:
        executions = 0
        def __init__(self, **kwargs):
            if fail == 'credentials':
                raise RuntimeError('Simulated unavailable credentials')
        def query(self, sql, *, job_config, **kwargs):
            if getattr(job_config, 'dry_run', False):
                return SimpleNamespace(total_bytes_processed=benchmark.MAX_BYTES+1 if fail == 'cap' else 100)
            self.executions += 1
            if fail == 'submission' and self.executions == 2:
                raise RuntimeError('Simulated ambiguous submission response')
            job = Job(self.executions, fail if self.executions == 2 else None)
            job.job_id = kwargs['job_id']
            return job
    module.Client = Client
    module.__version__ = 'fake-sdk-for-offline-failure-tests'
    module.QueryJobConfig = SimpleNamespace
    module.ScalarQueryParameter = lambda *args: args
    cloud.bigquery = module
    google.cloud = cloud
    for name, value in [('google',google),('google.cloud',cloud),('google.cloud.bigquery',module)]:
        monkeypatch.setitem(sys.modules, name, value)


@pytest.mark.parametrize('failure', ['credentials', 'mismatch', 'timeout', 'cap', 'submission'])
def test_failed_experiment_retains_partial_report_and_started_jobs(tmp_path, monkeypatch, failure):
    fake_cloud(monkeypatch, failure)
    output = tmp_path / 'experiment'
    with pytest.raises((ValueError, TimeoutError, RuntimeError)):
        benchmark.run(output)
    report = json.loads((output / 'report.json').read_text())
    assert report['complete'] is False
    assert 'failure_type' in report
    if failure in ('mismatch', 'timeout'):
        assert len(report['execution_jobs']) == 2
        assert report['execution_jobs'][-1]['job_id'].startswith('portfolio_optimizer_')
        assert report['execution_jobs'][-1]['comparison'] == 'failed'
        assert report['execution_jobs'][-1]['cancellation_requested'] is True
    elif failure == 'submission':
        assert len(report['execution_jobs']) == 2
        assert report['execution_jobs'][-1]['state'] == 'SUBMISSION_UNCONFIRMED'
        assert report['execution_jobs'][-1]['job_id'].startswith('portfolio_optimizer_')
    else:
        assert report['execution_jobs'] == []


def test_unreadable_sql_retains_failed_report(tmp_path, monkeypatch):
    fake_cloud(monkeypatch)
    monkeypatch.setattr(benchmark, 'HERE', tmp_path)
    with pytest.raises(FileNotFoundError):
        benchmark.run(tmp_path / 'experiment')
    report = json.loads((tmp_path / 'experiment/report.json').read_text())
    assert report['complete'] is False
    assert report['failure_type'] == 'FileNotFoundError'
