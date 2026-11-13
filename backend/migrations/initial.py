from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 轻量幂等迁移：create_all 负责新表，已存在的表通过检查器补齐新增列。
_EXTRA_COLUMNS = {
    "datasets": {"supersedes_id": "INT NULL"},
}


def _ensure_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _EXTRA_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns()


if __name__ == '__main__':
    migrate()
