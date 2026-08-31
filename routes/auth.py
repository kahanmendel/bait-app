from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from extensions import db
from models import User, SUPER_ADMIN_PHONE, normalize_phone

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = normalize_phone(request.form['phone'])
        pin = request.form['pin'].strip()

        user = User.query.filter_by(phone=phone).first()
        if not user:
            user = User.query.filter_by(phone_husband=phone).first()

        # לבעל יכול להיות קוד משלו, ולכן האימות תלוי במספר שממנו נכנסו
        if user and user.check_pin_for(phone, pin):
            if not user.is_approved:
                flash('החשבון ממתין לאישור מנהל. נסה שוב מאוחר יותר.', 'danger')
                return render_template('login.html')
            login_user(user)
            return redirect(url_for('dashboard.index'))

        flash('מספר טלפון או PIN שגויים', 'danger')
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form['phone'].strip().replace('-', '').replace(' ', '')
        pin = request.form['pin'].strip()
        name = request.form.get('name', '').strip()

        if len(pin) < 4:
            flash('PIN חייב להיות לפחות 4 ספרות', 'danger')
            return render_template('register.html')

        if User.query.filter_by(phone=phone).first():
            flash('מספר טלפון כבר רשום במערכת', 'danger')
            return render_template('register.html')

        # Super Admin — מאושר אוטומטית
        is_super = phone == SUPER_ADMIN_PHONE
        user = User(
            phone=phone,
            name=name,
            is_approved=is_super,
            is_admin=is_super
        )
        user.set_pin(pin)
        db.session.add(user)
        db.session.commit()

        if is_super:
            login_user(user)
            flash('ברוך הבא, מנהל!', 'success')
            return redirect(url_for('dashboard.index'))
        else:
            flash('נרשמת בהצלחה! החשבון ממתין לאישור מנהל.', 'info')
            return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
