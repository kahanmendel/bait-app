"""
חישוב מחדש של כל הלוגיקה אחרי עריכת/מחיקת וסת.
"""
from extensions import db
from models import Veeset, VesetKavua, User
from logic.kavua import check_kavua, should_cancel_kavua
from datetime import datetime


def recalculate_all(user_id: int):
    """
    מחשב מחדש את כל הקבועות למשתמשת.
    שלב 1: מוחק כל קבועות קיימות
    שלב 2: עובר על ווסתות בסדר כרונולוגי ויוצר קבועות
    שלב 3: בודק ביטול — רק על קבועות שנוצרו, ורק על ווסתות שאחריהן
    """
    VesetKavua.query.filter_by(user_id=user_id).delete()
    db.session.commit()

    vesetot = Veeset.query.filter_by(user_id=user_id)\
                  .order_by(Veeset.gregorian_date).all()

    user = db.session.get(User, user_id)
    messages = []

    # שלב 1: יצירת קבועות
    for i in range(len(vesetot)):
        subset = vesetot[:i+1]
        kavua = check_kavua(subset)
        if kavua:
            existing = VesetKavua.query.filter_by(
                user_id=user_id, type=kavua['type'], active=True).first()
            if not existing:
                established_date = vesetot[i].gregorian_date
                new_kavua = VesetKavua(
                    user_id=user_id,
                    type=kavua['type'],
                    hebrew_day_of_month=kavua.get('hebrew_day'),
                    haflagah_days=kavua.get('days'),
                    onah=kavua['onah'],
                    active=True,
                    established_at=datetime.combine(
                        established_date, datetime.min.time())
                )
                db.session.add(new_kavua)
                db.session.commit()
                messages.append(kavua['message'])

    # שלב 2: בדיקת ביטול — רק על ווסתות שאחרי כל קבועה
    active_kavuot = VesetKavua.query.filter_by(
        user_id=user_id, active=True).all()

    for k in active_kavuot:
        # רק ווסתות שאחרי הקבועה
        vesetot_after = [v for v in vesetot
                         if v.gregorian_date > k.established_at.date()]
        if should_cancel_kavua(k, vesetot_after, user):
            k.active = False
            messages.append('וסת קבועה בוטלה לאחר חישוב מחדש')

    db.session.commit()
    return messages
