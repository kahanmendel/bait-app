from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models import Veeset, VesetKavua
from logic.onah import determine_onah
from logic.kavua import check_kavua, should_cancel_kavua
from logic.tvila import calc_earliest_hefsek, calc_tvila
from logic.recalculate import recalculate_all
from hdate import HebrewDate
from datetime import date, datetime

veeset_bp = Blueprint('veeset', __name__)


def _hebrew_str(g_date):
    hd = HebrewDate.from_gdate(g_date)
    return f'{hd.day} {hd.month} {hd.year}'


@veeset_bp.route('/add_veeset', methods=['GET', 'POST'])
@login_required
def add_veeset():
    if request.method == 'POST':
        date_str = request.form['date']
        time_str = request.form['time']
        duration = int(request.form.get('duration_days', 1))
        notes = request.form.get('notes', '')
        g_date = date.fromisoformat(date_str)
        onah = determine_onah(time_str, g_date, current_user)

        v = Veeset(
            user_id=current_user.id,
            gregorian_date=g_date,
            time_of_sighting=time_str,
            onah=onah,
            hebrew_date_str=_hebrew_str(g_date),
            duration_days=duration,
            notes=notes
        )
        db.session.add(v)
        db.session.commit()

        all_vesetot = Veeset.query.filter_by(user_id=current_user.id)\
                          .order_by(Veeset.gregorian_date).all()

        # בדיקת קבועה חדשה
        kavua = check_kavua(all_vesetot)
        if kavua:
            existing = VesetKavua.query.filter_by(
                user_id=current_user.id, type=kavua['type'], active=True).first()
            if not existing:
                new_kavua = VesetKavua(
                    user_id=current_user.id, type=kavua['type'],
                    hebrew_day_of_month=kavua.get('hebrew_day'),
                    haflagah_days=kavua.get('days'),
                    onah=kavua['onah'], active=True,
                    established_at=datetime.utcnow())
                db.session.add(new_kavua)
                db.session.commit()
                flash(f'⚠️ {kavua["message"]}', 'kavua')

        # בדיקת ביטול — רק על ווסתות שאחרי כל קבועה
        active_kavuot = VesetKavua.query.filter_by(
            user_id=current_user.id, active=True).all()
        for k in active_kavuot:
            vesetot_after = [v for v in all_vesetot
                             if v.gregorian_date > k.established_at.date()]
            if should_cancel_kavua(k, vesetot_after, current_user):
                k.active = False
                db.session.commit()
                flash('וסת קבועה בוטלה', 'success')

        hefsek_info = calc_earliest_hefsek(v, current_user)
        flash(f'וסת נוספה — עונת {"יום" if onah == "yom" else "לילה"}', 'success')
        flash(f'📅 {hefsek_info["label"]}', 'info')
        return redirect(url_for('dashboard.index'))
    return render_template('add_veeset.html')


@veeset_bp.route('/edit_veeset/<int:veeset_id>', methods=['GET', 'POST'])
@login_required
def edit_veeset(veeset_id):
    v = Veeset.query.filter_by(id=veeset_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        date_str = request.form['date']
        time_str = request.form['time']
        duration = int(request.form.get('duration_days', 1))
        notes = request.form.get('notes', '')
        g_date = date.fromisoformat(date_str)
        onah = determine_onah(time_str, g_date, current_user)

        v.gregorian_date = g_date
        v.time_of_sighting = time_str
        v.onah = onah
        v.hebrew_date_str = _hebrew_str(g_date)
        v.duration_days = duration
        v.notes = notes
        # איפוס הפסק טהרה אם התאריך השתנה
        v.hefsek_date = None
        v.hefsek_time = None
        v.shiva_nekiim_start = None
        v.tvila_date = None
        db.session.commit()

        messages = recalculate_all(current_user.id)
        flash('וסת עודכנה — חישוב מחדש בוצע', 'success')
        for msg in messages:
            flash(f'⚠️ {msg}', 'kavua')
        return redirect(url_for('dashboard.index'))

    return render_template('edit_veeset.html', veeset=v)


@veeset_bp.route('/delete_veeset/<int:veeset_id>')
@login_required
def delete_veeset(veeset_id):
    v = Veeset.query.filter_by(id=veeset_id, user_id=current_user.id).first_or_404()
    db.session.delete(v)
    db.session.commit()
    messages = recalculate_all(current_user.id)
    flash('וסת נמחקה — חישוב מחדש בוצע', 'success')
    for msg in messages:
        flash(f'⚠️ {msg}', 'kavua')
    return redirect(url_for('dashboard.index'))


@veeset_bp.route('/end_veeset/<int:veeset_id>', methods=['GET', 'POST'])
@login_required
def end_veeset(veeset_id):
    v = Veeset.query.filter_by(id=veeset_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        end_date_str = request.form['end_date']
        end_time_str = request.form['end_time']
        end_date = date.fromisoformat(end_date_str)

        duration = (end_date - v.gregorian_date).days + 1
        if duration < 1:
            flash('תאריך סיום לא יכול להיות לפני תאריך התחלה', 'danger')
            return render_template('end_veeset.html', veeset=v)

        end_onah = determine_onah(end_time_str, end_date, current_user)
        v.duration_days = duration
        v.notes = (v.notes or '') + \
            f' | סיום: {end_date} {end_time_str} עונת {"יום" if end_onah == "yom" else "לילה"}'
        db.session.commit()

        flash(f'סיום ראייה עודכן — {duration} ימים', 'success')
        hefsek_info = calc_earliest_hefsek(v, current_user)
        flash(f'📅 {hefsek_info["label"]}', 'info')
        return redirect(url_for('dashboard.index'))

    return render_template('end_veeset.html', veeset=v)


@veeset_bp.route('/hefsek/<int:veeset_id>', methods=['GET', 'POST'])
@login_required
def hefsek(veeset_id):
    v = Veeset.query.filter_by(id=veeset_id, user_id=current_user.id).first_or_404()
    hefsek_info = calc_earliest_hefsek(v, current_user)

    if request.method == 'POST':
        hefsek_date_str = request.form.get('hefsek_date')
        hefsek_time_str = request.form.get('hefsek_time', '18:00')
        hefsek_date = date.fromisoformat(hefsek_date_str)

        if hefsek_date < hefsek_info['hefsek_date']:
            flash(f'לא ניתן לעשות הפסק לפני {hefsek_info["hebrew_date"]}', 'danger')
            return render_template('hefsek.html', veeset=v, hefsek_info=hefsek_info)

        tvila_info = calc_tvila(hefsek_date)
        v.hefsek_date = hefsek_date
        v.hefsek_time = hefsek_time_str
        v.shiva_nekiim_start = tvila_info['shiva_start']
        v.tvila_date = tvila_info['tvila_date']
        db.session.commit()

        flash(f'✅ הפסק טהרה נרשם! {tvila_info["label"]}', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('hefsek.html', veeset=v, hefsek_info=hefsek_info)
