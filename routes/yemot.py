"""
שלוחת ימות המשיח.

בשלוחה מסוג API בממשק של ימות מגדירים:
    type=api
    api_link=https://<כתובת השירות>/yemot
    api_add_0=secret=<YEMOT_API_SECRET>
    say_api_answer=no

ימות קוראת לנתיב הזה בכל שלב בשיחה ומצרפת את כל הערכים שכבר נקראו בה, ולכן
הזרימה כאן היא פונקציה של הפרמטרים שהתקבלו: כל שלב מזוהה לפי אילו משתנים
כבר קיימים בבקשה. ראה logic/yemot.py לתיאור הפרוטוקול.

שים לב לשם המטעה של re_enter_if_exists: ברירת המחדל 'no' גורמת לימות לשאול
את המשתנה מחדש, ואילו 'yes' אומר לה להשתמש בערך שכבר נאסף ולא להמתין להקשה.
לכן תפריט שנשלח עם 'yes' חוזר אלינו מיד עם הבחירה הישנה, נכנס שוב לאותו ענף
ויוצר לולאה במהירות מכונה.

ענף שרק קורא מידע חוזר לתפריט, כי המשתנה היחיד המעורב בו הוא menu והוא
נשאל מחדש. ענף שכותב נתונים מסתיים בניתוק: אין פקודה מתועדת שמנקה ערך
שכבר נאסף, וערכי הביניים שלו היו נשארים בשיחה וגורמים לכתיבה נוספת.
"""
import os
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, request, current_app

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import User, Veeset, Reminder, normalize_phone
from logic import yemot as y
from logic.calculations import hdate_str
from logic.expected import get_user_expected
from logic.onah import determine_onah
from logic.recalculate import recalculate_all

yemot_bp = Blueprint('yemot', __name__)

# כמה ימי פרישה קרובים להקריא
UPCOMING_LIMIT = 3
# כמה תזכורות להקריא
REMINDERS_LIMIT = 3
# ניסיונות PIN לפני ניתוק
PIN_ATTEMPTS = 3
# תקרת חזרות לתפריט באותה שיחה. מתקשר אמיתי לא מתקרב אליה, אבל אם ימות
# תחזיר בחירה ישנה במקום לשאול מחדש היא עוצרת לולאה תוך סיבוב אחד
MAX_MENU_ROUNDS = 12

VESET_TYPE_NAMES = {
    'onah_beinonit': 'עונה בינונית',
    'yom_hachodesh': 'יום החודש',
    'haflagah': 'הפלגה',
    'or_zarua': 'אור זרוע',
    'kavua_yom_hachodesh': 'וסת קבועה יום החודש',
    'kavua_haflagah': 'וסת קבועה הפלגה',
}
# סוגים שמקריאים עבורם גם את מספר ימי ההפלגה
HAFLAGAH_TYPES = ('haflagah', 'kavua_haflagah')

# כותרות לתזכורת. נבחרות מרשימה כי אין דרך אמינה להקליד עברית מלוח המקשים
REMINDER_TITLES = {
    '1': 'הפסק טהרה',
    '2': 'טבילה',
    '3': 'בדיקה',
    '4': 'תזכורת אישית',
}

# הקשה -> (שדה במודל, שם להקראה)
MINHAG_FIELDS = {
    '3': ('minhag_or_zarua', 'אור זרוע'),
    '4': ('minhag_shmirah_kefulah', 'שמירה כפולה'),
    '5': ('minhag_tikou', 'תיקו'),
    '6': ('minhag_haflagah_aruka', 'הפלגה ארוכה'),
}

# הקשה -> שעות מראש לתזכורת
REMINDER_HOURS = {'1': 6, '2': 12, '3': 24, '4': 48}


def _reply(text):
    """תשובה לימות — טקסט גולמי ב-UTF-8."""
    return Response(text, mimetype='text/plain; charset=utf-8')


def _onah_name(onah):
    return 'עונת יום' if onah == 'yom' else 'עונת לילה'


