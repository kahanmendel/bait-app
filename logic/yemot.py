"""
עוזרי פרוטוקול לשלוחת API של ימות המשיח (ymgateway).

ימות קוראת ל-URL שלנו ב-GET (או POST, לפי ההגדרה בשלוחה) ומצרפת:
    ApiCallId    מזהה ייחודי לשיחה
    ApiPhone     מספר המתקשר
    ApiDID       המספר אליו התקשרו
    ApiExtension נתיב השלוחה הנוכחית (למשל "2/1")
    ApiEnterID   מזהה הכניסה לשלוחה
    ApiTime      חותמת זמן
    hangup=yes   נשלח כשהמתקשר ניתק
בנוסף ימות מחזירה בכל בקשה את כל הערכים שכבר נקראו בשיחה (לפי שם המשתנה
שנתנו ב-read), וכך אפשר לנהל תפריט רב-שלבי בלי לשמור מצב בשרת.

התשובה שלנו היא טקסט גולמי (text/plain, UTF-8). פקודות מחוברות ב-'&':
    read=<הודעות>=<אפשרויות>   השמעת הודעה וקריאת קלט למשתנה
    id_list_message=<הודעות>   השמעת הודעה בלבד
    go_to_folder=<יעד>         מעבר לשלוחה, או 'hangup' לניתוק

<הודעות> הוא רצף פריטים מופרדים בנקודה, כל פריט עם קידומת סוג:
    t-  טקסט להקראה (TTS)   d-  ספרות אחת אחת   n-  מספר
    f-  קובץ מוקלט          date-/dateH-  תאריך לועזי/עברי
"""
import re

# תווים שימות אוסרת בתוך טקסט TTS. הנקודה משמשת כמפריד בין הודעות,
# הקו התחתי והאמפרסנד הם מפרידים בפרוטוקול עצמו.
_INVALID_TTS_CHARS = re.compile(r'[.\-"\'&|–—]')


def clean(text) -> str:
    """מנקה תווים שימות לא מקבלת בטקסט להקראה."""
    return _INVALID_TTS_CHARS.sub(' ', str(text)).strip()


# ===== בוני הודעות =====

def t(text) -> str:
    """טקסט להקראה ב-TTS."""
    return 't-' + clean(text)


def d(digits) -> str:
    """הקראת ספרה אחר ספרה (מספר טלפון, קוד)."""
    return 'd-' + str(digits)


def n(number) -> str:
    """הקראה כמספר שלם (חמישים ושבע)."""
    return 'n-' + str(number)


def f(path) -> str:
    """השמעת קובץ מוקלט מהמערכת."""
    return 'f-' + str(path)


def g_date(value) -> str:
    """תאריך לועזי מ-datetime.date."""
    return 'date-' + value.strftime('%d/%m/%Y')


def h_date(value) -> str:
    """התאריך העברי המקביל לתאריך לועזי מ-datetime.date."""
    return 'dateH-' + value.strftime('%d/%m/%Y')


def msgs(*parts) -> str:
    """מחבר פריטי הודעה לרצף אחד."""
    return '.'.join(p for p in parts if p)


# ===== בוני פקודות =====

def read(messages, val_name, max_digits=None, min_digits=1, sec_wait=7,
         re_enter=False, digits_allowed=None, attempts=None,
         typing_playback='No', block_asterisk=False, block_zero=False,
         allow_empty=False, empty_val=None) -> str:
    """
    השמעת הודעה וקריאת הקשות לתוך משתנה בשם val_name.

    הערך יחזור אלינו בבקשה הבאה כפרמטר בשם val_name, וימשיך לחזור בכל
    שאר בקשות השיחה. re_enter=True יגרום לימות לשאול שוב גם אם כבר יש ערך.
    סדר האפשרויות קבוע על ידי ימות ואסור לשנותו.
    """
    if digits_allowed is not None:
        digits_allowed = '.'.join(str(x) for x in digits_allowed)

    options = [
        val_name,
        'yes' if re_enter else 'no',
        '' if max_digits is None else str(max_digits),
        str(min_digits),
        str(sec_wait),
        typing_playback,
        'yes' if block_asterisk else 'no',
        'yes' if block_zero else 'no',
        '',                                     # replace_char
        digits_allowed or '',
        '' if attempts is None else str(attempts),
        'Ok' if allow_empty else '',
        '' if empty_val is None else str(empty_val),
        '',                                     # block_change_keyboard
    ]
    return 'read={}={}'.format(messages, ','.join(options))


def say(messages) -> str:
    """השמעת הודעה בלי לקרוא קלט."""
    return 'id_list_message=' + messages


def go_to(folder) -> str:
    """מעבר לשלוחה אחרת. נתיב מוחלט מהשורש, למשל '/2/1'."""
    return 'go_to_folder=' + folder


def hangup() -> str:
    """ניתוק השיחה."""
    return 'go_to_folder=hangup'


def combine(*commands) -> str:
    """מחבר כמה פקודות לתשובה אחת."""
    return '&'.join(c for c in commands if c)
