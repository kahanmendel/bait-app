from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import User
from logic.alerts import send_email
from logic.reports import build_users_report

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('אין לך הרשאה לעמוד זה', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/admin')
@login_required
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin.html', users=users)


@admin_bp.route('/admin/approve/<int:user_id>')
@login_required
@admin_required
def approve(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    # אישור מנקה דחייה קודמת, אחרת החשבון היה ממשיך להיראות נדחה בדוח
    user.rejected_at = None
    db.session.commit()
    flash(f'המשתמש {user.name or user.phone} אושר בהצלחה', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/admin/reject/<int:user_id>')
@login_required
@admin_required
def reject(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = False
    user.rejected_at = datetime.utcnow()
    db.session.commit()
    flash(f'המשתמש {user.name or user.phone} נחסם', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/admin/delete/<int:user_id>')
@login_required
@admin_required
def delete(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('לא ניתן למחוק את עצמך', 'danger')
        return redirect(url_for('admin.index'))
    db.session.delete(user)
    db.session.commit()
    flash('המשתמש נמחק', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/admin/send-report')
@login_required
@admin_required
def send_report():
    """שולח את דוח המנויים במייל עכשיו, ומציג מה קרה בפועל."""
    subject, body = build_users_report()
    delivered, reason = send_email(subject, body)
    if delivered:
        flash(f'הדוח נשלח — {reason}', 'success')
    else:
        flash(f'הדוח לא נשלח: {reason}', 'danger')
    return redirect(url_for('admin.index'))