def _on_off(enabled):
    return 'מופעל' if enabled else 'מבוטל'


def _value(values, name):
    """
    הערך האחרון שהתקבל למשתנה שנקרא ב-read.

    ימות מצרפת בכל בקשה את כל הערכים שנאספו בשיחה, ובקריאה חוזרת של אותו
    משתנה נצפה עותק נוסף לצד הישן ולא דריסה שלו. בשני המקרים הערך העדכני
    הוא האחרון ברשימה.
    """
    collected = values.getlist(name)
    return collected[-1] if collected else None


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


def _digits(raw):
    """
    הספרות בלבד מתוך ערך שהתקבל מימות.

    כשקוראים עם typing_playback_mode של Date או Time ימות מחזירה את הערך
    מפורמט ולא כספרות גולמיות — '10-10' לשעה 10:10 ו '00-05' לשעה 00:05.
    """
    return re.sub(r'\D', '', raw or '')


def _parse_date(raw):
    """DDMMYYYY, גם אם הגיע מפורמט -> date, או None אם לא תקין."""
    try:
        return datetime.strptime(_digits(raw), '%d%m%Y').date()
    except ValueError:
        return None


def _parse_time(raw):
    """HHMM, גם אם הגיע מפורמט -> 'HH:MM', או None אם לא תקין."""
    try:
        return datetime.strptime(_digits(raw), '%H%M').strftime('%H:%M')
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
    if item['type'] in HAFLAGAH_TYPES and item.get('haflagah_days'):
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

    phone = normalize_phone(values.get('ApiPhone'))

    user = _find_user(phone)
    if not user:
        return _reply(_flow_register(phone, values))

    if not user.is_approved:
        return _reply(_end(y.t('החשבון שלך ממתין לאישור המנהל')))

    # ===== שלב 1: קוד PIN =====
    pin = _value(values, 'pin')
    if not pin:
        return _reply(y.read(
            y.msgs(y.t('שלום'), y.t('נא להקיש את הקוד האישי ולסיים בסולמית')),
            'pin', max_digits=8, min_digits=4, attempts=PIN_ATTEMPTS,
        ))

    # לבעל יכול להיות קוד משלו, ולכן האימות תלוי במספר שממנו התקשרו
    if not user.check_pin_for(phone, pin):
        return _reply(_end(y.t('הקוד שהוקש שגוי')))

    # ===== שלב 2: תפריט ראשי =====
    menu = _value(values, 'menu')
    if not menu:
        return _reply(_main_menu(greet=user.name))

    # בלם: אם התפריט חוזר אלינו שוב ושוב בלי שהמתקשרת בחרה מחדש, מסיימים
    # במקום להמשיך להחזיר אותו
    if len(values.getlist('menu')) > MAX_MENU_ROUNDS:
        current_app.logger.warning('yemot: menu round limit reached')
        return _reply(_end(y.t('אירעה תקלה'), y.t('נא להתקשר שוב')))

    if menu == '1':
        return _reply(_flow_report(user, values))
    if menu == '2':
        return _reply(_flow_upcoming(user))
    if menu == '3':
        return _reply(_flow_last(user))
    if menu == '4':
        return _reply(_flow_reminders(user))
    if menu == '5':
        return _reply(_flow_add_reminder(user, values))
    if menu == '6':
        return _reply(_flow_settings(user, phone, values))

    # 9 או כל הקשה אחרת
    return _reply(_end(y.t('להתראות')))


def _main_menu(*messages, greet=None):
    """
    התפריט הראשי, אחרי הודעות פתיחה אם יש.

    re_enter נשאר בברירת המחדל 'no' כדי שימות תשאל את הבחירה מחדש. הערך
    'yes' היה גורם לה להחזיר את הבחירה הקודמת בלי להמתין להקשה, וכך נוצרה
    הלולאה.
    """
    parts = list(messages)
    if greet:
        parts.insert(0, y.t('שלום ' + greet))
    parts += [
        y.t('לדיווח ראייה חדשה הקישי 1'),
        y.t('לימי פרישה קרובים הקישי 2'),
        y.t('לפרטי הראייה האחרונה הקישי 3'),
        y.t('לתזכורות קרובות הקישי 4'),
        y.t('להוספת תזכורת הקישי 5'),
        y.t('להגדרות הקישי 6'),
        y.t('לסיום הקישי 9'),
    ]
    return y.read(y.msgs(*parts), 'menu', max_digits=1, min_digits=1,
                  digits_allowed=[1, 2, 3, 4, 5, 6, 9])


