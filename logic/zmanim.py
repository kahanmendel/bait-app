"""
זמני הנץ ושקיעה — חישוב מקומי בלי תלות ברשת.

עד כאן הזמנים נשלפו מ-api.sunrise-sunset.org, וכל כשל נפל בשקט ל-6:00
ו-19:00. נפילה כזו אינה "אי דיוק" קטן: בירושלים השקיעה בנובמבר היא ב-16:40,
כך שראייה ב-17:30 נרשמה כעונת יום במקום עונת לילה — וזו גם טעות של יום שלם
ביום העברי. אותה טעות קרתה גם כשה-API הצליח, כי ההמרה ל-UTC הייתה +3 קבוע
ולא התחשבה בשעון החורף.

hdate, שכבר נדרש בפרויקט לתאריכים העבריים, מחשב את הזמנים מקומית ועם אזור
זמן אמיתי, ולכן אין כאן יותר קריאת רשת שיכולה להיכשל. מה שעוד יכול להיכשל —
שגיאת חישוב, או זמנים ידניים חסרים או פגומים — מסומן כבלתי אמין ומדווח
בהתראה, במקום לעבור בשקט.
"""
from datetime import date, time
from typing import NamedTuple

from hdate import Location, Zmanim

# כל המשתמשות בישראל. המיקום (קו רוחב ואורך) נלקח מהמשתמשת, אזור הזמן קבוע.
DEFAULT_TIMEZONE = 'Asia/Jerusalem'

# ברירת מחדל גסה לירושלים. משמשת רק כשגם החישוב המקומי נכשל, ואז הערך
# מסומן כבלתי אמין ונשלחת התראה.
FALLBACK_HANETZ = time(6, 0)
FALLBACK_SHKIA = time(19, 0)

DEFAULT_LAT = 31.7683
DEFAULT_LON = 35.2137


class SunTimes(NamedTuple):
    """
    זמני הנץ ושקיעה ליום אחד, עם המקור שממנו הגיעו.

    source: 'computed' — חושב מקומית, 'custom' — זמנים ידניים של המשתמשת,
            'fallback' — ברירת המחדל הגסה.
    reliable: False פירושו שהעונה שתיקבע מהזמנים האלה אינה אמינה.
    """
    hanetz: time
    shkia: time
    source: str
    reliable: bool


def compute_sun_times(lat, lon, d: date,
                      timezone: str = DEFAULT_TIMEZONE) -> SunTimes:
    """
    הנץ ושקיעה לתאריך ולמיקום, מחושבים מקומית.

    זורק חריגה אם החישוב נכשל, כדי שהקורא יחליט מה לעשות. אין כאן נפילה
    שקטה לברירת מחדל.
    """
    location = Location(
        name='user',
        latitude=DEFAULT_LAT if lat is None else float(lat),
        longitude=DEFAULT_LON if lon is None else float(lon),
        timezone=timezone,
        diaspora=False,
    )
    zmanim = Zmanim(date=d, location=location).zmanim
    return SunTimes(
        hanetz=zmanim['netz_hachama'].local.time(),
        shkia=zmanim['shkia'].local.time(),
        source='computed',
        reliable=True,
    )


def custom_sun_times(user) -> SunTimes:
    """
    הזמנים הידניים של המשתמשת.

    זורק ValueError אם אחד מהם חסר או אינו בפורמט HH:MM — זה בדיוק המצב של
    "אין זמן מדויק", והקורא מתריע עליו.
    """
    raw_hanetz = (user.custom_hanetz or '').strip()
    raw_shkia = (user.custom_shkia or '').strip()
    if not raw_hanetz or not raw_shkia:
        raise ValueError('זמנים ידניים חסרים')

    def parse(raw, label):
        parts = raw.split(':')
        if len(parts) != 2:
            raise ValueError(f'{label} בפורמט לא תקין: {raw}')
        hour, minute = (int(p) for p in parts)
        return time(hour, minute)

    return SunTimes(
        hanetz=parse(raw_hanetz, 'הנץ ידני'),
        shkia=parse(raw_shkia, 'שקיעה ידנית'),
        source='custom',
        reliable=True,
    )


def fallback_sun_times() -> SunTimes:
    """ברירת המחדל הגסה, מסומנת תמיד כבלתי אמינה."""
    return SunTimes(hanetz=FALLBACK_HANETZ, shkia=FALLBACK_SHKIA,
                    source='fallback', reliable=False)
