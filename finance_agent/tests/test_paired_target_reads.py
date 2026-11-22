"""Bound paired targets via original GUI/handlers; program evidence only."""
import json,sqlite3,unittest
from collections import deque
from contextlib import closing
from app.gui_host import GuiHost
from app.references import display_collection
from tests import test_pending_relationship_repair as repair


def envelope(value):return {'role':'assistant','content':json.dumps(value,ensure_ascii=False)}


class PairedTargetReadTests(unittest.TestCase):
    setUp=repair.PendingRevisionRepairTests.setUp
    tearDown=repair.PendingRevisionRepairTests.tearDown
    facts=repair.PendingRevisionRepairTests.facts

    def host(self):
        targets=[]
        for index,(month,number) in enumerate(((8,'F012'),(9,'F005')),1):
            targets.append({'target_id':'i'+str(index),'object':'invoices','company_ids':['C001'],
                'company_quote':'甲企业','periods':[[2026,month]],'period_quote':f'2026年{month}月',
                'seller':{'mode':'none','value':'','quote':'票号、开票日期和备注'},
                'filters':[{'field':'invoice_no','operator':'=','value':number,'quote':number}],
                'metrics':[{'operation':'details','field':field,'quote':quote} for field,quote in
                    [('invoice_no','票号'),('invoice_date','开票日期'),('remark','备注')]]})
        self.q=deque([envelope({'kind':'read','targets':targets,'unresolved':[]})]);self.model_calls=[]
        sql="SELECT company_id,invoice_no,invoice_date,remark FROM invoices WHERE company_id='C001' AND ((invoice_no='F012' AND invoice_date LIKE '2026-08%') OR (invoice_no='F005' AND invoice_date LIKE '2026-09%'))"
        def model(*args):
            self.model_calls.append(args)
            if self.q:return self.q.popleft()
            return {'role':'assistant','tool_calls':[{'id':'original-paired-or','type':'function',
                'function':{'name':'query_business_sql','arguments':json.dumps({'sql':sql})}}]}
        host=GuiHost(self.book,'U001',session_path=self.book.parent/'session.sqlite',mode='mock',model=model)
        self.addCleanup(host.close)
        return host

    def query(self,host):
        return host.send('列甲企业2026年8月F012和2026年9月F005的票号、开票日期和备注。')

    def test_both_targets_deliver_and_candidates_keep_september_constraint(self):
        host=self.host();view=self.query(host);agent=host.host.agent
        self.assertTrue(view['current_result']['coverage']['complete'],view)
        self.assertEqual(len(self.model_calls),1,'No execution model/SQL is needed for bound unique targets')
        results=agent.last_response['tool_results']
        self.assertEqual([name for name,_ in results],['get_invoice','get_invoice'])
        self.assertEqual([r['evidence']['business_request']['target_ids'] for _,r in results],[['i1'],['i2']])
        self.assertIn('F012',view['current_result']['text']);self.assertIn('F005',view['current_result']['text'])
        display=view['display'];view=host.acknowledge_display(display['trace'],context=view['context'])
        candidates=display_collection(self.book,'U001',agent.context.display_ids)
        self.assertEqual({entry['key']['invoice_no'] for entry in candidates['data']},{'F012','F005'})
        text='从这两张里仅办2026年9月的，备注写“资料归档前核对”，票号等我选。'
        self.q.extend([envelope({'kind':'legacy','action_reason':'await_selection','field':'remark','field_quote':'备注写',
            'matter_relation':'new','matter_quote':text,'reference_relation':'displayed','reference_quote':'这两张',
            'pending_change':{'field':'remark','new_value':'资料归档前核对','source':{'kind':'current','quote':'备注写“资料归档前核对”'}}}),
            repair.tool({'field':'remark','new_value':'资料归档前核对','year':2026,'month':9})])
        view=host.send(text);self.assertFalse(view['preview'])
        self.assertEqual(view['pending']['known']['month'],9)
        for number,good in [('F012',False),('F005',True)]:
            text='选'+number+'，原来的2026年9月限制和备注保留。'
            self.q.extend([envelope({'kind':'legacy','value_relation':'keep','value_quote':text,
                'matter_relation':'continue','matter_quote':text,'reference_relation':'displayed','reference_quote':text}),
                repair.tool({'invoice_no':number})])
            view=host.send(text)
            if not good:
                self.assertFalse(view['preview']);self.assertEqual(view['pending']['known']['month'],9)
                if view.get('display'):
                    view=host.acknowledge_display(view['display']['trace'],context=view['context'])
            else:
                item=view['preview']['items'][0]
                self.assertEqual((item['invoice_no'],item['new_value']),('F005','资料归档前核对'))
                self.assertEqual(host.cancel_preview(view['preview']['id'],context=view['context'])['receipt']['status'],'CANCELLED')

    def test_one_target_cannot_certify_the_other_when_its_date_is_wrong(self):
        host=self.host()
        # Test-only fixture drift: F005 exists, but now violates its own target.
        with closing(sqlite3.connect(self.book)) as db,db:
            db.execute("UPDATE invoices SET invoice_date='2026-08-12' WHERE company_id='C001' AND invoice_no='F005'")
        try:
            view=self.query(host)
            self.assertFalse(view['current_result']['coverage']['complete'])
            coverage=host.host.agent.last_response['business_request_execution_coverage']
            self.assertEqual([t['status'] for t in coverage['targets']],['complete','partial'])
            self.assertFalse(view['preview'])
        finally:
            with closing(sqlite3.connect(self.book)) as db,db:
                db.execute("UPDATE invoices SET invoice_date='2026-09-12' WHERE company_id='C001' AND invoice_no='F005'")

    def test_extra_conditions_do_not_enter_the_point_read_mapping(self):
        from dataclasses import replace
        from app.business_request import bind,ReadFilter,Source
        from app.business_request_delivery import invoice_target_reads
        host=self.host()
        semantic=self.q[0]['content']
        request=bind(semantic,actor='U001',book=self.book,turn_id='policy-check',
            request='列甲企业2026年8月F012和2026年9月F005的票号、开票日期和备注。')
        self.assertEqual(len(invoice_target_reads(request,'U001',self.book)),2)
        target=request.targets[0]
        filtered=replace(target,filters=(*target.filters,ReadFilter('purpose','=','额外条件',Source('current','额外条件'))))
        self.assertIsNone(invoice_target_reads(replace(request,targets=(filtered,*request.targets[1:])),'U001',self.book))
        self.assertEqual(len(self.model_calls),0)


if __name__=='__main__':unittest.main()
