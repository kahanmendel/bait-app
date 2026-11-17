"""
בדיקות לזמני הנץ והשקיעה, לקביעת העונה ולהתראות התקלה.
הרצה: python test_zmanim.py
"""
import os
import sys
import tempfile
from datetime import date, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'test'
os.environ['YEMOT_API_SECRET'] = 's3cret'
for name in ('ALERT_EMAIL', 'SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM'):
    os.environ.pop(name, None)

from main import create_app
from extensions import db
from models import User, Veeset, AlertLog
from logic import alerts as alerts_module
from logic import onah as onah_module
from logic.zmanim import compute_sun_times, custom_sun_times, FALLBACK_SHKIA

app = create_app()
PHONE = '0509998888'
SECRET = 's3cret'

WINTER = date(2026, 11, 17)
SUMMER = date(2026, 7, 1)
JERUSALEM = (31.7683, 35.2137)


def ok(label):
    print(f'  ok  {label}')


class Recorder:
    """מחליף את send_alert ואוסף את ההתראות שנשלחו."""
    def __init__(self):
        self.sent = []

    def __call__(self, subject, body, *, key, min_interval_hours=1):
        self.sent.append({'subject': subject, 'body': body, 'key': key})
        return True

    def keys(self):
        return [item['key'] for item in self.sent]


class FakeUser:
    def __init__(self, **kw):
        self.id = 99
        self.use_auto_times = True
        self.location_lat, self.location_lon = JERUSALEM
        self.custom_hanetz = None
        self.custom_shkia = None
        self.__dict__.update(kw)


print('=== חישוב מקומי של הזמנים ===')

winter = compute_sun_times(*JERUSALEM, WINTER)
summer = compute_sun_times(*JERUSALEM, SUMMER)
assert winter.reliable and winter.source == 'computed'
assert winter.shkia == time(16, 40), winter.shkia
assert summer.shkia == time(19, 48), summer.shkia
ok(f'שקיעה בירושלים: חורף {winter.shkia:%H:%M}, קיץ {summer.shkia:%H:%M}')

# ההמרה הקודמת הייתה +3 קבוע, ולכן בחורף הזמנים זזו בשעה
assert winter.shkia.hour != summer.shkia.hour
ok('שעון חורף וקיץ נבדלים — אין יותר היסט קבוע')


print('\n=== הרגרסיה שבגללה נבנה הכל ===')

# עם הנפילה השקטה ל-19:00 ראייה ב-17:30 בנובמבר נרשמה כעונת יום
assert FALLBACK_SHKIA == time(19, 0)
onah, times = onah_module.determine_onah_checked('17:30', WINTER, FakeUser())
assert onah == 'layla', onah
assert times.reliable
ok('ראייה ב-17:30 בנובמבר נקבעת עונת לילה, ולא יום')

for clock, expected in (('10:00', 'yom'), ('16:30', 'yom'),
                        ('16:45', 'layla'), ('05:00', 'layla')):
    got, _ = onah_module.determine_onah_checked(clock, WINTER, FakeUser())
    assert got == expected, (clock, got, expected)
ok('גבול השקיעה נקבע לפי הזמן האמיתי')


print('\n=== זמנים ידניים ===')

manual = FakeUser(use_auto_times=False, custom_hanetz='06:30', custom_shkia='18:15')
times = onah_module.user_sun_times(manual, WINTER)
assert times.source == 'custom' and times.reliable
assert (times.hanetz, times.shkia) == (time(6, 30), time(18, 15))
ok('זמנים ידניים תקינים מכובדים ונחשבים אמינים')

for broken in (FakeUser(use_auto_times=False),
               FakeUser(use_auto_times=False, custom_hanetz='06:00', custom_shkia=''),
               FakeUser(use_auto_times=False, custom_hanetz='בוקר', custom_shkia='18:00'),
               FakeUser(use_auto_times=False, custom_hanetz='06:00', custom_shkia='18-00')):
    recorder = Recorder()
    original = onah_module.send_alert
    onah_module.send_alert = recorder
    try:
        times = onah_module.user_sun_times(broken, WINTER)
    finally:
        onah_module.send_alert = original
    assert not times.reliable, broken.__dict__
    assert len(recorder.sent) == 1, recorder.sent
    assert recorder.keys()[0].startswith('custom_times_invalid'), recorder.keys()
    # הערכים עצמם עדיין המדויקים למיקום, ולא 19:00
    assert times.shkia == time(16, 40), times
ok('זמנים ידניים חסרים או פגומים — התראה, סימון כבלתי אמין, וזמנים מחושבים')


print('\n=== כשל בחישוב עצמו ===')

recorder = Recorder()
original_alert = onah_module.send_alert
original_compute = onah_module.compute_sun_times


