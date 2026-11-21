"""Use existing verified fact wording for SQL cards; aliases prove no units."""
from copy import deepcopy
import unittest
from app.business_request_delivery import accept_result
from app.tui import AgentWorkspace
from tests import test_business_request_delivery as fixture_module


class VerifiedSQLCardTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.BusinessRequestDeliveryTests(methodName='runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.result=accept_result(f.requirement(),'query_business_sql',f.actual_result(f.sql),'U002',f.book)

    def test_aliases_do_not_hide_verified_money_count_units_or_groups(self):
        original=deepcopy(self.result)
        title,body=AgentWorkspace.business_card('query_business_sql',self.result['data'],self.result['evidence'])
        for expected in ('1 张','发票数量','发票金额合计','1797.00 元','2357.00 元','2026-09','2026-10'):
            self.assertIn(expected,body)
        self.assertNotIn('n：',body);self.assertNotIn('cents：',body)
        self.assertEqual(self.result,original)

    def test_unknown_expression_evidence_cannot_gain_verified_business_labels(self):
        unknown=deepcopy(self.result);unknown['evidence']['query_scope']['status']='UNKNOWN'
        _,body=AgentWorkspace.business_card('query_business_sql',unknown['data'],unknown['evidence'])
        self.assertNotIn('发票数量',body);self.assertNotIn('发票金额合计',body)
