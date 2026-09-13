"""Real PG + ordinary chapter/worker/review path with explicit test-only models."""
import copy
import json
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / 'persistence', HERE.parent / 'read_api'):
    sys.path.insert(0, str(path))

import psycopg
import control_plane
import narrative_store as store
import narrative_stage
import studio_jobs
import studio_reviews
import history
import test_reading_pipeline_postgres as base
from test_narrative_contract import drafts
from common import LeaseLost, PersistenceConflict, PersistenceError
from read_common import ReadModelError, ReadModelNotFound
import resolve_publish
from migrations import apply_migrations


class NarrativeTestModel:
    name = 'explicit-narrative-test-model'
    def __init__(self):
        self.calls = []
        self.prompts = []
        self.context = None
    def complete(self, prompt):
        self.prompts.append(prompt)
        kind = prompt.split('\nSTAGE=')[1].split('\n')[0]
        context = json.loads(prompt.split('\nINPUT=')[1].split('\nAPPROVED_CONCLUSIONS=')[0])
        self.calls.append(kind)
        self.context = context
        facts, prose = drafts(context)
        prose["navigation"] = [{"label": "测试时段", "first_paragraph_id": prose["paragraphs"][0]["id"],
            "last_paragraph_id": prose["paragraphs"][-1]["id"], "items": [
                {"paragraph_id": p["id"], "label": "测试节点", "reason": "覆盖该测试来源的阅读位置。"} for p in prose["paragraphs"]]}]
        return json.dumps(facts if kind == 'facts' else prose, ensure_ascii=False)


class CorrectingTestModel(NarrativeTestModel):
    def complete(self, prompt):
        raw = super().complete(prompt)
        if len(self.calls) == 1:
            candidate = json.loads(raw)
            candidate['source_relations'][0]['left'] = self.context['sources'][0]['publication_id']
            return json.dumps(candidate, ensure_ascii=False)
        return raw


class RetryCorrectionTestModel(NarrativeTestModel):
    def complete(self, prompt):
        raw = super().complete(prompt)
        if len(self.calls) <= 6:
            candidate = json.loads(raw)
            candidate['source_relations'][0]['left'] = 'wrong-source-a' if len(self.calls) % 2 else 'wrong-source-b'
            self.failed_raw = json.dumps(candidate, ensure_ascii=False)
            return self.failed_raw
        return raw


class NarrativePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control_url = base._control_url()
    setUp = base.ReadingPipelinePostgresTests.setUp
    tearDown = base.ReadingPipelinePostgresTests.tearDown
    _queue_job = base.ReadingPipelinePostgresTests._queue_job
    _prepare_model = base.ReadingPipelinePostgresTests._prepare_model
    _run_once = base.ReadingPipelinePostgresTests._run_once

    def _start(self, correcting=False, narrative=None, expected_status='needs_review'):
        text = base.TEXT_DISTINCT
        job, revision, sha = self._queue_job(text)
        model, plan = self._prepare_model(text, revision, sha)
        unexpected = NarrativeTestModel()
        self.assertEqual('completed', self._run_once(job, text, sha, model, narrative_model=unexpected)[1])
        self.assertEqual([], unexpected.calls, 'chapter import must not implicitly regenerate the public history')
        with psycopg.connect(self.database_url) as conn:
            sources = store.list_source_choices(conn)
            status, _, body = studio_jobs.dispatch_jobs(conn, control_plane, method='POST',
                path='/api/v1/studio/jobs/history', body=json.dumps({
                    'catalog_sha': sources['catalog_sha'],
                    'publication_ids': [item['publication_id'] for item in sources['items']],
                }).encode())
            self.assertEqual(201, status, body)
            job = uuid.UUID(json.loads(body)['job']['job_id'])
        narrative = narrative or (CorrectingTestModel() if correcting else NarrativeTestModel())
        outcome = self._run_once(job, text, sha, model, narrative_model=narrative)
        if outcome[1] != expected_status:
            with psycopg.connect(self.database_url) as conn:
                self.fail(str(control_plane.get_job_detail(conn, job_id=job)))
        self.args = (job, text, sha, model)
        self.narrative = narrative
        return job

    def test_explicit_retry_continues_the_durable_failed_draft(self):
        model = RetryCorrectionTestModel()
        job = self._start(narrative=model, expected_status='failed')
        self.assertEqual(3, len(model.calls))
        with psycopg.connect(self.database_url) as conn:
            self.assertIsNone(store.read_candidate(conn, job, 'facts'))
            self.assertIsNone(store.read_last_attempt(conn, job_id=job, kind='facts', context={'different': True}))
            control_plane.retry_job(conn, job_id=job)
        self.assertEqual('failed', self._run_once(*self.args, narrative_model=model)[1])
        self.assertEqual(6, len(model.calls))
        with psycopg.connect(self.database_url) as conn:
            attempts = conn.execute("SELECT payload FROM chronicle.ingestion_outputs WHERE job_id=%s AND artifact_type='narrative-facts-attempt' ORDER BY created_at", (job,)).fetchall()
            self.assertEqual(list(range(1, 7)), [row[0]['attempt_sequence'] for row in attempts])
            self.assertEqual(model.failed_raw, store.read_last_attempt(conn, job_id=job, kind='facts', context=store.build_context(store.source_descriptors(conn), lambda _: (self.args[1], self.args[2])))['raw_response'])
            control_plane.retry_job(conn, job_id=job)
        self.assertEqual('needs_review', self._run_once(*self.args, narrative_model=model)[1])
        self.assertIn('PREVIOUS_CANDIDATE=' + model.failed_raw, model.prompts[-1])
        self.assertIn('source relationship must name two supplied source_id values', model.prompts[-1])
        original_input = json.loads(model.prompts[0].split('\nINPUT=')[1])
        self.assertEqual(original_input['sources'], model.context['sources'])
        with psycopg.connect(self.database_url) as conn:
            self.assertIsNone(store.read_publication(conn))
            self.assertEqual('open', store.read_candidate(conn, job, 'facts')['status'])

    def _approve(self, kind):
        with psycopg.connect(self.database_url) as conn:
            row = store.read_candidate(conn, self.args[0], kind)
            store.decide(conn, review_id=row['review_id'], candidate_sha=row['candidate_sha'],
                         decision='approve', rationale='测试明确人工审核门禁，非真实内容验收。',
                         reviewed_conclusion_ids=[f['id'] for f in row['candidate'].get('conclusions', [])])
            control_plane.resume_job(conn, job_id=self.args[0])

    def test_full_context_two_gates_and_fixed_publication(self):
        job = self._start(correcting=True)
        context = self.narrative.context
        self.assertEqual(2, len(context['sources']))
        for source in context['sources']:
            self.assertIn(source['chapter_text'], base.TEXT_DISTINCT)
            self.assertEqual('person', context['entities'][next(iter(source['canonical_refs']['entities'].values()))]['kind'])
            # A 0.2 source has no published person-state manifest, so the
            # composite input stays explicitly empty instead of inventing one.
            self.assertEqual([], source['reviewed_person_states'])
        with psycopg.connect(self.database_url) as conn:
            apply_migrations(conn)
            self.assertIsNone(store.read_publication(conn))
            self.assertIsNone(history.dispatch_history(conn, '/v0/history', '')['publication'])
            with self.assertRaises(PersistenceConflict):
                control_plane.resume_job(conn, job_id=job)
            row = store.read_candidate(conn, job, 'facts')
            with self.assertRaisesRegex(PersistenceError, 'explicit review coverage'):
                store.decide(conn, review_id=row['review_id'], candidate_sha=row['candidate_sha'],
                             decision='approve', rationale='不能用一次点击冒充逐条核对。')
            choices = store.list_source_choices(conn, limit=1)
            self.assertTrue(choices['has_more'])
            selected = store.source_descriptors(conn, catalog_sha=choices['catalog_sha'],
                publication_ids=[choices['items'][0]['publication_id']])
            self.assertEqual(set(selected['entities']), set(selected['sources'][0]['canonical_refs']['entities'].values()))
            self.assertEqual(set(selected['events']), set(selected['sources'][0]['canonical_refs']['events'].values()))
            with self.assertRaises(PersistenceConflict):
                store.queue_narrative(conn, catalog_sha='0' * 64, publication_ids=[choices['items'][0]['publication_id']])
        self._approve('facts')
        self.assertEqual('needs_review', self._run_once(*self.args, narrative_model=self.narrative)[1])
        with psycopg.connect(self.database_url) as conn:
            self.assertIsNone(store.read_publication(conn))
        self._approve('prose')
        # Expiry after the final checkpoint must roll back the publication and
        # its completion together. Two review resumes cannot exhaust retries.
        with psycopg.connect(self.database_url) as conn:
            self.assertEqual(5, control_plane.get_job_detail(conn, job_id=job)['max_attempts'])
            control_plane.claim_job(conn, worker=base.WORKER, lease_seconds=2, job_id=job)
        write_checkpoint = control_plane.write_stage_checkpoint_fenced
        def delayed_checkpoint(*args, **kwargs):
            result = write_checkpoint(*args, **kwargs)
            time.sleep(2.2)
            return result
        with patch.object(control_plane, 'write_stage_checkpoint_fenced', delayed_checkpoint):
            with self.assertRaises(LeaseLost):
                narrative_stage.execute(self.database_url, job_id=job, worker=base.WORKER,
                    revision_source=lambda _: (self.args[1], self.args[2]),
                    model=self.narrative, lease_seconds=2)
        with psycopg.connect(self.database_url) as conn:
            self.assertIsNone(store.read_publication(conn))
            stage, checkpoint = conn.execute("SELECT status, checkpoint FROM chronicle.ingestion_job_stages WHERE job_id=%s AND stage='present'", (job,)).fetchone()
            self.assertEqual('running', stage)
            self.assertNotIn('historical_narrative_version', checkpoint)
        with patch.object(store.contract, 'compile_publication', side_effect=PersistenceError('injected publish fault')):
            self.assertEqual('failed', self._run_once(*self.args, narrative_model=self.narrative)[1])
        with psycopg.connect(self.database_url) as conn:
            self.assertIsNone(store.read_publication(conn))
            self.assertEqual(4, control_plane.get_job_detail(conn, job_id=job)['attempt'])
            control_plane.retry_job(conn, job_id=job)
        self.assertEqual('completed', self._run_once(*self.args, narrative_model=self.narrative)[1])
        self.assertEqual(['facts', 'facts', 'prose'], self.narrative.calls)
        with psycopg.connect(self.database_url) as conn:
            attempts = conn.execute("SELECT payload FROM chronicle.ingestion_outputs WHERE job_id=%s AND artifact_type='narrative-facts-attempt' ORDER BY created_at", (job,)).fetchall()
            self.assertEqual(2, len(attempts))
            self.assertEqual(attempts[0][0]['context_sha'], attempts[1][0]['context_sha'])
            self.assertIsNotNone(attempts[0][0]['validation_error'])
            self.assertIsNone(attempts[1][0]['validation_error'])
            pub = store.read_publication(conn)
            self.assertEqual(2, len(pub['paragraphs']))
            self.assertEqual(pub, store.read_publication(conn, pub['publication_version']))
            self.assertTrue(all(e['publication_id'] for e in pub['evidence'].values()))
            self.assertEqual(1, conn.execute('SELECT count(*) FROM chronicle.historical_narratives').fetchone()[0])
            version = pub['publication_version']
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute("UPDATE chronicle.historical_narratives SET payload='{}'::jsonb WHERE version_sha=%s", (version,))
            self.assertEqual(pub, store.read_publication(conn, version))
            meta = history.dispatch_history(conn, '/v0/history', 'version=' + version)['publication']
            self.assertEqual(1, len(meta['entry_points']))
            first = history.dispatch_history(conn, '/v0/history/paragraphs', f'version={version}&limit=1')
            self.assertEqual(1, first['next_start'])
            next_page = history.dispatch_history(conn, '/v0/history/paragraphs', f'version={version}&start=1&limit=1')
            self.assertIsNone(next_page['next_start'])
            self.assertEqual(0, next_page['previous_start'])
            found = history.dispatch_history(conn, '/v0/history/paragraphs', f'version={version}&at={next_page["paragraphs"][0]["id"]}&limit=1')
            self.assertEqual(next_page, found)
            fact = history.dispatch_history(conn, '/v0/history/conclusions/f0', 'version=' + version)['conclusion']
            self.assertEqual(context['sources'][0]['publication_id'], fact['evidence'][0]['publication_id'])
            for query in ('', 'version=', f'version={version}&version={version}', f'version={version}&limit=51', f'version={version}&start=0&at=x'):
                with self.subTest(query=query), self.assertRaises(ReadModelError):
                    history.dispatch_history(conn, '/v0/history/paragraphs', query)
            with self.assertRaises(ReadModelNotFound):
                history.dispatch_history(conn, '/v0/history/paragraphs', f'version={version}&at=hp_' + '0' * 24)
            with self.assertRaises(ReadModelNotFound):
                history.dispatch_history(conn, '/v0/history', 'version=' + '0' * 64)

    def test_stale_decision_and_cancelled_model_write_are_rejected(self):
        job = self._start()
        with psycopg.connect(self.database_url) as conn:
            row = store.read_candidate(conn, job, 'facts')
            with self.assertRaisesRegex(PersistenceConflict, 'stale'):
                store.decide(conn, review_id=row['review_id'], candidate_sha='0' * 64,
                             decision='approve', rationale='过期请求')
            self.assertEqual('open', store.read_candidate(conn, job, 'facts')['status'])
            control_plane.cancel_job(conn, job_id=job)
            status, _, body = studio_reviews.dispatch_reviews(conn, resolve_publish,
                method='GET', path='/api/v1/studio/jobs/reviews', raw_query='status=open')
            self.assertEqual(200, status)
            self.assertEqual(0, json.loads(body)['open_count'])
            self.assertEqual('dismissed', store.read_candidate(conn, job, 'facts')['status'])
        with psycopg.connect(self.database_url) as conn:
            with self.assertRaisesRegex(PersistenceConflict, 'cancelled'):
                store.decide(conn, review_id=row['review_id'], candidate_sha=row['candidate_sha'],
                             decision='approve', rationale='已取消的任务不可接受')
            with self.assertRaises(LeaseLost):
                store.save_candidate(conn, job_id=job, worker=base.WORKER, kind='facts',
                                     context=row['context'], candidate=row['candidate'], model='test')
            self.assertIsNone(store.read_publication(conn))


if __name__ == '__main__':
    unittest.main()
