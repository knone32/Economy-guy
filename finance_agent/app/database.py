"""SQLite 数据库建表和连接。"""
from pathlib import Path
import sqlite3


def connect(database_path: str | Path) -> sqlite3.Connection:
    """打开数据库，并让查询结果可按字段名读取。"""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """创建 Stage 0 所需表；重复调用不会重复建表。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS companies (
            company_id TEXT PRIMARY KEY, name TEXT NOT NULL, short_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY, name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permissions (
            user_id TEXT NOT NULL, company_id TEXT NOT NULL, can_read INTEGER NOT NULL,
            can_modify INTEGER NOT NULL, PRIMARY KEY (user_id, company_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        );
        CREATE TABLE IF NOT EXISTS invoices (
            company_id TEXT NOT NULL, invoice_no TEXT NOT NULL, invoice_date TEXT NOT NULL,
            seller_name TEXT NOT NULL, item_name TEXT NOT NULL, amount_cents INTEGER NOT NULL,
            purpose TEXT, remark TEXT, PRIMARY KEY (company_id, invoice_no),
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        );
        CREATE TABLE IF NOT EXISTS bank_transactions (
            company_id TEXT NOT NULL, transaction_no TEXT NOT NULL, transaction_date TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('收入', '支出')),
            amount_cents INTEGER NOT NULL, counterparty_name TEXT NOT NULL, remark TEXT,
            PRIMARY KEY (company_id, transaction_no),
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_month ON invoices(company_id, invoice_date);
        CREATE INDEX IF NOT EXISTS idx_transaction_month ON bank_transactions(company_id, transaction_date);
        """
    )
    connection.commit()
