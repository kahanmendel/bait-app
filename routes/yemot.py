"""
שלוחת ימות המשיח.

בשלוחה מסוג API בממשק של ימות מגדירים:
    type=api
    api_link=https://<כתובת השירות>/yemot?secret=<YEMOT_API_SECRET>

ימות קוראת לנתיב הזה בכל שלב בשיחה ומצרפת את כל הערכים שכבר נקראו בה, ולכן
הזרימה כאן היא פונקציה של הפרמטרים שהתקבלו: כל שלב מזוהה לפי אילו משתנים
כבר קיימים בבקשה. ראה logic/yemot.py לתיאור הפרוטוקול.

ערך שנקרא בשיחה נשאר בה עד סופה, ולכן תפריט חוזר משתמש ב-re_enter כדי
לדרוס את הבחירה הקודמת, ותהליך הדיווח מסתיים תמיד בניתוק — כך אין מצב שבו
ערכים ישנים מתוך התהליך גורמים לרישום כפול.
"""
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, request, current_app

from extensions import db
from models import User, Veeset, Reminder
from logic import yemot as y
from logic.calculations import get_all_expected, hdate_str
from logic.onah import determine_onah
from logic.recalculate import recalculate_all

yemot_bp = Blueprint('yemot', __name__)

# כמה ימי פרישה קרובים להקריא
UPCOMING_LIMIT = 3
# כמה תזכורות להקריא
REMINDERS_LIMIT = 3
# ניסיונות PIN לפני ניתוק
PIN_ATTEMPTS = 3

VESET_TYPE_NAMES = {
    'onah_beinonit': 'עונה בינונית',
    'yom_hachodesh': 'יום החודש',
    'haflagah': 'הפלגה',
    'or_zarua': 'אור זרוע',
}


def _reply(text):
    """תשובה לימות — טקסט גולמי ב-UTF-8."""
    return Response(text, mimetype='text/plain; charset=utf-8')


def _onah_name(onah):
    return 'עונת יום' if onah == 'yom' else 'עונת לילה'


def _normalize_phone(raw):
    return (raw or '').strip().replace('-', '').replace(' ', '').replace('+972', '0')


def _received_secret(values):
    """
    הסוד המשותף כפי שהגיע מימות.

    הדרך הנכונה להעביר אותו היא api_add_0=secret=... בהגדרות השלוחה. אם
    מגדירים אותו בתוך api_link כ-query string, ימות מצרפת את הפרמטרים שלה
    בסימן שאלה נוסף במקום ב-'&', והערך מגיע כ-'<הסוד>?ApiCallId=...'.
    """
    return (values.get('secret') or '').split('?', 1)[0]


def _find_user(phone):
    """מאתר משתמשת לפי מספר המתקשר — שלה או של בעלה."""
    if not phone:
        return None
    user = User.query.filter_by(phone=phone).first()
    if not user:
        user = User.query.filter_by(phone_husband=phone).first()
    return user


def _parse_date(digits):
    """DDMMYYYY -> date, או None אם לא תקין."""
    try:
        return datetime.strptime(digits, '%d%m%Y').date()
    except ValueError:
        return None


def _parse_time(digits):
    """HHMM -> 'HH:MM', או None אם לא תקין."""
    try:
        return datetime.strptime(digits, '%H%M').strftime('%H:%M')
    except ValueError:
        return None


def _say_time(time_str):
    """'14:30' -> הודעות להקראה כשעה ודקות."""
    hour, minute = (int(part) for part in time_str.split(':'))
    if minute:
        return y.msgs(y.n(hour), y.t('ו'), y.n(minute))
    return y.msgs(y.n(hour), y.t('בדיוק'))


def _describe_expected(item):
    """בונה רצף הודעות לתיאור יום פרישה אחד."""
    name = VESET_TYPE_NAMES.get(item['type'], 'יום פרישה')
    parts = [y.h_date(item['gregorian_date']), y.t(name)]
    if item['type'] == 'haflagah' and item.get('haflagah_days'):
        parts += [y.n(item['haflagah_days']), y.t('ימים')]
    parts.append(y.t(_onah_name(item.get('onah'))))
    return y.msgs(*parts)