def _end(*messages):
    """משמיע הודעה אחרונה ומנתק."""
    return y.combine(y.say(y.msgs(*messages)), y.hangup())


# ===== הרשמה טלפונית =====

def _flow_register(phone, values):
    """
    הרשמה למספר שאינו מוכר. החשבון נוצר לא מאושר, והמנהל מאשר אותו במסך
    הניהול. אין הענקת הרשאות ניהול דרך הטלפון, כי מזהה מתקשר ניתן לזיוף.
    """
    if not phone:
        return _end(y.t('לא ניתן לזהות את המספר שממנו התקשרת'),
                    y.t('יש להתקשר שוב בלי חסימת מזהה'))

    start = _value(values, 'reg_start')
    if not start:
        return y.read(
            y.msgs(y.t('המספר שממנו התקשרת אינו רשום במערכת'),
                   y.t('להרשמה הקישי 1'),
                   y.t('לסיום הקישי 2')),
            'reg_start', max_digits=1, min_digits=1, digits_allowed=[1, 2],
        )
    if start != '1':
        return _end(y.t('להתראות'))

    pin = _value(values, 'reg_pin')
    if not pin:
        return y.read(
            y.t('נא לבחור קוד אישי בן ארבע עד שמונה ספרות ולסיים בסולמית'),
            'reg_pin', max_digits=8, min_digits=4,
        )

    confirm = _value(values, 'reg_pin2')
    if not confirm:
        return y.read(
            y.t('נא להקיש שוב את אותו קוד ולסיים בסולמית'),
            'reg_pin2', max_digits=8, min_digits=4,
        )

    if confirm != pin:
        return _end(y.t('הקודים שהוקשו אינם זהים'), y.t('נא להתקשר שוב'))

    user = User(phone=phone, is_approved=False)
    user.set_pin(pin)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        # שיחה מקבילה מאותו מספר הספיקה לרשום אותו
        db.session.rollback()
        return _end(y.t('המספר כבר רשום במערכת'))

    return _end(
        y.t('נרשמת בהצלחה'),
        y.t('החשבון ממתין לאישור המנהל'),
        y.t('לאחר האישור אפשר להתקשר שוב ולהזדהות בקוד שבחרת'),
    )


# ===== 1 — דיווח ראייה חדשה =====

def _flow_report(user, values):
    """
    תהליך הדיווח מסתיים תמיד בניתוק, כדי שהערכים שנקראו בו לא יישארו
    בשיחה ויגרמו לרישום נוסף אם המתקשרת תיכנס שוב לאותו תפריט.
    """
    when = _value(values, 'rep_when')
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
        raw_date = _value(values, 'rep_date')
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

    raw_time = _value(values, 'rep_time')
    if not raw_time:
        return y.read(
            y.t('נא להקיש את שעת הראייה שתי ספרות שעה ושתי ספרות דקות'),
            'rep_time', max_digits=4, min_digits=4, typing_playback='Time',
        )
    time_str = _parse_time(raw_time)
    if not time_str:
        return _end(y.t('השעה שהוקשה אינה תקינה'))

    onah = determine_onah(time_str, g_date, user)

    confirm = _value(values, 'rep_confirm')
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
    # אותו חישוב שהלוח הראשי מציג — כולל קבועות וביטול ווסתות בהריון
    vesetot, expected, _ = get_user_expected(user)
    if not vesetot:
        return _main_menu(y.t('אין ראיות רשומות במערכת'))

    today = date.today()
    upcoming = [e for e in expected if e['gregorian_date'] >= today][:UPCOMING_LIMIT]
    if not upcoming:
        return _main_menu(y.t('אין ימי פרישה קרובים'),
                          y.t('יתכן שהראייה האחרונה ישנה ויש לדווח על ראייה חדשה'))

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


