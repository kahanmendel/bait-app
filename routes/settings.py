from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import User, normalize_phone

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        # מספרי טלפון
        phone_husband = normalize_phone(request.form.get('phone_husband'))

        # בדיקה שמספר הבעל לא שייך למשתמש אחר
        if phone_husband:
            existing = User.query.filter_by(phone_husband=phone_husband).first()
            if existing and existing.id != current_user.id:
                flash('מספר הבעל כבר רשום למשתמש אחר', 'danger')
                return render_template('settings.html')
            existing2 = User.query.filter_by(phone=phone_husband).first()
            if existing2 and existing2.id != current_user.id:
                flash('מספר זה כבר רשום כמספר ראשי', 'danger')
                return render_template('settings.html')
            current_user.phone_husband = phone_husband
        elif 'phone_husband' in request.form:
            # הוזן במפורש כריק — הסרת המספר, ואיתו הקוד הנפרד שלו
            current_user.phone_husband = None
            current_user.set_pin_husband(None)

        # שינוי קודים — לאישה ולבעל בנפרד. שדה ריק פירושו "אל תשנה"
        new_pin = request.form.get('new_pin', '').strip()
        if new_pin:
            if len(new_pin) < 4:
                flash('הקוד חייב להיות לפחות 4 ספרות', 'danger')
                return render_template('settings.html')
            current_user.set_pin(new_pin)

        new_pin_husband = request.form.get('new_pin_husband', '').strip()
        if new_pin_husband:
            if len(new_pin_husband) < 4:
                flash('קוד הבעל חייב להיות לפחות 4 ספרות', 'danger')
                return render_template('settings.html')
            if not phone_husband:
                flash('כדי לקבוע קוד לבעל יש להזין קודם את מספר הטלפון שלו', 'danger')
                return render_template('settings.html')
            current_user.set_pin_husband(new_pin_husband)

        # ביטול הקוד הנפרד — חזרה לקוד משותף לשני המספרים
        if 'clear_pin_husband' in request.form:
            current_user.set_pin_husband(None)

        # שדה שאינו בטופס אינו אמור למחוק ערך קיים
        if 'name' in request.form:
            current_user.name = request.form.get('name', '').strip()
        current_user.location_name = request.form.get('location_name', 'ירושלים')
        current_user.use_auto_times = 'use_auto_times' in request.form
        current_user.custom_hanetz = request.form.get('custom_hanetz') or None
        current_user.custom_shkia = request.form.get('custom_shkia') or None
        current_user.minhag_yemei_sfira = request.form.get('minhag_yemei_sfira', 'ashkenaz')
        current_user.minhag_or_zarua = 'minhag_or_zarua' in request.form
        current_user.minhag_shmirah_kefulah = 'minhag_shmirah_kefulah' in request.form
        current_user.minhag_tikou = 'minhag_tikou' in request.form
        current_user.minhag_haflagah_aruka = 'minhag_haflagah_aruka' in request.form
        current_user.reminder_hours_before = int(
            request.form.get('reminder_hours_before', 12))
        db.session.commit()
        flash('הגדרות נשמרו בהצלחה', 'success')
        return redirect(url_for('settings.settings'))
    return render_template('settings.html')
