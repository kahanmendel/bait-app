"""
חישוב ימי הפרישה הצפויים למשתמשת — מקור אמת אחד ללוח הראשי ולשלוחה
הטלפונית, כדי ששני הממשקים לא יענו תשובות שונות על אותה שאלה.

כולל את מה שהחישוב הבסיסי ב-calculations.py אינו יודע לבדו: וסתות קבועות
שכבר נקבעו, וביטול הווסתות אחרי 90 יום מתחילת הריון.
"""
from models import Veeset, VesetKavua
from logic.calculations import get_all_expected
from logic.kavua import get_kavua_expected


def get_user_expected(user):
    """
    מחזיר (vesetot, expected, active_kavuot):
    הראיות בסדר עולה, ימי הפרישה הצפויים ממוינים לפי תאריך, והקבועות הפעילות.
    """
    # ייבוא מקומי — routes/pregnancy מייבא מ-logic, וייבוא ברמת המודול ייצור מעגל
    from routes.pregnancy import check_pregnancy_cancel_vesetot

    check_pregnancy_cancel_vesetot(user)

    vesetot = Veeset.query.filter_by(user_id=user.id)\
                          .order_by(Veeset.gregorian_date).all()

    # אחרי 90 יום מתחילת הריון אין ימי פרישה כלל
    if user.pregnancy_active and user.pregnancy_vesetot_cancelled_at:
        return vesetot, [], []

    expected = get_all_expected(user, vesetot)
    active_kavuot = VesetKavua.query.filter_by(user_id=user.id, active=True).all()

    if vesetot:
        last = vesetot[-1]
        for kavua in active_kavuot:
            kavua_expected = get_kavua_expected(kavua, last)
            if kavua_expected:
                expected.append(kavua_expected)

    return vesetot, sorted(expected, key=lambda x: x['gregorian_date']), active_kavuot
