"""Read the database's tables, columns and keys into text for the prompt.

The model can only write correct SQL for tables it can see, so the
prompt carries the schema. Reading it from the live database (as the
read-only role) instead of a hand-kept file means the prompt can never
drift from what the database really has.

The same Schema object gives the validator its table allowlist, gives
retrieval one short description per table to embed, and lists the
tables joined to a given table so retrieval can bring them along.

Run `python -m nl2sql.schema` from backend/ to print the prompt text.
"""

from __future__ import annotations

import re
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field

import psycopg
from psycopg import sql

from nl2sql.config import Settings, load_settings
from nl2sql.db import DatabaseError, connect

# Columns the model is never shown; the validator also refuses them.
# staff.password is a credential hash, staff.picture is binary.
from nl2sql.validate import HIDDEN_COLUMNS

# Short text columns with this few distinct values get them listed in
# the prompt (category names, ratings), so the model matches real
# values instead of guessing spellings.
MAX_LISTED_VALUES = 20

# Never list values from columns that hold personal details.
_PERSONAL = re.compile(r"email|phone|user|password|address|postal", re.IGNORECASE)

# ON UPDATE/ON DELETE rules only matter for writes, which never happen.
_FK_ACTIONS = re.compile(
    r"\s+ON (UPDATE|DELETE) (CASCADE|RESTRICT|SET NULL|SET DEFAULT|NO ACTION)"
)

# Plain text columns only; arrays such as text[] are not listed.
_TEXT_TYPE = re.compile(r"^(text|character( varying)?(\(\d+\))?)$")


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    not_null: bool
    # Distinct values, only for short text columns (see MAX_LISTED_VALUES).
    values: tuple[str, ...] = ()
    # The column's database comment, e.g. what a code like PRIJEM means.
    comment: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    # Constraint text as Postgres prints it, e.g. "PRIMARY KEY (film_id)".
    constraints: tuple[str, ...]
    # Tables this one has a foreign key to.
    references: frozenset[str]
    # The table's database comment.
    comment: str = ""
    # The name as SQL must write it: "order" is quoted, film is not.
    quoted_name: str = ""


@dataclass(frozen=True)
class Schema:
    """The visible part of the database, keyed by lowercase table name."""

    tables: dict[str, Table]
    # Enum type name -> its labels in order, e.g. mpaa_rating.
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Domain name -> base type, e.g. year -> integer.
    domains: dict[str, str] = field(default_factory=dict)

    @property
    def allowed_tables(self) -> frozenset[str]:
        """Every table generated SQL may read."""
        return frozenset(self.tables)

    def related(self, names: Iterable[str]) -> set[str]:
        """The given tables plus every table joined to them in one step.

        Joins come from foreign keys, and from a column named like
        another table's key (payment.customer_id -> customer), because
        partitioned tables such as payment carry no foreign keys of
        their own in Pagila.
        """
        chosen = {n.lower() for n in names if n.lower() in self.tables}
        result = set(chosen)
        for name, table in self.tables.items():
            links = set(table.references) | {
                c.name[: -len("_id")]
                for c in table.columns
                if c.name.endswith("_id") and c.name[: -len("_id")] in self.tables
            }
            links.discard(name)
            if name in chosen:
                result |= links
            elif links & chosen:
                result.add(name)
        return result

    def to_prompt(self, names: Iterable[str] | None = None) -> str:
        """CREATE statements for the given tables (all when None).

        Types the tables use (enums, domains) come first, so the model
        knows rating is one of five values and release_year an integer.
        """
        picked = sorted(
            self.tables
            if names is None
            else {n.lower() for n in names} & set(self.tables)
        )
        used_types = {c.type for name in picked for c in self.tables[name].columns}
        parts = [
            f"CREATE TYPE {name} AS ENUM ({', '.join(_quote(v) for v in labels)});"
            for name, labels in sorted(self.enums.items())
            if name in used_types
        ]
        parts += [
            f"CREATE DOMAIN {name} AS {base};"
            for name, base in sorted(self.domains.items())
            if name in used_types
        ]
        parts += [_create_table(self.tables[name]) for name in picked]
        return "\n\n".join(parts)

    def describe(self, name: str) -> str:
        """One table as a short plain-text document, for embedding.

        Names are spelled out with spaces so a question like "which
        customers spent the most" lands near customer and payment.
        """
        table = self.tables[name.lower()]
        columns = ", ".join(c.name.replace("_", " ") for c in table.columns)
        text = (
            f"Table {table.name.replace('_', ' ')} ({table.name}). Columns: {columns}."
        )
        joined = sorted(self.related([table.name]) - {table.name})
        if table.comment:
            text += f" {table.comment}"
        if joined:
            text += f" Joins to: {', '.join(joined)}."
        listed = [c for c in table.columns if c.values]
        for column in listed:
            text += f" {column.name} values: {', '.join(column.values)}."
        return text


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _display_value(value: str) -> str:
    """A listed value as the prompt shows it.

    Padding is trimmed (Pagila's character(20) names), but a value that
    is only blanks is shown quoted, because ' ' and '' are different
    values and the model has to write the right one.
    """
    return _quote(value) if not value.strip() else value.strip()


def _one_line(text: str | None) -> str:
    """A database comment on one line; None (no comment) becomes ''."""
    return " ".join((text or "").split())


