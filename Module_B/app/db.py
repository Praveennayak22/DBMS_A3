import os
import re
from pathlib import Path
from typing import Iterable, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parents[1]
DB_DSN = os.getenv("MODULE_B_DB_DSN", "postgresql://postgres:postgres@localhost:5432/module_b")
SCHEMA_PATH = BASE_DIR / "sql" / "init_schema.sql"
INDEX_PATH = BASE_DIR / "sql" / "indexes.sql"

INSERT_ID_COLUMNS = {
    "roles": "role_id",
    "users": "user_id",
    "user_logs": "log_id",
    "groups": "group_id",
    "students": "student_id",
    "resumes": "resume_id",
    "companies": "company_id",
    "job_postings": "job_id",
    "eligibility_criteria": "criteria_id",
    "applications": "application_id",
    "job_events": "event_id",
    "venue_booking": "booking_id",
    "interviews": "interview_id",
    "question_bank": "q_id",
    "prep_pages": "page_id",
    "placement_stats": "stat_id",
    "penalties": "penalty_id",
    "cds_training_sessions": "session_id",
    "audit_logs": "log_id",
}


def _to_postgres_placeholders(query: str) -> str:
    # Existing app queries use sqlite-style placeholders; convert them centrally.
    return query.replace("?", "%s")


def _normalize_query(query: str) -> str:
    q = _to_postgres_placeholders(query)
    if re.search(r"(?i)INSERT\s+OR\s+IGNORE\s+INTO", q):
        q = re.sub(r"(?i)INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", q)
        if "ON CONFLICT" not in q.upper():
            q = q.rstrip()
            if q.endswith(";"):
                q = q[:-1].rstrip()
            q += " ON CONFLICT DO NOTHING"
    return q


def _prepare_schema_sql(schema_sql: str) -> str:
    sql = re.sub(r"(?im)^\s*PRAGMA\s+foreign_keys\s*=\s*ON;\s*$", "", schema_sql)
    sql = re.sub(r"(?i)INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", sql)

    def convert_insert_or_ignore(match: re.Match) -> str:
        stmt = match.group(0)
        stmt = re.sub(r"(?i)INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", stmt)
        stmt = stmt.rstrip()
        if stmt.endswith(";"):
            stmt = stmt[:-1].rstrip()
        return stmt + " ON CONFLICT DO NOTHING;"

    sql = re.sub(r"(?is)INSERT\s+OR\s+IGNORE\s+INTO\s+.+?;", convert_insert_or_ignore, sql)
    return sql


def _connect() -> psycopg.Connection:
    return psycopg.connect(DB_DSN, row_factory=dict_row)


class PostgresCursor:
    def __init__(self, cursor: psycopg.Cursor):
        self._cursor = cursor
        self._lastrowid = None

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._lastrowid

    def set_lastrowid(self, value):
        self._lastrowid = value

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnection:
    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self._conn.rollback()
        self._conn.close()

    def execute(self, query: str, params: Iterable = ()): 
        cur = self._conn.cursor()
        cur.execute(_normalize_query(query), tuple(params))
        return PostgresCursor(cur)

    def executemany(self, query: str, params_list: Iterable[Iterable]):
        cur = self._conn.cursor()
        cur.executemany(_normalize_query(query), params_list)
        return PostgresCursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def get_connection() -> PostgresConnection:
    return PostgresConnection(_connect())


def initialize_database(apply_indexes: bool = False):
    schema_sql = _prepare_schema_sql(SCHEMA_PATH.read_text(encoding="utf-8"))
    index_sql = INDEX_PATH.read_text(encoding="utf-8") if apply_indexes else ""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            if apply_indexes and index_sql.strip():
                cur.execute(index_sql)
        _ensure_baseline_auth_data(conn)
        _sync_identity_sequences(conn)
        conn.commit()


def _sync_identity_sequences(conn: psycopg.Connection):
    # Seed scripts insert explicit IDs; align serial sequences to avoid PK collisions.
    with conn.cursor() as cur:
        for table_name, id_column in INSERT_ID_COLUMNS.items():
            statement = sql.SQL(
                """
                SELECT setval(
                    pg_get_serial_sequence({table_lit}, {column_lit}),
                    COALESCE((SELECT MAX({id_col}) FROM {table_ident}), 0) + 1,
                    false
                )
                """
            ).format(
                table_lit=sql.Literal(table_name),
                column_lit=sql.Literal(id_column),
                id_col=sql.Identifier(id_column),
                table_ident=sql.Identifier(table_name),
            )
            cur.execute(statement)


def _ensure_baseline_auth_data(conn: psycopg.Connection):
    # Guarantees a known login path for UI even on partially seeded legacy DBs.
    conn.execute(
        """
        INSERT INTO roles(role_id, role_name, description)
        VALUES (4, 'CDS Manager', 'Head of Career Development and Placement Services')
        ON CONFLICT (role_id) DO NOTHING
        """
    )
    conn.execute(
        """
        INSERT INTO users(
            user_id, username, email, password_hash, role_id, is_verified,
            full_name, status, is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (1000, "admin", "admin@local.dev", "admin123", 4, 1, "System Admin", "ACTIVE", 1),
    )

    # Keep seeded credentials consistent so all documented test users can log in.
    credential_pairs = []

    for n in range(1, 31):
        credential_pairs.append((f"hash{n}", f"student{n}"))

    for n in range(1, 11):
        credential_pairs.append((f"hash{30 + n}", f"alumni{n}"))

    for n in range(1, 16):
        credential_pairs.append((f"hash{40 + n}", f"recruiter{n}"))

    for n in range(1, 6):
        credential_pairs.append((f"hash{55 + n}", f"cds{n}"))

    credential_pairs.append(("hash61", "cdsmanager1"))
    credential_pairs.append(("admin123", "admin"))

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE users SET password_hash = %s, is_active = 1, status = 'ACTIVE' WHERE username = %s",
            credential_pairs,
        )

def fetch_one(query: str, params: Iterable = ()) -> Optional[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_normalize_query(query), tuple(params))
            return cur.fetchone()


def fetch_all(query: str, params: Iterable = ()):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_normalize_query(query), tuple(params))
            return cur.fetchall()


def execute(query: str, params: Iterable = ()) -> int:
    normalized = _normalize_query(query)
    with _connect() as conn:
        with conn.cursor() as cur:
            is_insert = normalized.lstrip().upper().startswith("INSERT")
            has_returning = "RETURNING" in normalized.upper()
            if is_insert and "RETURNING" not in normalized.upper():
                table_match = re.search(r"(?is)INSERT\s+INTO\s+([a-zA-Z_][\w]*)", normalized)
                if table_match:
                    table_name = table_match.group(1).lower()
                    id_column = INSERT_ID_COLUMNS.get(table_name)
                    if id_column:
                        normalized = normalized.rstrip().rstrip(";") + f" RETURNING {id_column}"
                        has_returning = True

            cur.execute(normalized, tuple(params))
            inserted_id = 0
            if is_insert and has_returning:
                row = cur.fetchone()
                if row:
                    inserted_id = int(next(iter(row.values())))
            conn.commit()
            return inserted_id


def execute_many(query: str, params_list: Iterable[Iterable]):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(_normalize_query(query), params_list)
        conn.commit()
