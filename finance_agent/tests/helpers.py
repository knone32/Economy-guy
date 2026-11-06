from pathlib import Path
import os
import tempfile
from app.database import connect
from app.importer import initialize_database

ROOT = Path(__file__).resolve().parents[1]
EXCEL = Path(os.environ.get("FINANCE_TEST_EXCEL", str(ROOT / "tests" / "fixtures" / "example.xlsx")))
if not EXCEL.is_file():
    raise FileNotFoundError("缺少测试夹具，请提供tests/fixtures/example.xlsx或FINANCE_TEST_EXCEL")


class DatabaseTestCaseMixin:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        initialize_database(EXCEL, self.db_path)
        self.connection = connect(self.db_path)

    def tearDown(self):
        self.connection.close(); self.temp.cleanup()
