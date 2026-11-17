"""
קביעת עונה (יום/לילה) לפי שעה, תאריך ומיקום המשתמשת.

עונת יום: מהנץ החמה עד השקיעה.
עונת לילה: מהשקיעה עד הנץ.

הזמנים מחושבים מקומית ב-logic/zmanim.py. כל מצב שבו אין זמן מדויק — שגיאת
חישוב, או זמנים ידניים חסרים או פגומים — מחזיר עונה שמסומנת כבלתי אמינה
ושולח התראה למייל. הקוראים שכותבים ראייה לבסיס הנתונים מסמנים אותה
ב-onah_needs_review, כדי שתופיע לאימות ולא תיבלע בשקט.

שים לב: עונת לילה שייכת ליום העברי הבא. ההזזה הזאת אינה מיושמת בחישובים
כרגע — ראה README.
"""
from datetime import date, time

from logic.alerts import send_alert
from logic.zmanim import (
    compute_sun_times,
    custom_sun_times,
    fallback_sun_times,
)


def get_sun_times(lat, lon, d: date):
    """
    הנץ ושקיעה למיקום ולתאריך.

    חישוב מקומי. אם הוא נכשל — דבר שאינו אמור לקרות, כי אין כאן קריאת רשת —
    נשלחת התראה ומוחזרת ברירת מחדל גסה המסומנת כבלתי אמינה.
    """
    try:
        return compute_sun_times(lat, lon, d)
    except Exception as exc:
        fallback = fallback_sun_times()
        send_alert(
            'bait-app: חישוב הנץ ושקיעה נכשל',
            'חישוב הזמנים המקומי נכשל, והמערכת נפלה לברירת מחדל של '
            f'{fallback.hanetz:%H:%M} ו-{fallback.shkia:%H:%M}.\n'
            f'תאריך: {d}\nמיקום: {lat}, {lon}\n'
            f'שגיאה: {exc.__class__.__name__}: {exc}\n\n'
            'כל עונה שתיקבע עד לתיקון מסומנת כדורשת אימות.',
            key='zmanim_compute_failed',
        )
        return fallback


def user_sun_times(user, d: date):
    """
    הזמנים הרלוונטיים למשתמשת — ידניים אם ביקשה, ואחרת מחושבים.

    זמנים ידניים פגומים אינם מושתקים: נשלחת התראה, החישוב המקומי משמש
    כגיבוי מספרי, והתוצאה מסומנת כבלתי אמינה כי אינה מה שהמשתמשת ביקשה.
    """
    if getattr(user, 'use_auto_times', True):
        return get_sun_times(user.location_lat, user.location_lon, d)

    try:
        return custom_sun_times(user)
    except Exception as exc:
        send_alert(
            'bait-app: זמנים ידניים חסרים או פגומים',
            f'המשתמשת (id={getattr(user, "id", "?")}) מוגדרת לזמנים ידניים, '
            f'אבל הם אינם שמישים: {exc}\n'
            f'הנץ: {user.custom_hanetz!r}  שקיעה: {user.custom_shkia!r}\n'
            f'תאריך: {d}\n\n'
            'המערכת השתמשה בזמנים המחושבים למיקום שלה, והעונה סומנה '
            'כדורשת אימות.',
            key=f'custom_times_invalid:{getattr(user, "id", "?")}',
        )
        return get_sun_times(user.location_lat, user.location_lon, d)\
            ._replace(source='computed_instead_of_custom', reliable=False)


def determine_onah_checked(sighting_time: str, sighting_date: date, user):
    """
    קובע עונה ומחזיר (עונה, זמנים).

    העונה היא 'yom' או 'layla'. הזמנים כוללים reliable — False פירושו שהעונה
    נקבעה בלי זמן מדויק ויש לאמת אותה.
    """
    hour, minute = (int(part) for part in sighting_time.split(':'))
    times = user_sun_times(user, sighting_date)

    sighting = time(hour, minute)
    onah = 'yom' if times.hanetz <= sighting < times.shkia else 'layla'
    return onah, times

