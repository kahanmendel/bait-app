from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets

SUPER_ADMIN_PHONE = '0533134298'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    phone_husband = db.Column(db.String(20), unique=True, nullable=True)
    pin_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100))
    # אדמין
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    # מיקום
    location_name = db.Column(db.String(100), default='ירושלים')
    location_lat = db.Column(db.Float, default=31.7683)
    location_lon = db.Column(db.Float, default=35.2137)
    use_auto_times = db.Column(db.Boolean, default=True)
    custom_hanetz = db.Column(db.String(5))
    custom_shkia = db.Column(db.String(5))
    # מנהגים
    minhag_or_zarua = db.Column(db.Boolean, default=False)
    minhag_shmirah_kefulah = db.Column(db.Boolean, default=False)
    minhag_tikou = db.Column(db.Boolean, default=False)
    minhag_haflagah_aruka = db.Column(db.Boolean, default=False)
    minhag_yemei_sfira = db.Column(db.String(10), default='ashkenaz')
    # הריון
    pregnancy_start_date = db.Column(db.Date)
    pregnancy_due_date = db.Column(db.Date)
    pregnancy_active = db.Column(db.Boolean, default=False)
    pregnancy_vesetot_cancelled_at = db.Column(db.Date)
    # תזכורות
    reminder_hours_before = db.Column(db.Integer, default=12)
    # API
    api_key = db.Column(db.String(64), unique=True,
                        default=lambda: secrets.token_hex(32))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vesetot = db.relationship('Veeset', backref='user', lazy=True)
    reminders = db.relationship('Reminder', backref='user', lazy=True)

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(str(pin))

    def check_pin(self, pin):
        return check_password_hash(self.pin_hash, str(pin))

    @property
    def yemei_sfira_days(self):
        return 4 if self.minhag_yemei_sfira == 'beit_yosef' else 5

    @property
    def pregnancy_vesetot_active(self):
        if not self.pregnancy_active or not self.pregnancy_start_date:
            return False
        from datetime import date
        return (date.today() - self.pregnancy_start_date).days < 90


class Veeset(db.Model):
    __tablename__ = 'vesetot'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    gregorian_date = db.Column(db.Date, nullable=False)
    time_of_sighting = db.Column(db.String(5), nullable=False)
    onah = db.Column(db.String(10), nullable=False)
    hebrew_date_str = db.Column(db.String(50))
    duration_days = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)
    hefsek_date = db.Column(db.Date)
    hefsek_time = db.Column(db.String(5))
    shiva_nekiim_start = db.Column(db.Date)
    tvila_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VesetKavua(db.Model):
    __tablename__ = 'vesetot_kvuot'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    hebrew_day_of_month = db.Column(db.Integer)
    haflagah_days = db.Column(db.Integer)
    onah = db.Column(db.String(10))
    active = db.Column(db.Boolean, default=True)
    established_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reminder(db.Model):
    __tablename__ = 'reminders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    veeset_id = db.Column(db.Integer, db.ForeignKey('vesetot.id'), nullable=True)
    type = db.Column(db.String(20))
    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    gregorian_date = db.Column(db.Date)
    time_of_day = db.Column(db.String(5), default='08:00')
    recurrence = db.Column(db.String(20), default='once')
    active = db.Column(db.Boolean, default=True)
    sent = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PhoneSession(db.Model):
    __tablename__ = 'phone_sessions'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True,
                      default=lambda: secrets.token_hex(32))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True)
