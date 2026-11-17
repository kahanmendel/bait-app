"""
נתיבים ל-Google Cloud Scheduler, מאומתים ב-Authorization: Bearer <CRON_SECRET>.

    POST /cron/check-kavua     ב-1 לכל חודש — ביטול וסתות קבועות שנעקרו
    GET|POST /cron/users-report דוח המנויים במייל
"""
from flask import Blueprint, request, jsonify
from extensions import db
from models import User, Veeset, VesetKavua
from logic.kavua import should_cancel_kavua
from logic.alerts import send_email
from logic.reports import build_users_report
import os

cron_bp = Blueprint('cron', __name__)


def _authorized():
    expected = f'Bearer {os.getenv("CRON_SECRET", "dev-cron-secret")}'
    return request.headers.get('Authorization', '') == expected


@cron_bp.route('/cron/check-kavua', methods=['POST'])
def check_kavua_cron():
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    cancelled = 0
    # בדוק רק קבועות מסוג יום החודש
    kavuot = VesetKavua.query.filter_by(
        type='yom_hachodesh', active=True).all()

    for k in kavuot:
        user = User.query.get(k.user_id)
        if not user:
            continue
        vesetot = Veeset.query.filter_by(user_id=user.id)\
                     .order_by(Veeset.gregorian_date).all()
        if should_cancel_kavua(k, vesetot, user):
            k.active = False
            cancelled += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'checked': len(kavuot),
        'cancelled': cancelled
    })


@cron_bp.route('/cron/users-report', methods=['GET', 'POST'])
def users_report():
    """
    שולח במייל את דוח המנויים: מחוברים, ממתינים לאישור, ונדחו.

    מחזיר את סיבת הכשל בגוף התשובה, כדי שלא יהיה צריך לחפש בלוג למה המייל
    לא הגיע. מחזיר 502 בכשל שליחה, כך ש-Cloud Scheduler ינסה שוב.
    """
    if not _authorized():
        return jsonify({'error': 'unauthorized'}), 401

    subject, body = build_users_report()
    delivered, reason = send_email(subject, body)
    return jsonify({
        'success': delivered,
        'detail': reason,
        'subject': subject,
    }), (200 if delivered else 502)
