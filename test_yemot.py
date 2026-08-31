"""
בדיקת קצה לקצה של שלוחת ימות — מריצה שיחה מלאה מול test client של Flask.
הרצה: python test_yemot.py
"""
import os
import sys
import tempfile

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

response = client.get('/yemot', query_string={'secret': SECRET, 'ApiPhone': '0500000000'})
check('unknown caller', response.get_data(as_text=True),
      ['go_to_folder=hangup', 'אינו רשום'])

response = client.get('/yemot', query_string={'secret': 'wrong', 'ApiPhone': PHONE})
check('bad secret', response.get_data(as_text=True), ['שגיאת הגדרה'])

response = client.get('/yemot', query_string={'secret': SECRET, 'ApiPhone': PHONE,
                                              'hangup': 'yes'})
assert response.get_data(as_text=True) == '', 'hangup should return empty'
print('\n--- hangup --- (empty ok)')

check('ask pin', call(client), ['read=', 'pin,no,8,4,7,No,no,no,,,3,,,'])
check('bad pin', call(client, pin='9999'), ['שגוי', 'go_to_folder=hangup'])
check('main menu', call(client, pin='1234'),
      ['שלום שרה', 'menu,yes,1,1,7,No,no,no,,1.2.3.4.9,,,,'])
check('last, empty', call(client, pin='1234', menu='3'),
      ['אין ראיות רשומות', 'read='])

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

check('last', call(client, pin='1234', menu='3'), ['האחרונה', 'dateH-', 'menu,yes'])
check('upcoming', call(client, pin='1234', menu='2'), ['ימי הפרישה הקרובים', 'menu,yes'])
check('reminders', call(client, pin='1234', menu='4'), ['אין תזכורות', 'menu,yes'])
check('exit', call(client, pin='1234', menu='9'), ['להתראות', 'go_to_folder=hangup'])

print('\n\nALL YEMOT TESTS PASSED')
