from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import VesetKavua
from datetime import date, timedelta
from hdate import HebrewDate

pregnancy_bp = Blueprint('pregnancy', __name__)

PREGNANCY_WEEKS = 40

def _hdate_str(g_date):
    hd = HebrewDate.from_gdate(g_date)
    return f'{hd.day} {hd.month} {hd.year}'


@pregnancy_bp.route('/pregnancy/start', methods=['GET', 'POST'])
@login_required
def start_pregnancy():
    if request.method == 'POST':
        # תאריך הריון = ראייה אחרונה (ברירת מחדל) או תאריך שהוזן
        date_str = request.form.get('start_date')
        start_date = date.fromisoformat(date_str)
        due_date = start_date + timedelta(weeks=PREGNANCY_WEEKS)

        current_user.pregnancy_start_date = start_date
        current_user.pregnancy_due_date = due_date
        current_user.pregnancy_active = True
        current_user.pregnancy_vesetot_cancelled_at = None
        db.session.commit()

        flash(f'✅ הריון עודכן! תאריך לידה משוער: {due_date} ({_hdate_str(due_date)})', 'success')
        flash('ווסתות יבוטלו אוטומטית לאחר 90 יום מתחילת הריון', 'info')
        return redirect(url_for('dashboard.index'))

    # ברירת מחדל: ראייה אחרונה
    from models import Veeset
    last_veeset = Veeset.query.filter_by(user_id=current_user.id)\
                    .order_by(Veeset.gregorian_date.desc()).first()
    default_date = last_veeset.gregorian_date if last_veeset else date.today()
    return render_template('pregnancy_start.html', default_date=default_date)


@pregnancy_bp.route('/pregnancy/end', methods=['GET', 'POST'])
@login_required
def end_pregnancy():
    if request.method == 'POST':
        current_user.pregnancy_active = False
        current_user.pregnancy_start_date = None
        current_user.pregnancy_due_date = None
        current_user.pregnancy_vesetot_cancelled_at = None
        db.session.commit()
        flash('הריון הסתיים. ניתן להמשיך לעדכן ווסתות רגיל.', 'success')
        return redirect(url_for('dashboard.index'))
    return render_template('pregnancy_end.html')


def check_pregnancy_cancel_vesetot(user):
    """
    בודק אם עברו 90 יום מתחילת הריון — ומבטל ווסתות וקבועות.
    נקרא בכל טעינת לוח ראשי.
    """
    if not user.pregnancy_active or not user.pregnancy_start_date:
        return False
    if user.pregnancy_vesetot_cancelled_at:
        return True  # כבר בוטל

    days_since = (date.today() - user.pregnancy_start_date).days
    if days_since >= 90:
        # ביטול כל הקבועות
        VesetKavua.query.filter_by(user_id=user.id, active=True)\
                  .update({'active': False})
        user.pregnancy_vesetot_cancelled_at = date.today()
        db.session.commit()
        return True
    return False
