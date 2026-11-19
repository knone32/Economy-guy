# Pinned SQL evidence parser

`sqlglot-30.33.0-py3-none-any.whl` supplies the parser used by `app/sql_evidence.py` for same-string SQL evidence attribution. It does not execute or rewrite model SQL, change the SQLite authorizer, or provide natural-language routing.

- Upstream: https://github.com/tobymao/sqlglot
- Version: 30.33.0
- SHA256: `a5b279fe7397a9fb6cdd0274a13a5fcee0fa83ac6ff617083f1f2832031e90bc`
- Upstream metadata and license are retained inside the wheel.
- The application checks the bundled file hash and parser version before use. No network download or shared-environment installation is required.

Unsupported SQL expressions remain UNKNOWN. Scope attribution is not a proof of arbitrary answer semantics or user-intent correspondence.
