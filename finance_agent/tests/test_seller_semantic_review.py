"""Pure component regressions retained after replacing the postproposal stage.

The archived old stage is under artifacts/semantic-stage-92f. These controls
exercise the same duplicate JSON and CASE trust-boundary failures without
restoring a second request owner or a second Agent loop.
"""
import hashlib
import unittest
from app.seller_semantic_review import load_review,digest,verify_measure_sources
from app.seller_read_scope import SellerReadError


class StrictReadInterpretationTests(unittest.TestCase):
    def test_duplicate_decision_and_confidence_are_rejected(self):
        for raw in ('{"decision":"ambiguous","decision":"contains_all"}',
                    '{"confidence":"uncertain","confidence":"clear"}'):
            with self.assertRaises(ValueError):load_review(raw)

    def test_nested_duplicate_source_is_also_rejected(self):
        with self.assertRaises(ValueError):load_review('{"target":{"quote":"one","quote":"two"}}')

    def test_illegal_json_constants_do_not_acquire_a_source(self):
        for value in ('NaN','Infinity','-Infinity'):
            with self.assertRaises(ValueError):load_review('{"value":'+value+'}')

    def test_raw_current_request_hash_is_utf8_sha256(self):
        raw='当前读取要求'
        self.assertEqual(digest(raw),hashlib.sha256(raw.encode('utf-8')).hexdigest())

    def test_conditional_sum_and_count_cannot_hide_seller_filter(self):
        for kind in ('conditional_sum','conditional_count'):
            query={'status':'VERIFIED','conditions':[],
                   'columns':[{'kind':kind,'conditions':[{'field':'seller_name','operator':'=','value':'同名甲'}]}]}
            with self.assertRaises(SellerReadError):
                verify_measure_sources(query,decision='no_seller_requirement',directory=('同名甲','同名乙'),names=())

    def test_all_seller_set_cannot_be_narrowed_inside_a_measure(self):
        query={'status':'VERIFIED','conditions':[{'field':'seller_name','operator':'LIKE','value':'%同名%'}],
               'columns':[{'conditions':[{'field':'seller_name','operator':'=','value':'同名甲'}]}]}
        with self.assertRaises(SellerReadError):
            verify_measure_sources(query,decision='contains_all',directory=('同名甲','同名乙'),names=('同名甲','同名乙'))

    def test_equivalent_measure_seller_condition_is_not_blanket_banned(self):
        query={'status':'VERIFIED','conditions':[{'field':'seller_name','operator':'LIKE','value':'%同名%'}],
               'columns':[{'conditions':[{'field':'seller_name','operator':'IN','value':['同名甲','同名乙']}]}]}
        verify_measure_sources(query,decision='contains_all',directory=('同名甲','同名乙'),names=('同名甲','同名乙'))

    def test_unknown_attribution_is_capability_not_scope_mismatch(self):
        with self.assertRaises(SellerReadError) as caught:
            verify_measure_sources({'status':'UNKNOWN','reason':'unsupported_predicate'},decision='no_seller_requirement',directory=(),names=())
        self.assertEqual(caught.exception.status,'SQL_EVIDENCE_UNSUPPORTED')
