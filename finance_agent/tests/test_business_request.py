"""Finite immutable source binding, separate from tool/SQL generation."""
from contextlib import closing
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from app.business_request import (bind, BusinessRequestError, Source, ReadRequirement, messages, read_catalog)
from app.cli_workspaces import import_workspace
from app.seller_semantic_review import load_review, verify_measure_sources
from app.seller_read_scope import SellerReadError


class BusinessRequestTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.book=Path(temp.name)/'fictional.sqlite'
        import_workspace(Path(__file__).parent/'fixtures/example.xlsx',self.book)
        self.names=('青屿会展有限公司','青屿设备有限公司')
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute('DELETE FROM invoices')
            for no,name,amount in [('A',self.names[0],10000),('B',self.names[1],30000)]:
                db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',('C001',no,'2026-09-02',name,'项目',amount,'物料',''))
        self.text='C001 2026年9月统计销售方青屿会展有限公司、用途为物料的发票金额和张数。'

    def target(self):
        return {'target_id':'i1','object':'invoices','company_ids':['C001'],'company_quote':'C001',
            'periods':[[2026,9]],'period_quote':'2026年9月',
            'seller':{'mode':'single','quote':'销售方青屿会展有限公司','value':'青屿'},
            'filters':[{'field':'purpose','operator':'=','value':'物料','quote':'用途为物料'}],
            'metrics':[{'operation':'sum','field':'amount_cents','quote':'金额和张数'},
                       {'operation':'count','field':'*','quote':'金额和张数'}],
            'group_by':['period'],'comparisons':[]}

    def make(self,target=None,text=None,**kwargs):
        return bind(json.dumps({'kind':'read','targets':[target or self.target()],'unresolved':[]},ensure_ascii=False),
                    actor='U001',book=self.book,turn_id='turn',request=text or self.text,**kwargs)

    def test_full_name_in_own_source_has_priority_over_redundant_short_value(self):
        req=self.make();self.assertEqual(req.targets[0].seller.names,(self.names[0],))
        self.assertEqual(req.targets[0].company_source,Source('current','C001'))
        self.assertEqual(req.targets[0].period_source,Source('current','2026年9月'))
        req.require_current('U001',self.book,turn_id='turn')

    def test_shared_short_single_is_unresolved_with_real_candidate_names(self):
        target=self.target();target['seller']={'mode':'single','quote':'从青屿取得的全部发票','value':'青屿'}
        req=self.make(target,'C001 2026年9月从青屿取得的全部发票，用途为物料，金额和张数。')
        self.assertEqual(req.targets[0].seller.mode,'ambiguous');self.assertEqual(set(req.targets[0].seller.names),set(self.names))
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.book)

    def test_explicit_set_has_current_condition_source_and_canonical_directory_set(self):
        target=self.target();target['seller']={'mode':'set','quote':'销售方名称包含青屿的全部销售方','value':'青屿'}
        req=self.make(target,'C001 2026年9月汇总销售方名称包含青屿的全部销售方，用途为物料，金额和张数。')
        self.assertFalse(req.unresolved);self.assertEqual(set(req.targets[0].seller.names),set(self.names))
        self.assertFalse(req.metadata()['formal_semantic_proof'])

    def test_bank_counterparty_full_name_does_not_create_invoice_seller_requirement(self):
        target=self.target();target['seller']={'mode':'none','quote':'全部发票金额和张数','value':''};target['filters']=[]
        bank={'target_id':'b1','object':'bank_transactions','company_ids':['C001'],'company_quote':'C001',
              'periods':[[2026,9]],'period_quote':'2026年9月','filters':[{'field':'counterparty_name','operator':'=',
              'value':self.names[0],'quote':'银行交易方'+self.names[0]}],
              'metrics':[{'operation':'sum','field':'amount_cents','quote':'收入金额'}],'group_by':[],'comparisons':[]}
        text='C001 2026年9月统计全部发票金额和张数；另看银行交易方'+self.names[0]+'的收入金额。'
        req=bind(json.dumps({'kind':'read','targets':[target,bank],'unresolved':[]},ensure_ascii=False),
            actor='U001',book=self.book,turn_id='turn',request=text)
        self.assertEqual(req.targets[0].seller.mode,'none');self.assertIsNone(req.targets[1].seller)

    def test_invoice_only_fields_cannot_cross_to_bank_target(self):
        target=self.target();target['object']='bank_transactions';target.pop('seller')
        with self.assertRaises(BusinessRequestError):self.make(target)

    def test_sources_cannot_be_forged_from_unseen_name_or_tool_parameters(self):
        target=self.target();target['seller']['quote']='不存在的原话'
        with self.assertRaises(BusinessRequestError):self.make(target)
        target=self.target();target['filters'][0]['value']='设备维护'
        with self.assertRaises(BusinessRequestError):self.make(target)

    def test_frame_actor_book_turn_hash_and_catalog_are_live_checked(self):
        req=self.make()
        for actor,book,turn in [('U002',self.book,'turn'),('U001',self.book.with_name('other.sqlite'),'turn'),('U001',self.book,'other')]:
            with self.assertRaises(BusinessRequestError):req.require_current(actor,book,turn_id=turn)
        with self.assertRaises(BusinessRequestError):replace(req,request_hash='wrong').require_current('U001',self.book)
        with closing(sqlite3.connect(self.book)) as db,db:db.execute("UPDATE invoices SET seller_name='新登记目录' WHERE invoice_no='B'")
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.book)

    def test_deep_immutability_and_metadata_copy(self):
        req=self.make();metadata=req.metadata();metadata['targets'][0]['seller']['value']='改写'
        self.assertEqual(req.targets[0].seller.value,'青屿')
        with self.assertRaises(FrozenInstanceError):req.targets[0].periods=((2030,1),)
        mutable=['C001'];r=ReadRequirement('x','invoices',mutable,[[2026,9]])
        mutable.append('C002');self.assertEqual(r.company_ids,('C001',));self.assertEqual(r.periods,((2026,9),))

    def test_comparison_period_and_metric_are_bound_to_target(self):
        target=self.target();target['comparisons']=[{'operation':'subtract','metric_operation':'sum','metric_field':'amount_cents',
            'left_period':[2026,10],'right_period':[2026,9],'quote':'金额和张数'}]
        with self.assertRaises(BusinessRequestError):self.make(target)

    def test_context_inherits_filters_seller_metrics_without_historical_amounts_or_sql(self):
        previous=self.make();target=self.target();target.update(company_source='context',company_quote='',
            periods=[[2026,10]],period_quote='十月',previous_target_id='i1')
        target['seller'].update(quote='',source={'kind':'context','key':'i1.seller'})
        target['filters'][0].update(quote='',source={'kind':'context','key':'i1.filters.0'})
        for i,metric in enumerate(target['metrics']):metric.update(quote='',source={'kind':'context','key':f'i1.metrics.{i}'})
        trusted={'company_id':['C001'],'periods':[(2026,9)],'year':[2026],'month':[9]}
        req=self.make(target,'十月呢',previous_request=previous,trusted_scope=trusted,revision=2)
        self.assertEqual(req.targets[0].periods,((2026,10),));self.assertEqual(req.targets[0].seller.names,(self.names[0],))
        self.assertEqual(req.targets[0].filters[0].source.kind,'context');self.assertFalse(req.unresolved)
        prompt=messages('十月呢',read_catalog(self.book,'U001'),trusted_scope=trusted,previous_request=previous)
        data=json.loads(prompt[1]['content']);self.assertIn('previous_requirement',data)
        self.assertNotIn('10000',json.dumps(data));self.assertNotIn('SELECT',json.dumps(data))

    def test_silently_dropped_previous_filters_or_seller_is_unresolved(self):
        previous=self.make();target=self.target();target.update(company_source='context',company_quote='',period_source='context',period_quote='')
        target['seller']={'mode':'none','quote':'再统计金额和张数','value':''};target['filters']=[]
        for metric in target['metrics']:metric['quote']='金额和张数'
        req=self.make(target,'再统计金额和张数',previous_request=previous,trusted_scope={'company_id':['C001'],'periods':[(2026,9)]})
        self.assertTrue(req.unresolved)
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.book)

    def test_forged_context_value_is_rejected(self):
        previous=self.make();target=self.target();target['filters'][0].update(value='设备维护',source={'kind':'context','key':'i1.filters.0'})
        with self.assertRaises(BusinessRequestError):self.make(target,previous_request=previous)

    def test_validated_annual_context_normalizes_twelve_months_without_catalog_default(self):
        target=self.target();target.update(period_source='context',period_quote='',periods=[[2026,m] for m in range(1,13)])
        target['seller']['quote']='销售方青屿会展有限公司';target['filters']=[]
        text='C001 2026全年统计销售方青屿会展有限公司金额和张数。'
        req=self.make(target,text,trusted_scope={'company_id':['C001'],'year':[2026],
            'periods':[(2026,m) for m in range(1,13)]})
        self.assertEqual(len(req.targets[0].periods),12)
        with self.assertRaises(BusinessRequestError):self.make(target,text,trusted_scope={'company_id':['C001']})

    def test_identifier_internal_date_is_not_a_period_source(self):
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',('C001','DOC/2034-07','2034-07-01','其他公司','项目',1,'物料',''))
        target=self.target();target.update(periods=[[2034,7]],period_quote='DOC/2034-07')
        target['seller']={'mode':'none','quote':'发票金额和张数','value':''};target['filters']=[]
        with self.assertRaises(BusinessRequestError):self.make(target,'C001只查DOC/2034-07的发票金额和张数。')

    def test_duplicate_json_fields_cannot_become_a_business_request(self):
        raw=json.dumps({'kind':'read','targets':[self.target()],'unresolved':[]},ensure_ascii=False)
        raw=raw.replace('"kind": "read"','"kind":"general","kind":"read"')
        with self.assertRaises(BusinessRequestError):bind(raw,actor='U001',book=self.book,turn_id='turn',request=self.text)


    def test_bank_direction_enum_normalization_is_model_interpretation_not_wordlist(self):
        for operator,value,quote in [('=','收入','进账'),('IN',['收入','支出'],'进账和出账')]:
            target=self.target();target.update(object='bank_transactions',seller=None,filters=[
                {'field':'direction','operator':operator,'value':value,'quote':quote}])
            req=self.make(target,'C001 2026年9月看'+quote+'金额和张数。')
            self.assertEqual(req.targets[0].filters[0].source.key,'model_interpretation:bank_direction')
            self.assertFalse(req.metadata()['formal_semantic_proof'])
        target=self.target();target.update(object='bank_transactions',seller=None,
            filters=[{'field':'direction','operator':'IN','value':['收入','未知方向'],'quote':'进账和出账'}])
        with self.assertRaises(BusinessRequestError):self.make(target,'C001 2026年9月看进账和出账金额和张数。')

    def test_free_text_in_filter_also_requires_each_literal_source(self):
        target=self.target();target['filters'][0].update(operator='IN',value=['物料','未提及的项目'])
        with self.assertRaises(BusinessRequestError):self.make(target)


    def test_missing_company_and_period_are_unresolved_not_permission_denial_or_defaults(self):
        target=self.target();target.update(company_ids=[],periods=[],company_quote='',period_quote='')
        target['seller']={'mode':'none','quote':'统计全部发票金额和张数','value':''};target['filters']=[]
        req=self.make(target,'统计全部发票金额和张数。')
        self.assertIn('i1.company_id',req.unresolved);self.assertIn('i1.periods',req.unresolved)
        self.assertEqual(req.targets[0].company_ids,());self.assertEqual(req.targets[0].periods,())
        with self.assertRaises(BusinessRequestError) as caught:req.require_current('U001',self.book)
        self.assertEqual(caught.exception.status,'AMBIGUOUS')


    def test_no_seller_requirement_does_not_need_complete_historical_seller_directory(self):
        with closing(sqlite3.connect(self.book)) as db,db:
            db.executemany('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?)',
                [('C001','H'+str(i),'2025-01-02','历史销售方'+str(i),'项目',1,'物料','') for i in range(1001)])
        target=self.target();target['seller']={'mode':'none','quote':'全部发票金额和张数','value':''};target['filters']=[]
        req=self.make(target,'C001 2026年9月统计全部发票金额和张数。')
        self.assertFalse(req.unresolved);self.assertEqual(req.targets[0].seller.names,())
        req.require_current('U001',self.book,turn_id='turn')
        with self.assertRaises(BusinessRequestError) as error:self.make()
        self.assertEqual(error.exception.status,'SQL_SCOPE_LIMIT')


    def test_bank_amount_requires_direction_but_cross_direction_count_is_allowed(self):
        target=self.target();target.update(object='bank_transactions',seller=None,filters=[],group_by=[])
        text='C001 2026年9月统计银行金额和张数。'
        req=self.make(target,text);self.assertIn('i1.bank_direction',req.unresolved)
        target['group_by']=['direction'];self.assertFalse(self.make(target,text).unresolved)
        target['group_by']=[];target['metrics']=[{'operation':'count','field':'*','quote':'张数'}]
        self.assertFalse(self.make(target,text).unresolved)
        target['metrics']=[{'operation':'sum','field':'amount_cents','quote':'金额'}]
        target['filters']=[{'field':'direction','operator':'IN','value':['收入','支出'],'quote':'金额'}]
        self.assertIn('i1.bank_direction',self.make(target,text).unresolved)
        target['filters'][0]['value']=['收入'];self.assertFalse(self.make(target,text).unresolved)


    def test_explicit_empty_month_keeps_source_without_requiring_existing_rows(self):
        target=self.target();target['periods']=[[2035,8]];target['period_quote']='2035年8月'
        req=self.make(target,self.text.replace('2026年9月','2035年8月'))
        self.assertFalse(req.unresolved);self.assertEqual(req.targets[0].periods,((2035,8),))
        req.require_current('U001',self.book,turn_id='turn')
        target['periods']=[[2027,8]]
        with self.assertRaises(BusinessRequestError):self.make(target,self.text.replace('2026年9月','2035年8月'))
        target['periods']=[[2035,8]];target['period_quote']='35年8月'
        with self.assertRaises(BusinessRequestError):self.make(target,self.text.replace('2026年9月','35年8月'))
        target['period_quote']='2035年8月';target['company_ids']=['C002']
        with self.assertRaises(BusinessRequestError):self.make(target,self.text.replace('2026年9月','2035年8月'))

    def test_registered_business_fields_can_group_without_cross_object_fields(self):
        target=self.target();target['group_by']=['item_name','purpose','remark']
        req=self.make(target);self.assertEqual(req.targets[0].group_by,('item_name','purpose','remark'))
        target['group_by']=['counterparty_name']
        with self.assertRaises(BusinessRequestError):self.make(target)
        target.update(object='bank_transactions',seller=None,filters=[],group_by=['direction','counterparty_name','remark'])
        req=self.make(target);self.assertFalse(req.unresolved)
        target['group_by']=['purpose']
        with self.assertRaises(BusinessRequestError):self.make(target)


    def test_protocol_none_seller_keeps_empty_quote_negative_and_current_target_positive(self):
        target=self.target();target['filters']=[]
        target['seller']={'mode':'none','value':'','quote':''}
        text='C001 2026年9月统计全部发票金额和张数。'
        with self.assertRaises(BusinessRequestError):self.make(target,text)
        target['seller']['quote']='全部发票金额和张数'
        self.assertFalse(self.make(target,text).unresolved)

    def test_protocol_blank_filter_uses_empty_string_not_null(self):
        from app.business_request import DEFINITION
        target=self.target();text=self.text.replace('用途为物料','用途为空')
        target['filters']=[{'field':'purpose','operator':'is_blank','value':None,'quote':'用途为空'}]
        with self.assertRaises(BusinessRequestError):self.make(target,text)
        target['filters'][0]['value']=DEFINITION['protocol']['filter_operators']['is_blank']['value']
        self.assertFalse(self.make(target,text).unresolved)

    def test_protocol_annual_uses_normalized_trusted_months_not_raw_year_carrier(self):
        target=self.target();target['periods']=[[2026,m] for m in range(1,13)]
        target['period_quote']='2026全年';text=self.text.replace('2026年9月','2026全年')
        trusted={'company_id':['C001'],'year':[2026],'periods':[(2026,m) for m in range(1,13)]}
        with self.assertRaises(BusinessRequestError):self.make(target,text,trusted_scope=trusted)
        target['period_source']='context'
        req=self.make(target,text,trusted_scope=trusted)
        self.assertFalse(req.unresolved);self.assertEqual(len(req.targets[0].periods),12)
        self.assertEqual(req.targets[0].period_source.kind,'context')

    def test_protocol_min_max_and_text_pattern_conditions_bind_to_actual_fields(self):
        for operation in ('min','max'):
            target=self.target();target['metrics']=[{'operation':operation,'field':'amount_cents','quote':'最高和最低金额'}]
            self.assertFalse(self.make(target,self.text.replace('金额和张数','最高和最低金额')).unresolved)
        target=self.target();target['filters'][0].update(operator='IN',value=['物料','维修'],quote='用途为物料或维修')
        self.assertFalse(self.make(target,self.text.replace('用途为物料','用途为物料或维修')).unresolved)
        target['filters'][0].update(operator='LIKE',value='%物料%',quote='用途含物料')
        self.assertFalse(self.make(target,self.text.replace('用途为物料','用途含物料')).unresolved)
        target['filters'][0]['value']='%未提及%'
        with self.assertRaises(BusinessRequestError):self.make(target,self.text.replace('用途为物料','用途含物料'))



    def revision_target(self):
        target=self.target();target['seller']={'mode':'none','quote':'统计全部发票金额和张数','value':''}
        target['filters']=[]
        return target,'C001 2026年9月发起新查询，统计全部发票金额和张数。'

    def test_explicit_read_replacement_can_remove_old_seller_and_filter_with_current_source(self):
        previous=self.make();target,text=self.revision_target()
        target.update(relation='replace',relation_quote='发起新查询',previous_target_id='i1')
        req=self.make(target,text,previous_request=previous,revision=2)
        req.require_current('U001',self.book,turn_id='turn')
        current=req.targets[0];self.assertEqual((current.seller.mode,current.filters),('none',()))
        self.assertEqual(current.relation,'replace');self.assertEqual(current.previous_target_id,'i1')
        self.assertEqual(current.relation_source.quote,'发起新查询')
        self.assertEqual(current.relation_source.key,f'1/{previous.request_hash}/i1')
        self.assertEqual(previous.targets[0].seller.names,(self.names[0],))
        self.assertTrue(previous.targets[0].filters)

    def test_default_read_update_cannot_silently_remove_previous_conditions(self):
        previous=self.make();target,text=self.revision_target()
        req=self.make(target,text,previous_request=previous,revision=2)
        self.assertEqual(req.targets[0].relation,'update')
        self.assertIn('i1.previous_filters_not_replaced',req.unresolved)
        self.assertIn('i1.previous_seller_not_replaced',req.unresolved)
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.book)

    def test_replacement_requires_real_previous_target_and_current_quote(self):
        previous=self.make();base,text=self.revision_target()
        for extra in ({'relation':'replace','previous_target_id':'i1'},
                      {'relation':'replace','previous_target_id':'not-real','relation_quote':'发起新查询'},
                      {'relation':'replace','relation_quote':'发起新查询'},
                      {'relation':'replace','previous_target_id':'i1','relation_quote':'未出现的要求'}):
            with self.subTest(extra=extra),self.assertRaises(BusinessRequestError):
                self.make({**base,**extra},text,previous_request=previous,revision=2)
        with self.assertRaises(BusinessRequestError):
            self.make({**base,'relation':'replace','relation_quote':'发起新查询','previous_target_id':'i1'},text)
        # A revision relationship does not rescue forged new conditions.
        bad={**base,'relation':'replace','relation_quote':'发起新查询','previous_target_id':'i1',
             'filters':[{'field':'purpose','operator':'=','value':'未说过','quote':'发起新查询'}]}
        with self.assertRaises(BusinessRequestError):self.make(bad,text,previous_request=previous,revision=2)

    def test_read_clarify_relation_is_unresolved_and_cannot_execute(self):
        target,text=self.revision_target();target.update(relation='clarify',relation_quote='发起新查询')
        req=self.make(target,text)
        self.assertIn('i1.relation',req.unresolved)
        with self.assertRaises(BusinessRequestError):req.require_current('U001',self.book)