# ===== 5 — הוספת תזכורת אישית =====

def _flow_add_reminder(user, values):
    """
    הוספת תזכורת. הכותרת נבחרת מרשימה קבועה ולא מוקלדת, כי אין דרך אמינה
    להזין טקסט עברי מלוח המקשים.
    """
    title_key = _value(values, 'rem_title')
    if not title_key:
        parts = [y.t('נא לבחור את סוג התזכורת')]
        parts += [y.t(f'ל{name} הקישי {key}')
                  for key, name in REMINDER_TITLES.items()]
        return y.read(y.msgs(*parts), 'rem_title', max_digits=1, min_digits=1,
                      digits_allowed=list(REMINDER_TITLES))
    title = REMINDER_TITLES.get(title_key)
    if not title:
        return _end(y.t('בחירה לא מוכרת'))

    when = _value(values, 'rem_when')
    if not when:
        return y.read(
            y.msgs(y.t('לתזכורת להיום הקישי 1'),
                   y.t('למחר הקישי 2'),
                   y.t('לתאריך אחר הקישי 3')),
            'rem_when', max_digits=1, min_digits=1, digits_allowed=[1, 2, 3],
        )

    if when == '1':
        g_date = date.today()
    elif when == '2':
        g_date = date.today() + timedelta(days=1)
    else:
        raw_date = _value(values, 'rem_date')
        if not raw_date:
            return y.read(
                y.t('נא להקיש את התאריך שתי ספרות יום שתי ספרות חודש וארבע ספרות שנה'),
                'rem_date', max_digits=8, min_digits=8, typing_playback='Date',
            )
        g_date = _parse_date(raw_date)
        if not g_date:
            return _end(y.t('התאריך שהוקש אינו תקין'))
        if g_date < date.today():
            return _end(y.t('לא ניתן לקבוע תזכורת לתאריך שעבר'))

    raw_time = _value(values, 'rem_time')
    if not raw_time:
        return y.read(
            y.t('נא להקיש את שעת התזכורת שתי ספרות שעה ושתי ספרות דקות'),
            'rem_time', max_digits=4, min_digits=4, typing_playback='Time',
        )
    time_str = _parse_time(raw_time)
    if not time_str:
        return _end(y.t('השעה שהוקשה אינה תקינה'))

    reminder = Reminder(
        user_id=user.id,
        type='personal',
        title=title,
        message='נוצר בשיחה טלפונית',
        gregorian_date=g_date,
        time_of_day=time_str,
        recurrence='once',
        active=True,
    )
    db.session.add(reminder)
    db.session.commit()

    return _end(
        y.t('התזכורת נקבעה'),
        y.t(title),
        y.g_date(g_date),
        y.t('בשעה'),
        _say_time(time_str),
    )


# ===== 6 — הגדרות =====

def _flow_settings(user, phone, values):
    choice = _value(values, 'set_menu')
    if not choice:
        parts = [y.t('לשמיעת ההגדרות הנוכחיות הקישי 1'),
                 y.t('לשינוי הקוד האישי הקישי 2')]
        parts += [y.t(f'למנהג {name} הקישי {key}')
                  for key, (_, name) in MINHAG_FIELDS.items()]
        parts += [y.t('לימי הספירה הקישי 7'),
                  y.t('לשעות לפני תזכורת הקישי 8')]
        return y.read(y.msgs(*parts), 'set_menu', max_digits=1, min_digits=1,
                      digits_allowed=[1, 2, 3, 4, 5, 6, 7, 8])

    if choice == '1':
        return _say_settings(user)
    if choice == '2':
        return _flow_change_pin(user, phone, values)
    if choice in MINHAG_FIELDS:
        return _flow_toggle_minhag(user, choice, values)
    if choice == '7':
        return _flow_sfira(user, values)
    if choice == '8':
        return _flow_reminder_hours(user, values)
    return _end(y.t('בחירה לא מוכרת'))


