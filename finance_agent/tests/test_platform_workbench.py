"""Program-operated real Textual surface; never human or NLU evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from textual.widgets import Input
from app.tui import AgentWorkspace
from app.model_config import DEFAULT_TEMPLATE
from app.cli_workspaces import import_workspace
from app.assistant_config import configure
from app.tui_screens import Choices
from tests import test_tui_p0 as helpers


class PlatformWorkbenchTests(unittest.IsolatedAsyncioTestCase):
    await_state=helpers.P0Test.await_state
    sign_in=helpers.P0Test.sign_in
    send=helpers.P0Test.send

    async def test_select_configured_assistant_and_open_immutable_source(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);book=root/'book.db'
            import_workspace(Path(__file__).parent/'fixtures/example.xlsx',book)
            configure(book,'U001','assistant','query',{'name':'查询助手','tools':['get_invoice'],'skills':[]},capabilities={'assistant.manage'})
            app=AgentWorkspace(book,DEFAULT_TEMPLATE,root/'profiles.json',model=lambda *_:None)
            app.mode='mock'
            async with app.run_test(size=(150,42)) as pilot:
                await self.sign_in(app,pilot)
                await pilot.press('f5');await pilot.pause()
                self.assertIsInstance(app.screen,Choices)
                await pilot.click('#choice-0');await pilot.pause()
                self.assertEqual(app.assistant_id,'query')
                app.ensure_agent();self.assertEqual(app.agent.assistant_id,'query')
                await self.send(app,pilot,'/materials C001')
                content='\n'.join(line.text for line in app.workspace_widget('#chat-log').lines)
                self.assertIn('资料原文',content)
                self.assertIn('[]',content)

    def test_rule_card_preserves_version_and_exact_source_command(self):
        source={'material_id':'opaque','version':1,'paragraph_id':3}
        title,body=AgentWorkspace.business_card('get_applicable_rules',{'content':'规则原文','rule_id':'R','version':'v1','business_date':'2026-11-01','source':source},{'source':'current_sqlite'})
        self.assertIn('/source opaque 1 3',body)
        self.assertIn('2026-11-01',body)
        self.assertIn('v1',body)
