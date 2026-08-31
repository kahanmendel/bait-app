from flask import Blueprint, render_template
from flask_login import login_required, current_user
from logic.expected import get_user_expected
from datetime import timedelta

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
    # ווסתות ממוינות לפי תאריך עולה (לחישובים)
    vesetot, expected, active_kavuot = get_user_expected(current_user)

    last_veeset = vesetot[-1] if vesetot else None

    # חישוב הפלגה לכל וסת — מילון id → ימי הפלגה
    veeset_haflagah = {}
    for i, v in enumerate(vesetot):
        if i > 0:
            prev = vesetot[i - 1]
            delta = (v.gregorian_date - prev.gregorian_date).days + 1
            veeset_haflagah[v.id] = delta

    # תאריך ביטול ווסתות בהריון
    pregnancy_cancel_date = None
    if current_user.pregnancy_active and current_user.pregnancy_start_date:
        pregnancy_cancel_date = current_user.pregnancy_start_date + timedelta(days=90)

    # היסטוריה: חדש למעלה
    vesetot_display = list(reversed(vesetot))

    return render_template('dashboard.html',
                           vesetot=vesetot_display,
                           veeset_haflagah=veeset_haflagah,
                           expected=expected,
                           active_kavuot=active_kavuot,
                           last_veeset=last_veeset,
                           pregnancy_cancel_date=pregnancy_cancel_date)
