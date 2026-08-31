"""
API לימות המשיח.
שני מצבי אימות:
1. API Key (header X-API-Key) — לשימוש ישיר
2. Phone Session Token (header X-Session-Token) — אחרי אימות PIN בטלפון
"""
from flask import Blueprint, jsonify, request
from models import User, Veeset, VesetKavua, Reminder, PhoneSession
from logic.calculations import get_all_expected
from logic.onah import determine_onah
from logic.recalculate import recalculate_all
from extensions import db
from hdate import HebrewDate
from datetime import date, datetime, timedelta
from functools import wraps

api_bp = Blueprint('api', __name__)


def _hdate_str(g_date):
    hd = HebrewDate.from_gdate(g_date)
    return f'{hd.day} {hd.month} {hd.year}'


def get_user_from_request():
    """מנסה לזהות משתמש לפי API Key או Session Token."""
    key = request.headers.get('X-API-Key')
    if key:
        return User.query.filter_by(api_key=key).first()

    token = request.headers.get('X-Session-Token')
    if token:
        session = PhoneSession.query.filter_by(token=token, active=True).first()
        if session and session.expires_at > datetime.utcnow():
            return User.query.get(session.user_id)

    return None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_user_from_request()
        if not user:
            return jsonify({'error': 'נדרש אימות'}), 401
        return f(user, *args, **kwargs)
    return decorated


# ===== אימות PIN לשיחת ימות המשיח =====

@api_bp.route('/auth/request-pin', methods=['POST'])
def request_pin():
    data = request.get_json() or {}
    phone = data.get('phone', '').strip().replace('-', '').replace(' ', '')

    user = User.query.filter_by(phone=phone).first()
    if not user:
        user = User.query.filter_by(phone_husband=phone).first()

    if not user:
        return jsonify({'found': False, 'message': 'מספר לא רשום במערכת'})

    return jsonify({'found': True, 'message': 'אנא הקלד את קוד ה-PIN שלך'})


@api_bp.route('/auth/verify-pin', methods=['POST'])
def verify_pin():
    data = request.get_json() or {}
    phone = data.get('phone', '').strip().replace('-', '').replace(' ', '')
    pin = str(data.get('pin', '')).strip()

    user = User.query.filter_by(phone=phone).first()
    if not user:
        user = User.query.filter_by(phone_husband=phone).first()

    if not user or not user.check_pin(pin):
        return jsonify({'success': False, 'message': 'PIN שגוי'}), 401

    session = PhoneSession(
        user_id=user.id,
        phone=phone,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        active=True
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'success': True,
        'token': session.token,
        'expires_in': 3600,
        'message': f'שלום {user.name or ""}! מחובר בהצלחה'
    })


@api_bp.route('/auth/logout', methods=['POST'])
def api_logout():
    token = request.headers.get('X-Session-Token')
    if token:
        session = PhoneSession.query.filter_by(token=token).first()
        if session:
            session.active = False
            db.session.commit()
    return jsonify({'success': True})


# ===== ווסתות =====

@api_bp.route('/vesetot/expected', methods=['GET'])
@require_auth
def get_expected(user):
    """ווסתות צפויות — לתפריט 'ימי פרישה קרובים'"""
    vesetot = Veeset.query.filter_by(user_id=user.id)\
                  .order_by(Veeset.gregorian_date).all()
    expected = get_all_expected(user, vesetot)
    result = []
    for e in expected:
        result.append({
            'type': e['type'],
            'label': e.get('label', ''),
            'gregorian_date': e['gregorian_date'].isoformat(),
            'onah': e.get('onah', ''),
            'onah_label': 'יום' if e.get('onah') == 'yom' else 'לילה'
        })
    return jsonify({'expected': result})


@api_bp.route('/vesetot', methods=['GET'])
@require_auth
def get_vesetot(user):
    """היסטוריית ווסתות"""
    limit = request.args.get('limit', 10, type=int)
    vesetot = Veeset.query.filter_by(user_id=user.id)\
                  .order_by(Veeset.gregorian_date.desc()).limit(limit).all()
    return jsonify({'vesetot': [{
        'id': v.id,
        'hebrew_date': v.hebrew_date_str,
        'gregorian_date': v.gregorian_date.isoformat(),
        'time': v.time_of_sighting,
        'onah': v.onah,
        'onah_label': 'יום' if v.onah == 'yom' else 'לילה',
        'duration_days': v.duration_days,
        'notes': v.notes
    } for v in vesetot]})


