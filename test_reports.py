"""
בדיקות לדוח המנויים ולהפרדה בין חשבון ממתין לחשבון נדחה.
הרצה: python test_reports.py
"""
import os
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'test'
os.environ['CRON_SECRET'] = 'cron-s3cret'
os.environ['YEMOT_API_SECRET'] = 's3cret'
os.environ.update({'ALERT_EMAIL': 'admin@example.com', 'SMTP_HOST': 'smtp.example.com',
                   'SMTP_USER': 'admin@example.com', 'SMTP_PASSWORD': 'pw'})

from main import create_app
from extensions import db
from models import User, Veeset
from logic import alerts as alerts_module
from logic.reports import build_users_report

app = create_app()
client = app.test_client()

ADMIN_PHONE = '0501110000'
OK_PHONE = '0502220000'
PENDING_PHONE = '0503330000'
REJECTED_PHONE = '0504440000'


def ok(label):
    print(f'  ok  {label}')


sent = []


def fake_deliver(config, subject, body):
    sent.append({'to': config['to'], 'subject': subject, 'body': body})


with app.app_context():
    admin = User(phone=ADMIN_PHONE, name='מנהל', is_approved=True, is_admin=True)
    admin.set_pin('1111')
    approved = User(phone=OK_PHONE, name='שרה', phone_husband='0502220001',
                    is_approved=True)
    approved.set_pin('2222')
    pending = User(phone=PENDING_PHONE, name='לאה', is_approved=False)
    pending.set_pin('3333')
    rejected = User(phone=REJECTED_PHONE, name='רבקה', is_approved=False,
                    rejected_at=datetime(2026, 10, 1, 9, 30))
    rejected.set_pin('4444')
    db.session.add_all([admin, approved, pending, rejected])
    db.session.commit()

    db.session.add_all([
        Veeset(user_id=approved.id, gregorian_date=date(2026, 9, 1),
               time_of_sighting='10:00', onah='yom', duration_days=1),
        Veeset(user_id=approved.id, gregorian_date=date(2026, 10, 5),
               time_of_sighting='21:00', onah='layla', duration_days=1,
               onah_needs_review=True),
    ])
    db.session.commit()


print('=== שלושת המצבים ===')

with app.app_context():
    assert User.query.filter_by(phone=OK_PHONE).one().status == 'approved'
    assert User.query.filter_by(phone=PENDING_PHONE).one().status == 'pending'
    assert User.query.filter_by(phone=REJECTED_PHONE).one().status == 'rejected'
    ok('מחובר, ממתין ונדחה נבדלים זה מזה')

    # לפני השדה הזה שני המצובים האחרונים נראו זהים — is_approved=False בשניהם
    assert User.query.filter_by(phone=PENDING_PHONE).one().is_approved is False
    assert User.query.filter_by(phone=REJECTED_PHONE).one().is_approved is False
    ok('שניהם עדיין חסומים לכניסה, כמו קודם')


print('\n=== גוף הדוח ===')

with app.app_context():
    subject, body = build_users_report()

print(body)
assert 'ממתינים לאישור (1)' in body, body
assert 'מחוברים (2)' in body
assert 'נדחו (1)' in body
ok('שלושת החלקים עם המספרים הנכונים')

assert 'שרה' in body and '0502220001' in body
assert 'ראיות: 2' in body
assert 'ראייה אחת דורשת אימות עונה' in body
ok('פרטי החשבון, מספר הראיות, והאזהרה על אימות עונה')

assert 'נדחה: 01/10/2026 09:30' in body
ok('תאריך הדחייה מופיע')

assert '⭐ מנהל' in body
assert '4 חשבונות' in subject and '1 ממתינים' in subject
ok(f'הנושא: {subject}')


print('\n=== נתיב ה-cron ===')

assert client.post('/cron/users-report').status_code == 401
assert client.post('/cron/users-report',
                   headers={'Authorization': 'Bearer wrong'}).status_code == 401
ok('בלי הסוד הנכון הנתיב מחזיר 401')

original_deliver = alerts_module._deliver
alerts_module._deliver = fake_deliver
try:
    response = client.post('/cron/users-report',
                           headers={'Authorization': 'Bearer cron-s3cret'})
finally:
    alerts_module._deliver = original_deliver

assert response.status_code == 200, response.status_code
payload = response.get_json()
assert payload['success'] is True, payload
assert len(sent) == 1 and sent[0]['to'] == 'admin@example.com'
assert 'ממתינים לאישור (1)' in sent[0]['body']
ok(f'עם הסוד נשלח מייל אחד — {payload["detail"]}')


def exploding(config, subject, body):
    raise OSError('שרת לא זמין')


alerts_module._deliver = exploding
try:
    response = client.post('/cron/users-report',
                           headers={'Authorization': 'Bearer cron-s3cret'})
finally:
    alerts_module._deliver = original_deliver
assert response.status_code == 502, response.status_code
assert 'שרת לא זמין' in response.get_json()['detail']
ok('כשל שליחה מחזיר 502 עם הסיבה, כדי ש-Scheduler ינסה שוב')


print('\n=== כפתור במסך הניהול ===')

login = client.post('/login', data={'phone': ADMIN_PHONE, 'pin': '1111'})
assert login.status_code in (302, 200)

alerts_module._deliver = fake_deliver
try:
    response = client.get('/admin/send-report', follow_redirects=True)
finally:
    alerts_module._deliver = original_deliver
assert response.status_code == 200
assert 'הדוח נשלח' in response.get_data(as_text=True)
assert len(sent) == 2
ok('המנהל שולח דוח בלחיצה ורואה אישור')

page = client.get('/admin').get_data(as_text=True)
assert 'נדחה ✕' in page and 'ממתין ⏳' in page and 'מחובר ✓' in page
assert '2 מחוברים' in page and '1 ממתינים' in page and '1 נדחו' in page
ok('מסך הניהול מציג את שלושת המצבים ואת הסיכום')


print('\n=== מה שומע חשבון נדחה בטלפון ===')


def yemot(phone, **params):
    params.update({'secret': 's3cret', 'ApiPhone': phone, 'ApiCallId': 'c'})
    return client.get('/yemot', query_string=params).get_data(as_text=True)


pending_answer = yemot(PENDING_PHONE)
rejected_answer = yemot(REJECTED_PHONE)
print(pending_answer)
print(rejected_answer)
assert 'ממתין לאישור המנהל' in pending_answer
assert 'נחסם' in rejected_answer and 'ממתין' not in rejected_answer
ok('ממתין שומע שממתינים לאישור, ונדחה שומע שנחסם')


print('\n=== אישור מנקה דחייה ===')

with app.app_context():
    target = User.query.filter_by(phone=REJECTED_PHONE).one()
    target_id = target.id

client.get(f'/admin/approve/{target_id}', follow_redirects=True)
with app.app_context():
    target = db.session.get(User, target_id)
    assert target.is_approved and target.rejected_at is None
    assert target.status == 'approved'
ok('חשבון שאושר מחדש אינו נשאר מסומן כנדחה')


print('\n\nALL REPORT TESTS PASSED')