# ===== נקודת הכניסה =====

@yemot_bp.route('/yemot', methods=['GET', 'POST'])
def yemot_gateway():
    values = request.values

    # ימות מודיעה על ניתוק ומצפה לתשובה ריקה
    if values.get('hangup') == 'yes':
        return _reply('')

    # אימות שהבקשה אכן מימות — סוד משותף שמוגדר ב-api_add_0
    secret = os.getenv('YEMOT_API_SECRET')
    if secret and _received_secret(values) != secret:
        current_app.logger.warning('yemot: bad or missing secret')
        return _reply(_end(y.t('שגיאת הגדרה במערכת')))

    user = _find_user(_normalize_phone(values.get('ApiPhone')))
    if not user:
        return _reply(_end(
            y.t('המספר שממנו התקשרת אינו רשום במערכת'),
            y.t('יש להירשם באתר ולהוסיף את המספר בהגדרות'),
        ))

    if not user.is_approved:
        return _reply(_end(y.t('החשבון שלך ממתין לאישור מנהל')))

    # ===== שלב 1: קוד PIN =====
    pin = values.get('pin')
    if not pin:
        return _reply(y.read(
            y.msgs(y.t('שלום'), y.t('נא להקיש את הקוד האישי ולסיים בסולמית')),
            'pin', max_digits=8, min_digits=4, attempts=PIN_ATTEMPTS,
        ))

    if not user.check_pin(pin):
        return _reply(_end(y.t('הקוד שהוקש שגוי')))

    # ===== שלב 2: תפריט ראשי =====
    menu = values.get('menu')
    if not menu:
        return _reply(_main_menu(greet=user.name))

    if menu == '1':
        return _reply(_flow_report(user, values))
    if menu == '2':
        return _reply(_flow_upcoming(user))
    if menu == '3':
        return _reply(_flow_last(user))
    if menu == '4':
        return _reply(_flow_reminders(user))

    # 9 או כל הקשה אחרת
    return _reply(_end(y.t('להתראות')))


def _main_menu(*messages, greet=None):
    """
    התפריט הראשי. re_enter מבטיח שהבחירה תישאל מחדש בכל חזרה לתפריט,
    ולא תילקח מהערך שנשמר בשיחה בפעם הקודמת.
    """
    parts = list(messages)
    if greet:
        parts.insert(0, y.t('שלום ' + greet))
    parts += [
        y.t('לדיווח ראייה חדשה הקישי 1'),
        y.t('לימי פרישה קרובים הקישי 2'),
        y.t('לפרטי הראייה האחרונה הקישי 3'),
        y.t('לתזכורות קרובות הקישי 4'),
        y.t('לסיום הקישי 9'),
    ]
    return y.read(y.msgs(*parts), 'menu', max_digits=1, min_digits=1,
                  re_enter=True, digits_allowed=[1, 2, 3, 4, 9])


def _end(*messages):
    """משמיע הודעה אחרונה ומנתק."""
    return y.combine(y.say(y.msgs(*messages)), y.hangup())


# ===== 1 — דיווח ראייה חדשה =====