@api_bp.route('/vesetot', methods=['POST'])
@require_auth
def add_veeset(user):
    """הוספת ראייה חדשה"""
    data = request.get_json() or {}

    # תאריך — ברירת מחדל היום
    date_str = data.get('gregorian_date', date.today().isoformat())
    g_date = date.fromisoformat(date_str)

    # שעה — ברירת מחדל עכשיו
    time_str = data.get('time', datetime.now().strftime('%H:%M'))

    onah = determine_onah(time_str, g_date, user)
    hebrew_str = _hdate_str(g_date)

    v = Veeset(
        user_id=user.id,
        gregorian_date=g_date,
        time_of_sighting=time_str,
        onah=onah,
        hebrew_date_str=hebrew_str,
        duration_days=data.get('duration_days', 1),
        notes=data.get('notes', 'דיווח מטלפון')
    )
    db.session.add(v)
    db.session.commit()

    # חישוב מחדש של קבועות
    try:
        recalculate_all(user.id)
    except Exception:
        pass

    return jsonify({
        'success': True,
        'veeset_id': v.id,
        'onah': onah,
        'onah_label': 'יום' if onah == 'yom' else 'לילה',
        'hebrew_date': hebrew_str,
        'gregorian_date': g_date.isoformat(),
        'message': f'ראייה נרשמה בהצלחה — {hebrew_str}, עונת {("יום" if onah == "yom" else "לילה")}'
    })


@api_bp.route('/vesetot/last', methods=['GET'])
@require_auth
def get_last_veeset(user):
    """קבלת הראייה האחרונה — לצורך עריכה/מחיקה"""
    v = Veeset.query.filter_by(user_id=user.id)\
              .order_by(Veeset.gregorian_date.desc()).first()
    if not v:
        return jsonify({'found': False, 'message': 'אין ראיות רשומות'})
    return jsonify({
        'found': True,
        'id': v.id,
        'hebrew_date': v.hebrew_date_str,
        'gregorian_date': v.gregorian_date.isoformat(),
        'time': v.time_of_sighting,
        'onah_label': 'יום' if v.onah == 'yom' else 'לילה',
        'duration_days': v.duration_days
    })


@api_bp.route('/vesetot/<int:veeset_id>', methods=['PUT'])
@require_auth
def edit_veeset(user, veeset_id):
    """עריכת ראייה קיימת"""
    v = Veeset.query.filter_by(id=veeset_id, user_id=user.id).first()
    if not v:
        return jsonify({'error': 'ראייה לא נמצאה'}), 404

    data = request.get_json() or {}

    if 'gregorian_date' in data:
        v.gregorian_date = date.fromisoformat(data['gregorian_date'])
        v.hebrew_date_str = _hdate_str(v.gregorian_date)

    if 'time' in data:
        v.time_of_sighting = data['time']
        v.onah = determine_onah(data['time'], v.gregorian_date, user)

    if 'duration_days' in data:
        v.duration_days = int(data['duration_days'])

    if 'notes' in data:
        v.notes = data['notes']

    db.session.commit()

    try:
        recalculate_all(user.id)
    except Exception:
        pass

    return jsonify({'success': True, 'message': 'הראייה עודכנה בהצלחה'})


@api_bp.route('/vesetot/<int:veeset_id>', methods=['DELETE'])
@require_auth
def delete_veeset(user, veeset_id):
    """מחיקת ראייה"""
    v = Veeset.query.filter_by(id=veeset_id, user_id=user.id).first()
    if not v:
        return jsonify({'error': 'ראייה לא נמצאה'}), 404

    db.session.delete(v)
    db.session.commit()

    try:
        recalculate_all(user.id)
    except Exception:
        pass

    return jsonify({'success': True, 'message': 'הראייה נמחקה בהצלחה'})


@api_bp.route('/day-status', methods=['GET'])
@require_auth
def day_status(user):
    """האם היום יום פרישה"""
    date_str = request.args.get('date', date.today().isoformat())
    g_date = date.fromisoformat(date_str)
    vesetot = Veeset.query.filter_by(user_id=user.id)\
                  .order_by(Veeset.gregorian_date).all()
    expected = get_all_expected(user, vesetot)
    matches = [e for e in expected if e['gregorian_date'] == g_date]
    return jsonify({
        'date': date_str,
        'is_prisha': len(matches) > 0,
        'prisha_types': [m['type'] for m in matches],
        'message': matches[0]['label'] if matches else 'אין יום פרישה היום'
    })


# ===== הריון =====

@api_bp.route('/pregnancy/start', methods=['POST'])
@require_auth
def start_pregnancy(user):
    """עדכון הריון חדש"""
    data = request.get_json() or {}
    start_str = data.get('start_date', date.today().isoformat())
    start = date.fromisoformat(start_str)
    due = start + timedelta(weeks=40)

    user.pregnancy_active = True
    user.pregnancy_start_date = start
    user.pregnancy_due_date = due
    user.pregnancy_vesetot_cancelled_at = None
    db.session.commit()

    return jsonify({
        'success': True,
        'due_date': due.isoformat(),
        'message': f'הריון עודכן! תאריך לידה משוער: {due.strftime("%d/%m/%Y")}'
    })


