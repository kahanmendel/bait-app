"""
בדיקות לקודים הנפרדים לשני המספרים, למסך ההגדרות ולהרשמה הטלפונית.
הרצה: python test_accounts.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db').replace('\\', '/')
os.environ['SECRET_KEY'] = 'test'
os.environ['YEMOT_API_SECRET'] = 's3cret'

from sqlalchemy import inspect, text

from main import create_app
from extensions import db
from models import User
from logic.schema import ensure_schema

WIFE = '0501111111'
HUSBAND = '0502222222'
NEWCOMER = '0503333333'
SECRET = 's3cret'

app = create_app()


def yemot(client, **params):
    params.setdefault('secret', SECRET)
    params.setdefault('ApiCallId', 'call-1')
    params.setdefault('ApiExtension', '2')
    return client.get('/yemot', query_string=params).get_data(as_text=True)


def ok(label):
    print(f'  ok  {label}')


with app.app_context():
    user = User(phone=WIFE, phone_husband=HUSBAND, name='שרה', is_approved=True,
                use_auto_times=False, custom_hanetz='06:00', custom_shkia='19:00')
    user.set_pin('1111')
    db.session.add(user)
    db.session.commit()

print('\n=== קוד משותף כל עוד לא נקבע לבעל קוד משלו ===')
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    assert user.check_pin_for(WIFE, '1111')
    assert user.check_pin_for(HUSBAND, '1111'), 'husband must fall back to the shared pin'
    assert not user.check_pin_for(HUSBAND, '2222')
    ok('שני המספרים נכנסים עם הקוד המשותף')

print('\n=== קוד נפרד לבעל ===')
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    user.set_pin_husband('2222')
    db.session.commit()

    assert user.check_pin_for(HUSBAND, '2222'), 'husband pin must work'
    assert not user.check_pin_for(HUSBAND, '1111'), 'shared pin must stop working for him'
    assert user.check_pin_for(WIFE, '1111'), 'wife keeps her own pin'
    assert not user.check_pin_for(WIFE, '2222'), 'wife must not accept his pin'
    ok('כל מספר מאמת מול הקוד שלו בלבד')

print('\n=== כניסה לאתר משני המספרים ===')
for phone, pin in ((WIFE, '1111'), (HUSBAND, '2222')):
    client = app.test_client()
    response = client.post('/login', data={'phone': phone, 'pin': pin})
    assert response.status_code == 302, f'{phone} could not log in: {response.status_code}'
    ok(f'{phone} נכנס עם הקוד שלו')

client = app.test_client()
response = client.post('/login', data={'phone': HUSBAND, 'pin': '1111'})
assert response.status_code == 200, 'shared pin must be rejected for the husband'
ok('הקוד של האישה נדחה למספר הבעל')

print('\n=== מסך ההגדרות לא מוחק נתונים ===')
client = app.test_client()
client.post('/login', data={'phone': WIFE, 'pin': '1111'})
response = client.post('/settings', data={
    'name': 'שרה',
    'phone_husband': HUSBAND,
    'location_name': 'ירושלים',
    'minhag_yemei_sfira': 'ashkenaz',
    'reminder_hours_before': '12',
})
assert response.status_code == 302, response.status_code
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    assert user.name == 'שרה', f'name was wiped: {user.name!r}'
    assert user.phone_husband == HUSBAND, f'husband phone was wiped: {user.phone_husband!r}'
    assert user.check_pin_for(HUSBAND, '2222'), 'saving settings must not clear the pins'
    ok('שמירה בלי שינוי קודים משאירה שם, מספר בעל וקודים')

print('\n=== החלפת קודים דרך ההגדרות ===')
client.post('/settings', data={
    'name': 'שרה',
    'phone_husband': HUSBAND,
    'new_pin': '3333',
    'new_pin_husband': '4444',
    'location_name': 'ירושלים',
    'minhag_yemei_sfira': 'ashkenaz',
    'reminder_hours_before': '12',
})
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    assert user.check_pin_for(WIFE, '3333'), 'wife pin was not changed'
    assert user.check_pin_for(HUSBAND, '4444'), 'husband pin was not changed'
    ok('שני הקודים הוחלפו')

print('\n=== ביטול הקוד הנפרד ===')
client = app.test_client()
client.post('/login', data={'phone': WIFE, 'pin': '3333'})
client.post('/settings', data={
    'name': 'שרה',
    'phone_husband': HUSBAND,
    'clear_pin_husband': 'on',
    'location_name': 'ירושלים',
    'minhag_yemei_sfira': 'ashkenaz',
    'reminder_hours_before': '12',
})
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    assert user.pin_hash_husband is None
    assert user.check_pin_for(HUSBAND, '3333'), 'husband should fall back to the shared pin'
    ok('הבעל חזר לקוד המשותף')

print('\n=== קוד נפרד גם בשלוחה הטלפונית ===')
with app.app_context():
    user = User.query.filter_by(phone=WIFE).first()
    user.set_pin_husband('4444')
    db.session.commit()

client = app.test_client()
answer = yemot(client, ApiPhone=HUSBAND, pin='4444')
assert 'menu,' in answer, f'husband could not authenticate by phone: {answer}'
ok('הבעל מזדהה בטלפון עם הקוד שלו')

answer = yemot(client, ApiPhone=HUSBAND, pin='3333')
assert 'שגוי' in answer, f'wife pin was accepted for the husband: {answer}'
ok('הקוד של האישה נדחה בטלפון למספר הבעל')

print('\n=== הרשמה טלפונית ===')
client = app.test_client()
answer = yemot(client, ApiPhone=NEWCOMER)
assert 'reg_start' in answer and 'להרשמה הקישי 1' in answer, answer
ok('מספר לא מוכר מקבל הצעת הרשמה')

answer = yemot(client, ApiPhone=NEWCOMER, reg_start='2')
assert 'go_to_folder=hangup' in answer and 'reg_pin' not in answer
ok('סירוב מנתק')

answer = yemot(client, ApiPhone=NEWCOMER, reg_start='1')
assert 'reg_pin,' in answer, answer
answer = yemot(client, ApiPhone=NEWCOMER, reg_start='1', reg_pin='9876')
assert 'reg_pin2,' in answer, answer
answer = yemot(client, ApiPhone=NEWCOMER, reg_start='1', reg_pin='9876', reg_pin2='9999')
assert 'אינם זהים' in answer, answer
with app.app_context():
    assert User.query.filter_by(phone=NEWCOMER).first() is None, 'mismatch must not register'
ok('קודים שאינם תואמים לא יוצרים חשבון')

answer = yemot(client, ApiPhone=NEWCOMER, reg_start='1', reg_pin='9876', reg_pin2='9876')
assert 'נרשמת בהצלחה' in answer and 'ממתין לאישור המנהל' in answer, answer
assert 'go_to_folder=hangup' in answer
ok('הרשמה מוצלחת ונאמר שממתינים לאישור')

with app.app_context():
    newcomer = User.query.filter_by(phone=NEWCOMER).first()
    assert newcomer is not None, 'user was not created'
    assert newcomer.is_approved is False, 'phone registration must not self approve'
    assert newcomer.is_admin is False, 'phone registration must never grant admin'
    assert newcomer.check_pin_for(NEWCOMER, '9876')
    ok('החשבון נוצר לא מאושר עם הקוד שנבחר')

print('\n=== מתקשר שנרשם ועדיין לא אושר ===')
answer = yemot(app.test_client(), ApiPhone=NEWCOMER)
assert 'ממתין לאישור המנהל' in answer, answer
assert 'pin,' not in answer, 'must not ask for a pin before approval'
ok('שומע ממתין לאישור המנהל ולא מתבקש קוד')

print('\n=== המנהל מאשר, ואז אפשר להיכנס ===')
with app.app_context():
    newcomer = User.query.filter_by(phone=NEWCOMER).first()
    newcomer.is_approved = True
    db.session.commit()
answer = yemot(app.test_client(), ApiPhone=NEWCOMER, pin='9876')
assert 'menu,' in answer, answer
ok('אחרי אישור מגיע התפריט')

print('\n=== חסימת מזהה ===')
answer = yemot(app.test_client(), ApiPhone='')
assert 'לא ניתן לזהות' in answer, answer
ok('מספר חסום מקבל הסבר ולא מסך הרשמה')

print('\n=== השלמת עמודה בבסיס נתונים קיים ===')
with app.app_context():
    db.session.execute(text('ALTER TABLE users DROP COLUMN pin_hash_husband'))
    db.session.commit()
    assert 'pin_hash_husband' not in {
        c['name'] for c in inspect(db.engine).get_columns('users')}

    added = ensure_schema(db)
    assert added == ['users.pin_hash_husband'], added
    assert 'pin_hash_husband' in {
        c['name'] for c in inspect(db.engine).get_columns('users')}
    ok('העמודה החסרה נוספה')

    assert ensure_schema(db) == [], 'ensure_schema must be a no-op the second time'
    ok('הרצה חוזרת אינה עושה דבר')

print('\n\nALL ACCOUNT TESTS PASSED')