class PureReviewBoundaryTests(unittest.TestCase):
    def test_duplicate_keys_are_not_last_wins(self):
        for raw in ('{"decision":"ambiguous","decision":"contains_all"}',
                    '{"confidence":"uncertain","confidence":"clear"}'):
            with self.assertRaises(ValueError):load_review(raw)

    def test_conditional_seller_measures_cannot_bypass_no_seller_or_all_set(self):
        query={'status':'VERIFIED','conditions':[{'field':'seller_name','operator':'LIKE','value':'%同名%'}],
               'columns':[{'conditions':[{'field':'seller_name','operator':'=','value':'同名甲'}]}]}
        for decision,names in [('no_seller_requirement',()),('contains_all',('同名甲','同名乙'))]:
            with self.assertRaises(SellerReadError):verify_measure_sources(query,decision=decision,directory=('同名甲','同名乙'),names=names)
        query['conditions']=[]
        with self.assertRaises(SellerReadError):verify_measure_sources(query,decision='no_seller_requirement',directory=('同名甲','同名乙'),names=())

    def test_unknown_proof_is_capability_not_scope_mismatch(self):
        with self.assertRaises(SellerReadError) as caught:
            verify_measure_sources({'status':'UNKNOWN','reason':'unsupported_predicate'},decision='no_seller_requirement',directory=(),names=())
        self.assertEqual(caught.exception.status,'SQL_EVIDENCE_UNSUPPORTED')

