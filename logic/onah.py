"""
חישוב עונה (יום/לילה) לפי שעה, תאריך ומיקום משתמשת.
עונת יום: מהנץ החמה עד השקיעה
עונת לילה: מהשקיעה עד הנץ (שייכת ליום העברי הבא)
"""
import requests
from datetime import datetime, date, time
import os

SUNRISE_SUNSET_API = "https://api.sunrise-sunset.org/json"

def get_sun_times(lat: float, lon: float, d: date) -> dict:
    """מחזיר שעות נץ ושקיעה בשעון מקומי (UTC+3 לישראל)"""
    try:
        resp = requests.get(SUNRISE_SUNSET_API, params={
            'lat': lat, 'lng': lon,
            'date': d.strftime('%Y-%m-%d'),
            'formatted': 0
        }, timeout=5)
        data = resp.json()['results']
        # ממיר UTC לשעון ישראל (UTC+2/+3)
        from datetime import timezone, timedelta
        tz_israel = timedelta(hours=3)  # שעון קיץ — ניתן לשפר
        sunrise_utc = datetime.fromisoformat(data['sunrise'])
        sunset_utc = datetime.fromisoformat(data['sunset'])
        sunrise_local = (sunrise_utc + tz_israel).time()
        sunset_local = (sunset_utc + tz_israel).time()
        return {'hanetz': sunrise_local, 'shkia': sunset_local}
    except Exception:
        # ברירת מחדל לירושלים
        return {'hanetz': time(6, 0), 'shkia': time(19, 0)}


def determine_onah(sighting_time: str, sighting_date: date,
                   user) -> str:
    """
    קובע עונה לפי שעת ראייה.
    מחזיר 'yom' או 'layla'.
    שים לב: לילה = אחרי שקיעה או לפני הנץ → שייך ליום העברי הבא.
    """
    h, m = map(int, sighting_time.split(':'))
    t = time(h, m)

    if user.use_auto_times:
        sun = get_sun_times(user.location_lat, user.location_lon, sighting_date)
    else:
        hh, mm = map(int, user.custom_hanetz.split(':'))
        sh, sm = map(int, user.custom_shkia.split(':'))
        sun = {'hanetz': time(hh, mm), 'shkia': time(sh, sm)}

    if sun['hanetz'] <= t < sun['shkia']:
        return 'yom'
    else:
        return 'layla'
