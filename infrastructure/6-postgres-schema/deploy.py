"""One-off deploy of schema.sql to the SkyCargo PostgreSQL flexible server.

Uses Entra ID token auth (passwordless), matching the worker's auth model.
"""
from __future__ import annotations

import pathlib
import sys

import psycopg
from azure.identity import AzureCliCredential

HOST = "devpostgresvinay.postgres.database.azure.com"
DBNAME = "postgres"
PORT = 5432
SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def main() -> int:
    cred = AzureCliCredential()
    token = cred.get_token(SCOPE).token

    # The DB user is the signed-in Entra principal (UPN).
    import subprocess

    user = subprocess.check_output(
        ["az", "account", "show", "--query", "user.name", "-o", "tsv"],
        text=True,
        shell=True,
    ).strip()
    print(f"Connecting as: {user}")

    sql = pathlib.Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

    with psycopg.connect(
        host=HOST,
        dbname=DBNAME,
        user=user,
        port=PORT,
        sslmode="require",
        password=token,
        autocommit=True,
    ) as conn:
        conn.execute(sql)
    print("Schema deployed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