def _flow_report(user, values):
    """
    תהליך הדיווח מסתיים תמיד בניתוק, כדי שהערכים שנקראו בו לא יישארו
    בשיחה ויגרמו לרישום נוסף אם המתקשרת תיכנס שוב לאותו תפריט.
    """
    when = values.get('rep_when')
    if not when:
        return y.read(
            y.msgs(y.t('לדיווח על ראייה שהיתה היום הקישי 1'),
                   y.t('לראייה שהיתה אתמול הקישי 2'),
                   y.t('לתאריך אחר הקישי 3')),
            'rep_when', max_digits=1, min_digits=1, digits_allowed=[1, 2, 3],
        )

    if when == '1':
        g_date = date.today()
    elif when == '2':
        g_date = date.today() - timedelta(days=1)
    else:
        raw_date = values.get('rep_date')
        if not raw_date:
            return y.read(
                y.t('נא להקיש את תאריך הראייה שתי ספרות יום שתי ספרות חודש וארבע ספרות שנה'),
                'rep_date', max_digits=8, min_digits=8, typing_playback='Date',
            )
        g_date = _parse_date(raw_date)
        if not g_date:
            return _end(y.t('התאריך שהוקש אינו תקין'))
        if g_date > date.today():
            return _end(y.t('לא ניתן לדווח על תאריך עתידי'))

    raw_time = values.get('rep_time')
    if not raw_time:
        return y.read(
            y.t('נא להקיש את שעת הראייה שתי ספרות שעה ושתי ספרות דקות'),
            'rep_time', max_digits=4, min_digits=4, typing_playback='Time',
        )
    time_str = _parse_time(raw_time)
    if not time_str:
        return _end(y.t('השעה שהוקשה אינה תקינה'))

    onah = determine_onah(time_str, g_date, user)

    confirm = values.get('rep_confirm')
    if not confirm:
        return y.read(
            y.msgs(
                y.t('הראייה תירשם בתאריך'),
                y.h_date(g_date),
                y.t('בשעה'),
                _say_time(time_str),
                y.t(_onah_name(onah)),
                y.t('לאישור הקישי 1'),
                y.t('לביטול הקישי 2'),
            ),
            'rep_confirm', max_digits=1, min_digits=1, digits_allowed=[1, 2],
        )

    if confirm != '1':
        return _end(y.t('הדיווח בוטל'))

    veeset = Veeset(
        user_id=user.id,
        gregorian_date=g_date,
        time_of_sighting=time_str,
        onah=onah,
        hebrew_date_str=hdate_str(g_date),
        duration_days=1,
        notes='דיווח טלפוני',
    )
    db.session.add(veeset)
    db.session.commit()

    try:
        recalculate_all(user.id)
    except Exception:
        current_app.logger.exception('yemot: recalculate_all failed')

    return _end(
        y.t('הראייה נרשמה בהצלחה בתאריך'),
        y.h_date(g_date),
        y.t(_onah_name(onah)),
    )


# ===== 2 — ימי פרישה קרובים =====

def _flow_upcoming(user):
    vesetot = Veeset.query.filter_by(user_id=user.id)\
                          .order_by(Veeset.gregorian_date).all()
    if not vesetot:
        return _main_menu(y.t('אין ראיות רשומות במערכת'))

    today = date.today()
    upcoming = [e for e in get_all_expected(user, vesetot)
                if e['gregorian_date'] >= today][:UPCOMING_LIMIT]
    if not upcoming:
        return _main_menu(y.t('אין ימי פרישה קרובים'))

    parts = [y.t('ימי הפרישה הקרובים')]
    parts += [_describe_expected(item) for item in upcoming]
    return _main_menu(*parts)


# ===== 3 — הראייה האחרונה =====

def _flow_last(user):
    veeset = Veeset.query.filter_by(user_id=user.id)\
                         .order_by(Veeset.gregorian_date.desc()).first()
    if not veeset:
        return _main_menu(y.t('אין ראיות רשומות במערכת'))

    return _main_menu(
        y.t('הראייה האחרונה נרשמה בתאריך'),
        y.h_date(veeset.gregorian_date),
        y.t('בשעה'),
        _say_time(veeset.time_of_sighting),
        y.t(_onah_name(veeset.onah)),
    )


# ===== 4 — תזכורות קרובות =====

def _flow_reminders(user):
    today = date.today()
    reminders = Reminder.query.filter_by(user_id=user.id, active=True)\
                              .filter(Reminder.gregorian_date >= today)\
                              .order_by(Reminder.gregorian_date)\
                              .limit(REMINDERS_LIMIT).all()
    if not reminders:
        return _main_menu(y.t('אין תזכורות קרובות'))

    parts = [y.t('התזכורות הקרובות')]
    parts += [y.msgs(y.g_date(r.gregorian_date), y.t(r.title or 'תזכורת'))
              for r in reminders]
    return _main_menu(*parts)
