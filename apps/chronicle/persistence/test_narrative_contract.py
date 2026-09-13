"""Corroboration invariants, not a historical truth oracle."""
import copy
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narrative_contract as contract
from common import PersistenceError


def expanded_states(source):
    result = copy.deepcopy(source['reviewed_person_states'])
    for item in result:
        if 'source_fact_refs' in item:
            item['source_facts'] = [source['reviewed_person_state_sources'][key]
                                    for key in item.pop('source_fact_refs')]
    return result


def drafts(context):
    sources = context['sources']
    phases, facts, paragraphs = [], [], []
    for index, source in enumerate(sources):
        phase, fact = f'p{index}', f'f{index}'
        entity = next(iter(source.get('canonical_refs', {}).get('entities', {}).values()), None)
        event = next(iter(source.get('canonical_refs', {}).get('events', {}).values()), None)
        evidence = source['evidence'][0]['id']
        phases.append(dict(id=phase, label=source['title'], year=None, period=None,
                           basis=[evidence], relation_to_previous='uncertain'))
        facts.append(dict(id=fact, question='这一来源如何描述人物？', subject_id=entity, event_id=event,
                          dimension='event_detail', phase_ids=[phase], text=source['evidence'][0]['quote'],
                          value=None, certainty='clear', reason='限于这份来源明确记载的范围。',
                          evidence=[dict(id=evidence, relation='support', attribution='本传作者', note='原文明载。')]))
        paragraphs.append(dict(id=f'n{index}', phase_id=phase,
            segments=[dict(text=source['translation'][0]['text'], conclusion_ids=[fact],
                           event_id=event, event_relation='current' if event else None, event_text=None)],
            entities=[dict(entity_id=entity, importance='primary')] if entity else []))
    relations = [dict(left=a['source_id'], right=b['source_id'], relation='unknown',
                      reason='此测试不对史料独立性作断言。') for a, b in itertools.combinations(sources, 2)]
    return (
        dict(schema='chronicle.source-corroboration', version='0.1', title='测试综合叙事',
             phases=phases, conclusions=facts, source_relations=relations),
        dict(schema='chronicle.historical-narrative', version='0.1', paragraphs=paragraphs,
             entry_points=[dict(label='阅读入口', kind='period', paragraph_id='n0', event_id=None,
                                reason='概览这一组已核对资料的完整历史发展。')]),
    )


def context_fixture():
    return dict(catalog_sha='c' * 64, entities={'person': {'name': '周瑜', 'kind': 'person'},
                'place': {'name': '南郡', 'kind': 'place'}}, events={'event': {'name': '史料所述战事'}},
        sources=[dict(source_id=f's{n}', publication_id=f'pub{n}', document_id='one-work',
            source_sha='a' * 64, title=f'传{n}', chapter_text='瑜为偏将军，领南郡太守。',
            translation=[{'text': '周瑜担任偏将军，兼任南郡太守。'}],
            canonical_refs={'entities': {'ent_1': 'person'}, 'events': {'evt_1': 'event'}},
            evidence=[dict(id=f'e{n}', anchor_id=f'a{n}', quote='瑜为偏将军，领南郡太守。', start=0, end=15)])
            for n in range(2)])


