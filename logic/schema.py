"""
השלמת עמודות שנוספו למודל אחרי שהטבלאות כבר נוצרו.

db.create_all() יוצר טבלאות חסרות בלבד ואינו נוגע בטבלה קיימת, ולכן עמודה
חדשה לא מגיעה לבסיס הנתונים שבענן. אין כאן Alembic, אז ההשלמה נעשית בעליית
השרת. הפעולה בטוחה לחזרה — עמודה שכבר קיימת מדולגת.
"""
from sqlalchemy import inspect, text

# טבלה -> עמודה -> טיפוס. טיפוסים ניטרליים שמובנים גם ב-Postgres וגם ב-SQLite.
ADDED_COLUMNS = {
    'users': {
        'pin_hash_husband': 'VARCHAR(256)',
    },
}


def ensure_schema(db):
    """מוסיף את העמודות החסרות ומחזיר את רשימת מה שנוסף בפועל."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    added = []

    for table, columns in ADDED_COLUMNS.items():
        # טבלה שנוצרה זה עתה כבר כוללת את כל העמודות של המודל
        if table not in existing_tables:
            continue

        present = {column['name'] for column in inspector.get_columns(table)}
        for name, column_type in columns.items():
            if name in present:
                continue
            db.session.execute(
                text(f'ALTER TABLE {table} ADD COLUMN {name} {column_type}'))
            db.session.commit()
            added.append(f'{table}.{name}')

    return added