def exploding(*args, **kwargs):
    raise RuntimeError('זמנים לא זמינים')


onah_module.send_alert = recorder
onah_module.compute_sun_times = exploding
try:
    times = onah_module.get_sun_times(*JERUSALEM, WINTER)
finally:
    onah_module.send_alert = original_alert
    onah_module.compute_sun_times = original_compute

assert times.source == 'fallback' and not times.reliable
assert times.shkia == FALLBACK_SHKIA
assert recorder.keys() == ['zmanim_compute_failed'], recorder.keys()
assert 'זמנים לא זמינים' in recorder.sent[0]['body']
ok('כשל חישוב — ברירת מחדל מסומנת כבלתי אמינה, והתראה נשלחת')


print('\n=== התראות: מיגון מפני הצפה והגדרות חסרות ===')

with app.app_context():
    db.create_all()

    # בלי הגדרות SMTP אין שליחה, והתקלה נכתבת ללוג
    assert alerts_module.send_alert('נושא', 'גוף', key='no_config') is False
    assert AlertLog.query.filter_by(key='no_config').count() == 0
    ok('בלי הגדרות SMTP אין שליחה ואין רישום')

    os.environ.update({'ALERT_EMAIL': 'me@example.com', 'SMTP_HOST': 'smtp.example.com',
                       'SMTP_USER': 'me@example.com', 'SMTP_PASSWORD': 'pw'})
    delivered = []
    original_deliver = alerts_module._deliver
    alerts_module._deliver = lambda config, subject, body: delivered.append(subject)
    try:
        assert alerts_module.send_alert('ראשונה', 'גוף', key='dup') is True
        assert alerts_module.send_alert('שנייה', 'גוף', key='dup') is False
        assert alerts_module.send_alert('אחרת', 'גוף', key='other') is True
    finally:
        alerts_module._deliver = original_deliver

    assert delivered == ['ראשונה', 'אחרת'], delivered
    assert AlertLog.query.filter_by(key='dup').count() == 1
    ok('התראה חוזרת באותו מזהה מאוחדת, מזהה אחר נשלח')

    # כשל שליחה נרשם כלא נמסר, כדי שיהיה עקבות גם בלי מייל
    alerts_module._deliver = exploding
    try:
        assert alerts_module.send_alert('נפל', 'גוף', key='broken') is False
    finally:
        alerts_module._deliver = original_deliver
    row = AlertLog.query.filter_by(key='broken').first()
    assert row is not None and not row.delivered
    ok('כשל בשליחת ההתראה נרשם ואינו מפיל את הפעולה')


print('\n=== מקצה לקצה: דיווח טלפוני בלי זמן מדויק ===')

with app.app_context():
    user = User(phone=PHONE, name='רחל', is_approved=True,
                use_auto_times=False, custom_hanetz='', custom_shkia='')
    user.set_pin('1234')
    db.session.add(user)
    db.session.commit()

client = app.test_client()
base = {'secret': SECRET, 'ApiPhone': PHONE, 'ApiCallId': 'c-1', 'pin': '1234'}

recorder = Recorder()
onah_module.send_alert = recorder
try:
    answer = client.get('/yemot', query_string={
        **base, 'menu': '1', 'rep_when': '1', 'rep_time': '1730',
        'rep_confirm': '1'}).get_data(as_text=True)
finally:
    onah_module.send_alert = original_alert

print(answer)
assert 'נרשמה בהצלחה' in answer
assert 'יש לאמת' in answer, answer
assert recorder.keys(), 'לא נשלחה התראה'
ok('המתקשרת שומעת שהעונה דורשת אימות, והתראה נשלחת')

with app.app_context():
    saved = Veeset.query.filter_by(user_id=User.query.filter_by(phone=PHONE).first().id).all()
    assert len(saved) == 1, saved
    assert saved[0].onah_needs_review is True, saved[0].onah_needs_review
    # 17:30 מול שקיעה אמיתית 16:40 — לילה, ולא יום כמו בברירת המחדל
    assert saved[0].onah == 'layla', saved[0].onah
ok('הראייה נשמרה מסומנת לאימות, והעונה לפי הזמן האמיתי')


print('\n=== הלוח הראשי מציג את האזהרה ===')

login = client.post('/login', data={'phone': PHONE, 'pin': '1234'})
assert login.status_code in (302, 200), login.status_code
page = client.get('/').get_data(as_text=True)
assert 'דורשות אימות עונה' in page, 'הבנר אינו מוצג'
assert 'לאימות' in page, 'התג בשורת הראייה אינו מוצג'
ok('בנר האזהרה והתג מוצגים בלוח הראשי')


print('\n\nALL ZMANIM TESTS PASSED')