def _say_settings(user):
    parts = [y.t('ההגדרות הנוכחיות')]
    for field, name in MINHAG_FIELDS.values():
        parts.append(y.t(f'מנהג {name} {_on_off(getattr(user, field))}'))
    parts += [
        y.t('ימי הספירה'),
        y.n(user.yemei_sfira_days),
        y.t('תזכורת'),
        y.n(user.reminder_hours_before or 12),
        y.t('שעות מראש'),
    ]
    return _end(*parts)


def _flow_change_pin(user, phone, values):
    """
    שינוי הקוד של המספר שממנו התקשרו. לבעל נקבע קוד נפרד משלו, גם אם עד
    כה השתמש בקוד המשותף.
    """
    new_pin = _value(values, 'set_pin')
    if not new_pin:
        return y.read(
            y.t('נא להקיש קוד חדש בן ארבע עד שמונה ספרות ולסיים בסולמית'),
            'set_pin', max_digits=8, min_digits=4,
        )

    confirm = _value(values, 'set_pin2')
    if not confirm:
        return y.read(
            y.t('נא להקיש שוב את אותו קוד ולסיים בסולמית'),
            'set_pin2', max_digits=8, min_digits=4,
        )

    if confirm != new_pin:
        return _end(y.t('הקודים שהוקשו אינם זהים'), y.t('הקוד לא שונה'))

    if user.is_husband_phone(phone):
        user.set_pin_husband(new_pin)
        message = y.t('הקוד של המספר הזה עודכן')
    else:
        user.set_pin(new_pin)
        message = y.t('הקוד עודכן')
    db.session.commit()

    return _end(message)


def _flow_toggle_minhag(user, choice, values):
    field, name = MINHAG_FIELDS[choice]
    answer = _value(values, 'set_value')
    if not answer:
        return y.read(
            y.msgs(y.t(f'מנהג {name} כעת {_on_off(getattr(user, field))}'),
                   y.t('להפעלה הקישי 1'),
                   y.t('לביטול הקישי 2')),
            'set_value', max_digits=1, min_digits=1, digits_allowed=[1, 2],
        )

    setattr(user, field, answer == '1')
    db.session.commit()
    return _end(y.t(f'מנהג {name} {_on_off(answer == "1")}'))


def _flow_sfira(user, values):
    answer = _value(values, 'set_sfira')
    if not answer:
        return y.read(
            y.msgs(y.t('ימי הספירה כעת'),
                   y.n(user.yemei_sfira_days),
                   y.t('לחמישה ימים הקישי 1'),
                   y.t('לארבעה ימים הקישי 2')),
            'set_sfira', max_digits=1, min_digits=1, digits_allowed=[1, 2],
        )

    user.minhag_yemei_sfira = 'ashkenaz' if answer == '1' else 'beit_yosef'
    db.session.commit()
    return _end(y.t('ימי הספירה עודכנו ל'), y.n(user.yemei_sfira_days),
                y.t('ימים'))


def _flow_reminder_hours(user, values):
    answer = _value(values, 'set_hours')
    if not answer:
        parts = [y.t('התזכורת נשלחת כעת'),
                 y.n(user.reminder_hours_before or 12),
                 y.t('שעות מראש')]
        parts += [y.msgs(y.t('ל'), y.n(hours), y.t(f'שעות הקישי {key}'))
                  for key, hours in REMINDER_HOURS.items()]
        return y.read(y.msgs(*parts), 'set_hours', max_digits=1, min_digits=1,
                      digits_allowed=list(REMINDER_HOURS))

    hours = REMINDER_HOURS.get(answer)
    if not hours:
        return _end(y.t('בחירה לא מוכרת'))

    user.reminder_hours_before = hours
    db.session.commit()
    return _end(y.t('התזכורת תישלח'), y.n(hours), y.t('שעות מראש'))


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
