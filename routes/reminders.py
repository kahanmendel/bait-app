from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import Reminder
from datetime import date

reminders_bp = Blueprint('reminders', __name__)

RECURRENCE_LABELS = {
    'once': 'חד פעמי',
    'weekly': 'שבועי',
    'monthly_heb': 'חודשי עברי',
    'monthly_greg': 'חודשי לועזי',
    'yearly_heb': 'שנתי עברי',
    'yearly_greg': 'שנתי לועזי',
}

@reminders_bp.route('/reminders')
@login_required
def list_reminders():
    reminders = Reminder.query.filter_by(
        user_id=current_user.id, type='personal', active=True)\
        .order_by(Reminder.gregorian_date).all()
    return render_template('reminders.html',
                           reminders=reminders,
                           recurrence_labels=RECURRENCE_LABELS)

@reminders_bp.route('/reminders/add', methods=['GET', 'POST'])
@login_required
def add_reminder():
    if request.method == 'POST':
        r = Reminder(
            user_id=current_user.id,
            type='personal',
            title=request.form['title'],
            message=request.form.get('message', ''),
            gregorian_date=date.fromisoformat(request.form['date']),
            time_of_day=request.form.get('time', '08:00'),
            recurrence=request.form.get('recurrence', 'once'),
            active=True
        )
        db.session.add(r)
        db.session.commit()
        flash('תזכורת נוספה בהצלחה', 'success')
        return redirect(url_for('reminders.list_reminders'))
    return render_template('add_reminder.html', recurrence_labels=RECURRENCE_LABELS,
                           reminder=None)

@reminders_bp.route('/reminders/edit/<int:reminder_id>', methods=['GET', 'POST'])
@login_required
def edit_reminder(reminder_id):
    r = Reminder.query.filter_by(
        id=reminder_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        r.title = request.form['title']
        r.message = request.form.get('message', '')
        r.gregorian_date = date.fromisoformat(request.form['date'])
        r.time_of_day = request.form.get('time', '08:00')
        r.recurrence = request.form.get('recurrence', 'once')
        db.session.commit()
        flash('תזכורת עודכנה', 'success')
        return redirect(url_for('reminders.list_reminders'))
    return render_template('add_reminder.html', recurrence_labels=RECURRENCE_LABELS,
                           reminder=r)

@reminders_bp.route('/reminders/delete/<int:reminder_id>')
@login_required
def delete_reminder(reminder_id):
    r = Reminder.query.filter_by(
        id=reminder_id, user_id=current_user.id).first_or_404()
    r.active = False
    db.session.commit()
    flash('תזכורת נמחקה', 'success')
    return redirect(url_for('reminders.list_reminders'))
