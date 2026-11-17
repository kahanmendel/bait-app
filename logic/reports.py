"""
דוח המנויים שנשלח במייל.

מחזיר טקסט פשוט ולא HTML — נקרא טוב בטלפון, ואינו נשבר בשום לקוח מייל.
שלושת המצבים מגיעים מ-User.status: מחובר, ממתין לאישור, ונדחה. ההפרדה בין
השניים האחרונים התאפשרה רק עם הוספת rejected_at; לפניה חשבון שנדחה נראה
בבסיס הנתונים בדיוק כמו חשבון שטרם אושר.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func

from extensions import db
from models import User, Veeset

ISRAEL = ZoneInfo('Asia/Jerusalem')

# סדר ההצגה בדוח: קודם מה שדורש פעולה
STATUS_ORDER = ('pending', 'approved', 'rejected')
STATUS_TITLES = {
    'pending': 'ממתינים לאישור',
    'approved': 'מחוברים',
    'rejected': 'נדחו',
}


def _date(value):
    return value.strftime('%d/%m/%Y') if value else '—'


def _datetime(value):
    return value.strftime('%d/%m/%Y %H:%M') if value else '—'


def _veeset_stats():
    """user_id -> מספר ראיות, תאריך האחרונה, וכמה דורשות אימות עונה."""
    stats = {}
    rows = db.session.query(
        Veeset.user_id,
        func.count(Veeset.id),
        func.max(Veeset.gregorian_date),
    ).group_by(Veeset.user_id).all()
    for user_id, count, last in rows:
        stats[user_id] = {'count': count, 'last': last, 'review': 0}

    # NULL אינו נתפס בתנאי הזה, וזו ההתנהגות הרצויה לרשומות ישנות
    review_rows = db.session.query(Veeset.user_id, func.count(Veeset.id))\
        .filter(Veeset.onah_needs_review)\
        .group_by(Veeset.user_id).all()
    for user_id, count in review_rows:
        stats.setdefault(user_id, {'count': 0, 'last': None, 'review': 0})
        stats[user_id]['review'] = count

    return stats


def _describe(user, stats, index):
    """פסקה אחת לחשבון."""
    info = stats.get(user.id, {'count': 0, 'last': None, 'review': 0})
    lines = [
        f'{index}. {user.name or "ללא שם"}' + ('  ⭐ מנהל' if user.is_admin else ''),
        f'   טלפון: {user.phone}' +
        (f'   טלפון בעל: {user.phone_husband}' if user.phone_husband else ''),
        f'   נרשם: {_datetime(user.created_at)}',
    ]
    if user.status == 'rejected':
        lines.append(f'   נדחה: {_datetime(user.rejected_at)}')
    lines.append(f'   ראיות: {info["count"]}   אחרונה: {_date(info["last"])}')
    if info['review'] == 1:
        lines.append('   ⚠️ ראייה אחת דורשת אימות עונה')
    elif info['review']:
        lines.append(f'   ⚠️ {info["review"]} ראיות דורשות אימות עונה')
    if user.pregnancy_active:
        lines.append(f'   בהריון מ-{_date(user.pregnancy_start_date)}')
    return lines


def build_users_report():
    """מחזיר (נושא, גוף) לדוח המנויים."""
    users = User.query.order_by(User.created_at.desc()).all()
    stats = _veeset_stats()

    groups = {status: [] for status in STATUS_ORDER}
    for user in users:
        groups[user.status].append(user)

    now = datetime.now(ISRAEL)
    counts = {status: len(groups[status]) for status in STATUS_ORDER}

    body = [
        'דוח מנויים — bait-app',
        f'נוצר: {now:%d/%m/%Y %H:%M} (שעון ישראל)',
        '',
        f'סך הכל {len(users)} חשבונות: '
        f'{counts["approved"]} מחוברים, '
        f'{counts["pending"]} ממתינים לאישור, '
        f'{counts["rejected"]} נדחו',
    ]

    for status in STATUS_ORDER:
        group = groups[status]
        body += ['', f'===== {STATUS_TITLES[status]} ({len(group)}) =====']
        if not group:
            body.append('אין')
            continue
        for index, user in enumerate(group, start=1):
            body += _describe(user, stats, index)

    if counts['pending'] == 1:
        body += ['', 'יש חשבון אחד שממתין לאישור שלך במסך הניהול.']
    elif counts['pending']:
        body += ['', f'יש {counts["pending"]} חשבונות שממתינים לאישור שלך '
                     'במסך הניהול.']

    subject = (f'bait-app: דוח מנויים — {len(users)} חשבונות, '
               f'{counts["pending"]} ממתינים')
    return subject, '\n'.join(body)