def _create_table(table: Table) -> str:
    lines = []
    for c in table.columns:
        line = f"  {c.name} {c.type}" + (" NOT NULL" if c.not_null else "")
        notes = c.comment
        if c.values:
            listed = ", ".join(c.values)
            notes = f"{notes} Values: {listed}" if notes else f"values: {listed}"
        if notes:
            line += f"  -- {notes}"
        lines.append(line)
    lines += [f"  {text}" for text in table.constraints]
    # Commas go between items, before any trailing "-- values" comment.
    body = []
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        head, sep, comment = line.partition("  -- ")
        body.append(head + ("" if last else ",") + (f"  -- {comment}" if sep else ""))
    head = f"-- {table.comment}\n" if table.comment else ""
    return head + f"CREATE TABLE {table.quoted_name or table.name} (\n" + "\n".join(body) + "\n);"


# Ordinary and partitioned tables in public, without the monthly payment
# partitions: queries use the parent table.
_TABLES_SQL = """
SELECT c.oid, c.relname, obj_description(c.oid, 'pg_class'), quote_ident(c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
ORDER BY c.relname
"""

_COLUMNS_SQL = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       col_description(a.attrelid, a.attnum)
FROM pg_attribute a
WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attrelid, a.attnum
"""

_CONSTRAINTS_SQL = """
SELECT con.conrelid, con.contype, pg_get_constraintdef(con.oid), ref.relname
FROM pg_constraint con
LEFT JOIN pg_class ref ON ref.oid = con.confrelid
WHERE con.conrelid = ANY(%s) AND con.contype IN ('p', 'f')
ORDER BY con.conrelid, con.contype DESC, con.conname
"""

_ENUMS_SQL = """
SELECT t.typname, e.enumlabel
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
JOIN pg_enum e ON e.enumtypid = t.oid
WHERE n.nspname = 'public'
ORDER BY t.typname, e.enumsortorder
"""

_DOMAINS_SQL = """
SELECT t.typname, format_type(t.typbasetype, t.typtypmod)
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public' AND t.typtype = 'd'
"""


def _listed_values(
    conn: psycopg.Connection, table: str, column: str
) -> tuple[str, ...]:
    """Distinct values of a short text column, or () if there are too many."""
    query = sql.SQL(
        "SELECT DISTINCT {col}::text FROM {tbl} WHERE {col} IS NOT NULL LIMIT %s"
    ).format(col=sql.Identifier(column), tbl=sql.Identifier("public", table))
    rows = conn.execute(query, (MAX_LISTED_VALUES + 1,)).fetchall()
    if len(rows) > MAX_LISTED_VALUES:
        return ()
    return tuple(sorted(_display_value(r[0]) for r in rows))


def load_schema(conn: psycopg.Connection) -> Schema:
    """Read the public schema through an open connection.

    Reads the system catalogs directly. That is allowed here because
    this is the app's own code, not model-written SQL; the validator
    still blocks generated SQL from touching the catalogs.
    """
    tables_rows = conn.execute(_TABLES_SQL).fetchall()
    oids = [oid for oid, _, _, _ in tables_rows]
    names = {oid: name for oid, name, _, _ in tables_rows}
    table_comments = {oid: _one_line(comment) for oid, _, comment, _ in tables_rows}
    quoted = {oid: q for oid, _, _, q in tables_rows}

    columns: dict[int, list[tuple[str, str, bool, str]]] = {oid: [] for oid in oids}
    for oid, name, type_name, not_null, comment in conn.execute(_COLUMNS_SQL, (oids,)):
        if (names[oid], name) not in HIDDEN_COLUMNS:
            columns[oid].append((name, type_name, not_null, _one_line(comment)))

    constraints: dict[int, list[str]] = {oid: [] for oid in oids}
    references: dict[int, set[str]] = {oid: set() for oid in oids}
    for oid, kind, definition, ref_name in conn.execute(_CONSTRAINTS_SQL, (oids,)):
        constraints[oid].append(_FK_ACTIONS.sub("", definition))
        if kind == "f" and ref_name:
            references[oid].add(ref_name)

    enums: dict[str, list[str]] = {}
    for type_name, label in conn.execute(_ENUMS_SQL):
        enums.setdefault(type_name, []).append(label)
    domains = dict(conn.execute(_DOMAINS_SQL).fetchall())

    tables = {}
    for oid in oids:
        name = names[oid]
        cols = []
        for col_name, type_name, not_null, comment in columns[oid]:
            values: tuple[str, ...] = ()
            if _TEXT_TYPE.match(type_name) and not _PERSONAL.search(col_name):
                values = _listed_values(conn, name, col_name)
            cols.append(Column(col_name, type_name, not_null, values, comment))
        tables[name.lower()] = Table(
            name=name,
            columns=tuple(cols),
            constraints=tuple(constraints[oid]),
            references=frozenset(references[oid]),
            comment=table_comments[oid],
            quoted_name=quoted[oid],
        )
    return Schema(
        tables=tables,
        enums={k: tuple(v) for k, v in enums.items()},
        domains=domains,
    )


_cache: dict[str, Schema] = {}
_cache_lock = threading.Lock()


def get_schema(settings: Settings) -> Schema:
    """The schema for settings.database_url, read once per process.

    Cached because it only changes when someone runs a db/ script, and
    reading it takes a few dozen catalog queries. A failed read is not
    cached, so the next request tries again. Raises db.DatabaseError if
    the database cannot be reached.
    """
    with _cache_lock:
        cached = _cache.get(settings.database_url)
        if cached is not None:
            return cached
        try:
            with connect(settings) as conn:
                schema = load_schema(conn)
        except psycopg.Error as exc:
            raise DatabaseError(f"Could not read the schema: {exc}") from exc
        _cache[settings.database_url] = schema
        return schema


def main() -> int:
    """Print the prompt text, as a quick check that introspection works."""
    try:
        schema = get_schema(load_settings())
    except DatabaseError as exc:
        print(exc)
        return 1
    print(schema.to_prompt())
    print(f"\n-- {len(schema.tables)} tables: {', '.join(sorted(schema.tables))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
