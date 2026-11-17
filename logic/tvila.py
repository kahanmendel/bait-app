"""
חישוב הפסק טהרה ויום הטבילה.
אשכנזים: 5 ימים מתחילת ראייה (כולל יום הראייה)
בית יוסף: 4 ימים
הפסק טהרה: לפני שקיעה של היום האחרון
7 נקיים: מתחילים מהלילה שאחרי ההפסק
טבילה: לילה שאחרי יום 7
"""
from datetime import date, timedelta
from logic.onah import user_sun_times
from hdate import HebrewDate


def calc_earliest_hefsek(veeset, user) -> dict:
    """
    מחשב את היום המוקדם ביותר לעשות הפסק טהרה.
    אשכנזים: יום 5 (כולל יום הראייה)
    בית יוסף: יום 4
    """
    days = user.yemei_sfira_days  # 4 או 5
    hefsek_date = veeset.gregorian_date + timedelta(days=days - 1)
    hd = HebrewDate.from_gdate(hefsek_date)

    # שעת שקיעה. user_sun_times מכבד זמנים ידניים, מחשב מקומית אחרת,
    # ומתריע בעצמו על כל מצב שבו אין זמן מדויק
    times = user_sun_times(user, hefsek_date)
    shkia = times.shkia.strftime('%H:%M')

    return {
        'hefsek_date': hefsek_date,
        'hebrew_date': f'{hd.day} {hd.month} {hd.year}',
        'before_shkia': shkia,
        'minhag': 'אשכנזים' if days == 5 else 'בית יוסף',
        'label': f'הפסק טהרה ניתן לעשות ביום {hd.day} {hd.month} לפני השקיעה ({shkia})'
    }


def calc_tvila(hefsek_date: date) -> dict:
    """
    מחשב 7 ימים נקיים ויום טבילה.
    7 נקיים מתחילים מהלילה שאחרי ההפסק (= הלילה של היום הבא = יום עברי הבא).
    טבילה = לילה שאחרי יום 7 = יום לועזי 8 אחרי ההפסק.
    """
    # לילה ראשון = אחרי שקיעת יום ההפסק = יום לועזי הבא
    shiva_start = hefsek_date + timedelta(days=1)
    # יום 7 נקי
    shiva_end = hefsek_date + timedelta(days=7)
    # טבילה = לילה שאחרי יום 7 = יום לועזי 8
    tvila_date = hefsek_date + timedelta(days=8)

    hd_start = HebrewDate.from_gdate(shiva_start)
    hd_end = HebrewDate.from_gdate(shiva_end)
    hd_tvila = HebrewDate.from_gdate(tvila_date)

    return {
        'shiva_start': shiva_start,
        'shiva_start_hebrew': f'{hd_start.day} {hd_start.month} {hd_start.year}',
        'shiva_end': shiva_end,
        'shiva_end_hebrew': f'{hd_end.day} {hd_end.month} {hd_end.year}',
        'tvila_date': tvila_date,
        'tvila_hebrew': f'{hd_tvila.day} {hd_tvila.month} {hd_tvila.year}',
        'label': f'טבילה: ליל {hd_tvila.day} {hd_tvila.month} {hd_tvila.year} ({tvila_date})'
    }