@api_bp.route('/pregnancy/end', methods=['POST'])
@require_auth
def end_pregnancy(user):
    """סיום הריון"""
    user.pregnancy_active = False
    user.pregnancy_start_date = None
    user.pregnancy_due_date = None
    db.session.commit()
    return jsonify({'success': True, 'message': 'הריון הסתיים, חזרה לחישוב רגיל'})


# ===== תזכורות =====

@api_bp.route('/reminders', methods=['GET'])
@require_auth
def get_reminders(user):
    """תזכורות קרובות"""
    today = date.today()
    reminders = Reminder.query.filter_by(user_id=user.id, active=True)\
                    .filter(Reminder.gregorian_date >= today)\
                    .order_by(Reminder.gregorian_date).limit(5).all()
    return jsonify({'reminders': [{
        'id': r.id,
        'title': r.title,
        'date': r.gregorian_date.isoformat(),
        'time': r.time_of_day,
        'recurrence': r.recurrence
    } for r in reminders]})


@api_bp.route('/reminders', methods=['POST'])
@require_auth
def add_reminder(user):
    """הוספת תזכורת"""
    data = request.get_json() or {}

    date_str = data.get('date', date.today().isoformat())
    r = Reminder(
        user_id=user.id,
        title=data.get('title', 'תזכורת'),
        message=data.get('message', ''),
        gregorian_date=date.fromisoformat(date_str),
        time_of_day=data.get('time', '08:00'),
        recurrence=data.get('recurrence', 'once'),
        type='personal'
    )
    db.session.add(r)
    db.session.commit()
    return jsonify({'success': True, 'reminder_id': r.id, 'message': 'תזכורת נוספה בהצלחה'})


@api_bp.route('/reminders/<int:reminder_id>', methods=['DELETE'])
@require_auth
def delete_reminder(user, reminder_id):
    """מחיקת תזכורת"""
    r = Reminder.query.filter_by(id=reminder_id, user_id=user.id).first()
    if not r:
        return jsonify({'error': 'תזכורת לא נמצאה'}), 404
    r.active = False
    db.session.commit()
    return jsonify({'success': True, 'message': 'תזכורת נמחקה'})


# ===== הגדרות =====

@api_bp.route('/settings', methods=['GET'])
@require_auth
def get_settings(user):
    """קבלת הגדרות נוכחיות"""
    return jsonify({
        'name': user.name,
        'location': user.location_name,
        'minhag_yemei_sfira': user.minhag_yemei_sfira,
        'minhag_or_zarua': user.minhag_or_zarua,
        'minhag_shmirah_kefulah': user.minhag_shmirah_kefulah,
        'minhag_tikou': user.minhag_tikou,
        'minhag_haflagah_aruka': user.minhag_haflagah_aruka,
        'use_auto_times': user.use_auto_times,
        'reminder_hours_before': user.reminder_hours_before
    })


@api_bp.route('/settings/pin', methods=['PUT'])
@require_auth
def change_pin(user):
    """שינוי PIN"""
    data = request.get_json() or {}
    old_pin = str(data.get('old_pin', '')).strip()
    new_pin = str(data.get('new_pin', '')).strip()

    if not user.check_pin(old_pin):
        return jsonify({'success': False, 'message': 'PIN ישן שגוי'}), 401

    if len(new_pin) < 4:
        return jsonify({'success': False, 'message': 'PIN חייב להיות לפחות 4 ספרות'}), 400

    user.set_pin(new_pin)
    db.session.commit()
    return jsonify({'success': True, 'message': 'PIN עודכן בהצלחה'})


@api_bp.route('/settings/minhag', methods=['PUT'])
@require_auth
def update_minhag(user):
    """עדכון מנהגים"""
    data = request.get_json() or {}

    if 'minhag_yemei_sfira' in data:
        user.minhag_yemei_sfira = data['minhag_yemei_sfira']
    if 'minhag_or_zarua' in data:
        user.minhag_or_zarua = bool(data['minhag_or_zarua'])
    if 'minhag_shmirah_kefulah' in data:
        user.minhag_shmirah_kefulah = bool(data['minhag_shmirah_kefulah'])
    if 'minhag_tikou' in data:
        user.minhag_tikou = bool(data['minhag_tikou'])
    if 'minhag_haflagah_aruka' in data:
        user.minhag_haflagah_aruka = bool(data['minhag_haflagah_aruka'])

    db.session.commit()
    return jsonify({'success': True, 'message': 'מנהגים עודכנו'})