class NarrativeContractTests(unittest.TestCase):
    def setUp(self):
        self.context = context_fixture()
        self.facts, self.prose = drafts(self.context)

    def test_whole_context_and_explicit_state_ranges_are_preserved(self):
        for n, value in enumerate(['偏将军', '南郡太守']):
            state = copy.deepcopy(self.facts['conclusions'][0])
            state.update(id=f'office{n}', dimension='office', value=value,
                         certainty='uncertain' if n else 'clear')
            self.facts['conclusions'].append(state)
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual(['偏将军', '南郡太守'], [s['value'] for s in pub['paragraphs'][0]['entities'][0]['states']])
        self.assertEqual([], pub['paragraphs'][1]['entities'][0]['states'])
        self.assertEqual(['clear', 'uncertain'], [s['certainty'] for s in pub['paragraphs'][0]['entities'][0]['states']])
        prompt = contract.build_prompt('facts', self.context)
        self.assertIn(self.context['sources'][0]['chapter_text'], prompt)
        changed = copy.deepcopy(self.prose)
        changed['paragraphs'][0]['segments'][0]['text'] += '（修订）'
        self.assertNotEqual(pub['publication_version'], contract.compile_publication(self.context, self.facts, changed)['publication_version'])
        self.assertEqual(pub, contract.compile_publication(self.context, self.facts, self.prose))

    def test_same_document_or_duplicate_upload_never_independent(self):
        self.facts['source_relations'][0]['relation'] = 'independent'
        with self.assertRaisesRegex(PersistenceError, 'not independent'):
            contract.validate_facts(self.facts, self.context)
        self.context['sources'][1]['document_id'] = 'second-upload'
        with self.assertRaisesRegex(PersistenceError, 'not independent'):
            contract.validate_facts(self.facts, self.context)

    def test_unreviewed_and_wrong_phase_facts_cannot_enter_current_prose(self):
        self.prose['paragraphs'][0]['segments'][0]['conclusion_ids'] = ['invented']
        with self.assertRaisesRegex(PersistenceError, 'unreviewed'):
            contract.validate_prose(self.prose, self.context, self.facts)
        self.prose['paragraphs'][0]['segments'][0]['conclusion_ids'] = ['f1']
        with self.assertRaisesRegex(PersistenceError, 'outside its approved phase'):
            contract.validate_prose(self.prose, self.context, self.facts)

    def test_mentions_cannot_be_navigation_occurrence(self):
        self.prose['paragraphs'][0]['segments'][0]['event_relation'] = 'retrospective'
        self.prose['entry_points'] = [dict(label='不能猜', kind='event', paragraph_id='n0', event_id='event', reason='测试禁止用回顾段落充当事件发生位置。')]
        with self.assertRaisesRegex(PersistenceError, 'retrospective'):
            contract.validate_prose(self.prose, self.context, self.facts)

    def test_silence_and_actions_cannot_be_states(self):
        fact = self.facts['conclusions'][0]
        fact['evidence'][0]['relation'] = 'background'
        with self.assertRaisesRegex(PersistenceError, 'silence'):
            contract.validate_facts(self.facts, self.context)
        fact['evidence'][0]['relation'] = 'support'
        fact.update(dimension='control', value='孙权势力')
        with self.assertRaisesRegex(PersistenceError, 'matching entity kind'):
            contract.validate_facts(self.facts, self.context)

    def test_time_grouping_and_capacity_fail_closed(self):
        for phase in self.facts['phases']:
            phase.update(year=208, period='冬')
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual(1, len(pub['groups']))
        self.facts['phases'][1]['year'] = 207
        with self.assertRaisesRegex(PersistenceError, 'chronological'):
            contract.validate_facts(self.facts, self.context)
        self.context['sources'][0]['chapter_text'] = '古文' * contract.MAX_PROMPT_CHARS
        with self.assertRaisesRegex(PersistenceError, 'never truncate'):
            contract.build_prompt('facts', self.context)

    def test_repeated_reading_state_rows_do_not_exhaust_full_chapter_budget(self):
        state = dict(person_id='person', person_name='周瑜', item_kind='identity',
            dimension='office', value='偏将军', relation=None, target=None,
            qualification='ordinary', certainty='clear', reason_codes=[],
            phase_ids=['source_phase'], operation=None, from_phase_id=None,
            to_phase_id=None, source_facts=[dict(fact_ref='sf1', phase_id='source_phase',
                chapter_id='source_chapter', revision_id='r1', chapter_publication_id='pub0',
                claim_refs=['claim1'])])
        variants = [state, {**state, 'certainty': 'uncertain'},
            {**state, 'qualification': 'reported'},
            {**state, 'phase_ids': ['other_phase']},
            {**state, 'reason_codes': ['tenure_unproven']},
            {**state, 'source_facts': [{**state['source_facts'][0], 'fact_ref': 'sf2'}]}]
        self.context['sources'][0]['reviewed_person_states'] = [copy.deepcopy(state) for _ in range(675)] + variants
        self.context['sources'][1]['reviewed_person_states'] = [copy.deepcopy(state)]
        before = copy.deepcopy(self.context)
        self.assertGreater(len(contract.canonical_json_bytes(self.context)), contract.MAX_PROMPT_CHARS)
        forward, _ = contract.model_reference_maps(self.context)
        view = contract.model_context(self.context, forward)
        self.assertEqual(variants, expanded_states(view['sources'][0]))
        self.assertEqual([state], expanded_states(view['sources'][1]))
        self.assertEqual(before, self.context)
        prompt = contract.build_prompt('facts', self.context)
        self.assertLess(len(prompt), contract.MAX_PROMPT_CHARS)
        for original, supplied in zip(self.context['sources'], view['sources']):
            self.assertEqual(original['chapter_text'], supplied['chapter_text'])
            self.assertEqual(original['translation'], supplied['translation'])
            self.assertEqual([e['quote'] for e in original['evidence']], [e['quote'] for e in supplied['evidence']])
        self.context['sources'][0]['chapter_text'] = '完整原文' * contract.MAX_PROMPT_CHARS
        with self.assertRaisesRegex(PersistenceError, 'never truncate'):
            contract.build_prompt('facts', self.context)

    def test_shared_state_provenance_round_trips_without_merging_variants(self):
        fact = dict(fact_ref='sf1', phase_id='source_phase', chapter_id='chapter',
                    revision_id='r1', chapter_publication_id='pub0', claim_refs=['c1'],
                    note=' 空格、换行\n与未参与引用映射的 entity_001 都原样保留。' * 30)
        variants = [fact, {**fact, 'phase_id': 'other_phase'},
                    {**fact, 'claim_refs': ['c2']}, {**fact, 'revision_id': 'r2'},
                    {**fact, 'chapter_publication_id': 'pub1'}, {**fact, 'extra': '保留新字段'}]
        states = [dict(person_id='person', phase_ids=[f'p{n}'], source_facts=[fact, variant, fact])
                  for n, variant in enumerate(variants)]
        states.extend([dict(person_id='person', source_facts=[]), dict(person_id='person')])
        for source in self.context['sources']:
            source['reviewed_person_states'] = copy.deepcopy(states)
        before = copy.deepcopy(self.context)
        view = contract.model_context(self.context, contract.model_reference_maps(self.context)[0])
        self.assertEqual(before, self.context)
        for source in view['sources']:
            self.assertEqual(states, expanded_states(source))
            table = source['reviewed_person_state_sources']
            self.assertEqual(len(variants), len(table))
            self.assertEqual(variants, list(table.values()))
            self.assertEqual([], source['reviewed_person_states'][-2]['source_fact_refs'])
            self.assertNotIn('source_fact_refs', source['reviewed_person_states'][-1])
        self.assertTrue(set(view['sources'][0]['reviewed_person_state_sources']).isdisjoint(
            view['sources'][1]['reviewed_person_state_sources']))
        self.assertEqual(view, contract.model_context(self.context, contract.model_reference_maps(self.context)[0]))

    def test_small_unique_state_provenance_does_not_add_prompt_overhead(self):
        state = dict(person_id='person', source_facts=[{'fact_ref': 'f1'}])
        self.context['sources'][0]['reviewed_person_states'] = [state]
        self.context['sources'][1]['reviewed_person_states'] = []
        view = contract.model_context(self.context, contract.model_reference_maps(self.context)[0])
        self.assertEqual([state], view['sources'][0]['reviewed_person_states'])
        for source in view['sources']:
            self.assertNotIn('reviewed_person_state_sources', source)

    def test_repeated_provenance_leaves_room_for_complete_prose_correction(self):
        fact = dict(fact_ref='sf1', phase_id='phase', chapter_id='chapter',
                    revision_id='r1', chapter_publication_id='pub0', claim_refs=['c1'],
                    note='完整未截断的来源材料。' * 600)
        states = [dict(person_id='person', phase_ids=[f'phase_{n}'], source_facts=[fact])
                  for n in range(40)]
        self.context['sources'][0]['reviewed_person_states'] = states
        before = copy.deepcopy(self.context)
        previous = contract.canonical_json_bytes(self.prose).decode()
        prompt = contract.build_prompt('prose', self.context, self.facts)
        self.assertGreater(len(contract.canonical_json_bytes(before).decode()), contract.MAX_PROMPT_CHARS)
        self.assertLess(len(prompt) + len(previous) + 6000, contract.MAX_PROMPT_CHARS)
        view = contract.model_context(self.context, contract.model_reference_maps(self.context)[0])
        self.assertEqual(states, expanded_states(view['sources'][0]))
        self.assertEqual(before, self.context)
        self.assertIn(fact['note'], prompt)

    def test_events_are_not_automatically_promoted_to_navigation(self):
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual(2, len(pub['paragraphs']))
        self.assertEqual(1, len(pub['entry_points']))
        self.assertEqual('period', pub['entry_points'][0]['kind'])
        self.prose['entry_points'] = [
            dict(label='后期', kind='period', paragraph_id='n1', event_id=None, reason='一段独立的发展阶段。'),
            dict(label='早期', kind='period', paragraph_id='n0', event_id=None, reason='进入这段历史的起点。')]
        pub = contract.compile_publication(self.context, self.facts, self.prose)
        self.assertEqual(['早期', '后期'], [e['label'] for e in pub['entry_points']])
        self.prose['entry_points'][0]['reason'] = ''
        with self.assertRaises(PersistenceError):
            contract.validate_prose(self.prose, self.context, self.facts)

    def test_inline_event_label_is_grounded_in_actual_prose(self):
        segment = self.prose['paragraphs'][0]['segments'][0]
        segment['event_text'] = '未出现的赤壁之战'
        with self.assertRaisesRegex(PersistenceError, 'exactly once'):
            contract.validate_prose(self.prose, self.context, self.facts)
        segment['event_text'] = '周瑜'
        contract.validate_prose(self.prose, self.context, self.facts)

    def test_model_handles_round_trip_only_typed_references(self):
        before = copy.deepcopy(self.context)
        forward, reverse = contract.model_reference_maps(self.context)
        self.assertEqual((forward, reverse), contract.model_reference_maps(copy.deepcopy(self.context)))
        view = contract.model_context(self.context, forward)
        self.assertEqual(before, self.context)
        for original, supplied in zip(self.context['sources'], view['sources']):
            self.assertEqual(original['chapter_text'], supplied['chapter_text'])
            self.assertEqual(original['translation'], supplied['translation'])
            self.assertEqual(original['evidence'][0]['quote'], supplied['evidence'][0]['quote'])
            self.assertEqual(forward[original['evidence'][0]['id']], supplied['evidence'][0]['id'])
        self.facts['conclusions'][0]['text'] = 'person event e0 entity_001 是原文中的字样。'
        encoded = contract.map_candidate_references(self.facts, forward)
        self.assertEqual(self.facts['conclusions'][0]['text'], encoded['conclusions'][0]['text'])
        self.assertEqual('f0', encoded['conclusions'][0]['id'])
        self.assertEqual(self.facts, contract.map_candidate_references(encoded, reverse))
        encoded_prose = contract.map_candidate_references(self.prose, forward)
        self.assertEqual(self.prose, contract.map_candidate_references(encoded_prose, reverse))
        encoded['conclusions'][0]['subject_id'] = 'entity_999'
        with self.assertRaisesRegex(PersistenceError, 'invents a canonical entity'):
            contract.validate_facts(contract.map_candidate_references(encoded, reverse), self.context)

    def test_prose_correction_reports_all_affected_paragraphs(self):
        self.prose['paragraphs'][0]['segments'][0]['event_text'] = '缺少这个事件词'
        self.prose['paragraphs'][1]['segments'][0]['conclusion_ids'] = ['f0']
        with self.assertRaises(PersistenceError) as error:
            contract.validate_prose(self.prose, self.context, self.facts)
        self.assertIn('paragraph n0 segment 0', str(error.exception))
        self.assertIn('paragraph n1 segment 0', str(error.exception))
        self.assertIn("'f0': ['p0']", str(error.exception))

    def test_correction_cannot_silently_drop_later_approved_history(self):
        self.prose['paragraphs'].pop()
        with self.assertRaisesRegex(PersistenceError, "omits approved phases.*p1"):
            contract.validate_prose(self.prose, self.context, self.facts)

    def test_facts_cannot_approve_a_phase_that_no_conclusion_can_narrate(self):
        phase = copy.deepcopy(self.facts['phases'][-1])
        phase['id'] = 'orphan'
        self.facts['phases'].append(phase)
        with self.assertRaisesRegex(PersistenceError, 'phases have no applicable conclusion.*orphan'):
            contract.validate_facts(self.facts, self.context)


if __name__ == '__main__':
    unittest.main()
