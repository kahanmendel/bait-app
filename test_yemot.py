"""
בדיקת קצה לקצה של שלוחת ימות — מריצה שיחה מלאה מול test client של Flask.
הרצה: python test_yemot.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'test'
os.environ['YEMOT_API_SECRET'] = 's3cret'

from main import create_app
from extensions import db
from models import User, Veeset

PHONE = '0501234567'
SECRET = 's3cret'
# תווים שאסור שיופיעו בתוך טקסט TTS שנשלח לימות
INVALID_TTS_CHARS = set('."\'&|-')

app = create_app()


def call(client, **params):
    params.setdefault('secret', SECRET)
    params.setdefault('ApiPhone', PHONE)
    params.setdefault('ApiCallId', 'call-1')
    params.setdefault('ApiExtension', '2')
    response = client.get('/yemot', query_string=params)
    assert response.status_code == 200, response.status_code
    assert response.mimetype == 'text/plain', response.mimetype
    return response.get_data(as_text=True)


def check(label, text, must_contain=()):
    print(f'\n--- {label} ---\n{text}')
    for needle in must_contain:
        assert needle in text, f'{label}: missing {needle!r}'
    for command in text.split('&'):
        body = command.split('=', 1)[1] if '=' in command else ''
        for item in body.split('='):
            for part in item.split('.'):
                if part.startswith('t-'):
                    bad = set(part[2:]) & INVALID_TTS_CHARS
                    assert not bad, f'{label}: invalid TTS chars {bad} in {part!r}'


with app.app_context():
    user = User(phone=PHONE, name='שרה', is_approved=True, use_auto_times=False,
                custom_hanetz='06:00', custom_shkia='19:00')
    user.set_pin('1234')
    db.session.add(user)
    db.session.commit()

client = app.test_client()

# מספר לא מוכר מגיע למסלול ההרשמה — הזרימה המלאה נבדקת ב-test_accounts.py
response = client.get('/yemot', query_string={'secret': SECRET, 'ApiPhone': '0500000000'})
check('unknown caller', response.get_data(as_text=True),
      ['אינו רשום', 'להרשמה הקישי 1', 'reg_start,'])

response = client.get('/yemot', query_string={'secret': 'wrong', 'ApiPhone': PHONE})
check('bad secret', response.get_data(as_text=True), ['שגיאת הגדרה'])

# ימות מצרפת את הפרמטרים שלה בסימן שאלה נוסף כשהסוד נמצא בתוך api_link
response = client.get('/yemot?secret=' + SECRET + '?ApiCallId=abc&ApiPhone=' + PHONE)
check('secret with appended query', response.get_data(as_text=True),
      ['read=', 'pin,no,8,4,7,No,no,no,,,3,,,'])

response = client.get('/yemot', query_string={'secret': SECRET, 'ApiPhone': PHONE,
                                              'hangup': 'yes'})
assert response.get_data(as_text=True) == '', 'hangup should return empty'
print('\n--- hangup --- (empty ok)')

check('ask pin', call(client), ['read=', 'pin,no,8,4,7,No,no,no,,,3,,,'])
check('bad pin', call(client, pin='9999'), ['שגוי', 'go_to_folder=hangup'])
check('main menu', call(client, pin='1234'),
      ['שלום שרה', 'menu,no,1,1,7,No,no,no,,1.2.3.4.5.6.9,,,,'])
check('last, empty', call(client, pin='1234', menu='3'),
      ['אין ראיות רשומות', 'go_to_folder=hangup'])

check('report step when', call(client, pin='1234', menu='1'),
      ['rep_when,no,1,1,7,No,no,no,,1.2.3,,,,'])
check('report step time', call(client, pin='1234', menu='1', rep_when='1'),
      ['rep_time,no,4,4,7,Time,'])
check('report confirm', call(client, pin='1234', menu='1', rep_when='1', rep_time='1430'),
      ['rep_confirm', 'dateH-', 'n-14', 'n-30'])
check('report cancel', call(client, pin='1234', menu='1', rep_when='1',
                            rep_time='1430', rep_confirm='2'),
      ['בוטל', 'go_to_folder=hangup'])
check('report bad time', call(client, pin='1234', menu='1', rep_when='1', rep_time='9999'),
      ['אינה תקינה'])
check('report future date', call(client, pin='1234', menu='1', rep_when='3',
                                 rep_date='01019999'),
      ['עתידי'])
# עם typing_playback_mode ימות מחזירה את הערך מפורמט ולא כספרות גולמיות
check('formatted time from yemot', call(client, pin='1234', menu='1',
                                        rep_when='1', rep_time='10-10'),
      ['rep_confirm', 'n-10'])
assert 'אינה תקינה' not in call(client, pin='1234', menu='1',
                                rep_when='1', rep_time='00-05')
check('formatted date from yemot', call(client, pin='1234', menu='1',
                                        rep_when='3', rep_date='01-01-2026',
                                        rep_time='08-30'),
      ['rep_confirm', 'dateH-'])
print('  ok  formatted Date and Time values are accepted')

check('report save', call(client, pin='1234', menu='1', rep_when='1',
                          rep_time='1430', rep_confirm='1'),
      ['נרשמה בהצלחה', 'עונת יום', 'go_to_folder=hangup'])

with app.app_context():
    saved = Veeset.query.all()
    assert len(saved) == 1, saved
    assert saved[0].time_of_sighting == '14:30'
    assert saved[0].onah == 'yom'
    assert saved[0].notes == 'דיווח טלפוני'
    print('\n--- DB --- saved:', saved[0].gregorian_date, saved[0].time_of_sighting,
          saved[0].onah)

check('last', call(client, pin='1234', menu='3'),
      ['האחרונה', 'dateH-', 'go_to_folder=hangup'])
check('upcoming', call(client, pin='1234', menu='2'),
      ['ימי הפרישה הקרובים', 'go_to_folder=hangup'])
check('reminders', call(client, pin='1234', menu='4'),
      ['אין תזכורות', 'go_to_folder=hangup'])
check('exit', call(client, pin='1234', menu='9'), ['להתראות', 'go_to_folder=hangup'])

print('\n=== 5 — הוספת תזכורת ===')
check('reminder title menu', call(client, pin='1234', menu='5'),
      ['rem_title,', 'הפסק טהרה'])
check('reminder date menu', call(client, pin='1234', menu='5', rem_title='2'),
      ['rem_when,'])
check('reminder time', call(client, pin='1234', menu='5', rem_title='2',
                            rem_when='2'),
      ['rem_time,'])
check('reminder past date', call(client, pin='1234', menu='5', rem_title='2',
                                 rem_when='3', rem_date='01012020'),
      ['תאריך שעבר'])
check('reminder saved', call(client, pin='1234', menu='5', rem_title='2',
                             rem_when='2', rem_time='20-15'),
      ['התזכורת נקבעה', 'טבילה', 'go_to_folder=hangup'])
with app.app_context():
    from models import Reminder
    saved_reminder = Reminder.query.filter_by(type='personal').one()
    assert saved_reminder.title == 'טבילה', saved_reminder.title
    assert saved_reminder.time_of_day == '20:15', saved_reminder.time_of_day
    assert saved_reminder.gregorian_date == date.today() + timedelta(days=1)
    print('  ok  reminder stored with the formatted time parsed correctly')

check('reminders now lists it', call(client, pin='1234', menu='4'),
      ['טבילה', 'go_to_folder=hangup'])

print('\n=== 6 — הגדרות ===')
check('settings menu', call(client, pin='1234', menu='6'),
      ['set_menu,', 'אור זרוע'])
check('settings readout', call(client, pin='1234', menu='6', set_menu='1'),
      ['ההגדרות הנוכחיות', 'go_to_folder=hangup'])
check('minhag prompt', call(client, pin='1234', menu='6', set_menu='3'),
      ['אור זרוע', 'מבוטל', 'set_value,'])
check('minhag enabled', call(client, pin='1234', menu='6', set_menu='3',
                             set_value='1'),
      ['אור זרוע', 'מופעל'])
with app.app_context():
    assert User.query.filter_by(phone=PHONE).one().minhag_or_zarua is True
    print('  ok  minhag persisted')

check('sfira changed', call(client, pin='1234', menu='6', set_menu='7',
                            set_sfira='2'),
      ['ימי הספירה עודכנו', 'n-4'])
check('reminder hours changed', call(client, pin='1234', menu='6', set_menu='8',
                                     set_hours='4'),
      ['n-48', 'שעות מראש'])
with app.app_context():
    changed = User.query.filter_by(phone=PHONE).one()
    assert changed.minhag_yemei_sfira == 'beit_yosef'
    assert changed.reminder_hours_before == 48
    print('  ok  sfira and reminder hours persisted')


# אף ענף לא רשאי להחזיר read על menu: ימות אינה דורסת ערך שכבר נאסף אלא
# מוסיפה עותק, ולכן חזרה לתפריט מכניסה את השיחה ללולאה אינסופית
for choice in ('2', '3', '4', '9'):
    answer = call(client, pin='1234', menu=choice)
    assert 'menu,' not in answer, f'menu={choice} loops back to the menu: {answer}'
    assert 'go_to_folder=hangup' in answer, f'menu={choice} does not end the call'
print('\n--- no branch loops back to the menu --- ok')

# ימות שולחת את הערך שוב ושוב באותה שיחה; הערך הקובע הוא האחרון
duplicated = client.get('/yemot?secret=' + SECRET + '&ApiPhone=' + PHONE
                        + '&pin=1234' + '&menu=2' * 80)
check('duplicated menu values', duplicated.get_data(as_text=True),
      ['go_to_folder=hangup'])
assert 'menu,' not in duplicated.get_data(as_text=True), 'duplicated values still loop'

# הלוח הראשי משתמש באותו חישוב — ודא שהוא עדיין נטען
login = client.post('/login', data={'phone': PHONE, 'pin': '1234'})
assert login.status_code in (302, 200), login.status_code
dashboard = client.get('/')
assert dashboard.status_code == 200, dashboard.status_code
assert 'ימי פרישה' in dashboard.get_data(as_text=True)
print('--- dashboard renders --- ok')

check('pin mismatch', call(client, pin='1234', menu='6', set_menu='2',
                           set_pin='5555', set_pin2='6666'),
      ['אינם זהים', 'הקוד לא שונה'])
check('pin changed', call(client, pin='1234', menu='6', set_menu='2',
                          set_pin='5555', set_pin2='5555'),
      ['הקוד עודכן'])
with app.app_context():
    assert User.query.filter_by(phone=PHONE).one().check_pin_for(PHONE, '5555')
    print('  ok  pin changed by phone')
PIN = '5555'

print('\n\nALL YEMOT TESTS PASSED')
