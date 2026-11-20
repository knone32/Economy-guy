"""Compatibility of the existing one-column is_blank helper, no new functions."""
import unittest
from app.sql_evidence import describe
from app.business_sql import TABLES


class IsBlankProjectionCompatibilityTests(unittest.TestCase):
    def evidence(self,condition,then='amount_cents'):
        sql='SELECT SUM(CASE WHEN '+condition+' THEN '+then+' ELSE 0 END) AS value FROM invoices'
        return describe(sql,['value'],{'company_ids':('C001',),'periods':((2026,9),)},TABLES,
                        {'invoices'},allow_partial_projection=True)

    def test_existing_blank_conditional_money_and_count_keep_original_attribution(self):
        for then,kind,unit in [('amount_cents','conditional_sum','cents'),('1','conditional_count','count')]:
            with self.subTest(then=then):
                query=self.evidence('is_blank(purpose)',then)
                self.assertEqual(query['status'],'VERIFIED',query)
                self.assertEqual(query['columns'][0]['kind'],kind)
                self.assertEqual(query['columns'][0]['unit'],unit)
                self.assertEqual(query['columns'][0]['conditions'],[{'field':'purpose','operator':'is_blank','value':True}])
                self.assertEqual(query['row_shape'],'aggregate')

    def test_existing_negated_blank_does_not_become_positive_blank(self):
        query=self.evidence('NOT is_blank(purpose)')
        self.assertEqual(query['status'],'VERIFIED',query)
        self.assertIs(query['columns'][0]['conditions'][0]['value'],False)

    def test_other_anonymous_and_non_original_column_signatures_stay_unknown(self):
        for condition in ('custom_function(purpose)',"is_blank('')",'is_blank(purpose,remark)',
                          'is_blank(TRIM(purpose))','is_blank(missing_column)'):
            with self.subTest(condition=condition):
                self.assertEqual(self.evidence(condition)['status'],'UNKNOWN')
