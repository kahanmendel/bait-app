"""
Cron job — רץ ב-1 לכל חודש.
בודק וסתות קבועות מסוג יום החודש ומבטל אם עברו 3 פספוסים.
מופעל מ-Google Cloud Scheduler דרך HTTP POST ל-/cron/check-kavua
עם header Authorization: Bearer <CRON_SECRET>
"""
from flask import Blueprint, request, jsonify
from extensions import db
from models import User, Veeset, VesetKavua
from logic.kavua import should_cancel_kavua
import os

cron_bp = Blueprint('cron', __name__)

@cron_bp.route('/cron/check-kavua', methods=['POST'])
def check_kavua_cron():
    # אבטחה בסיסית — Cloud Scheduler שולח secret
    secret = request.headers.get('Authorization', '')
    if secret != f'Bearer {os.getenv("CRON_SECRET", "dev-cron-secret")}':
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
