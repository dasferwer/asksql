import os

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def init():
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(350029)")
        conn.execute("""CREATE TABLE IF NOT EXISTS questions (
            id uuid PRIMARY KEY, owner text NOT NULL, question text NOT NULL,
            parent uuid REFERENCES questions(id), response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""")
