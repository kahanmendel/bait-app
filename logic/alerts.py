"""
התראות תקלה למייל אישי, דרך SMTP.

ההתראה נשלחת מתוך בקשה חיה — לפעמים בלב שיחה טלפונית — ולכן יש כאן שני
מיגונים: timeout קצר ל-SMTP, ואיחוד התראות לפי מזהה תקלה כך שתקלה חוזרת
שולחת מייל אחד לחלון זמן ולא מייל לכל ראייה. הפונקציה אינה זורקת חריגות
לעולם: תקלה בשליחת ההתראה לא תפיל את הפעולה שעליה היא מתריעה.

הגדרה בסביבה:
    ALERT_EMAIL    כתובת היעד להתראות
    SMTP_HOST      שרת ה-SMTP (ל-Gmail: smtp.gmail.com)
    SMTP_PORT      587 ל-STARTTLS, או 465 ל-SSL. ברירת מחדל 587
    SMTP_USER      שם המשתמש להתחברות
    SMTP_PASSWORD  סיסמה. ב-Gmail חייבת להיות App Password ולא סיסמת החשבון
    SMTP_FROM      כתובת השולח. ריק פירושו SMTP_USER
"""
import os
import smtplib
import socket
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate

from flask import current_app

from extensions import db
from models import AlertLog

# התראה לא תעכב שיחה טלפונית יותר מזה
SMTP_TIMEOUT = 5
# ברירת מחדל: מייל אחד לשעה לכל סוג תקלה
DEFAULT_MIN_INTERVAL_HOURS = 1


def _log(level, message):
    """כותב ללוג גם כשאין app context."""
    try:
        getattr(current_app.logger, level)(message)
    except Exception:
        pass


def _config():
    port_raw = os.getenv('SMTP_PORT', '587')
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
        _log('warning', f'alerts: SMTP_PORT לא מספרי ({port_raw}), משתמש ב-587')

    user = os.getenv('SMTP_USER')
    return {
        'to': os.getenv('ALERT_EMAIL'),
        'host': os.getenv('SMTP_HOST'),
        'port': port,
        'user': user,
        'password': os.getenv('SMTP_PASSWORD'),
        'sender': os.getenv('SMTP_FROM') or user,
    }


def _missing(config):
    """שמות ההגדרות החסרות לשליחה."""
    required = {'ALERT_EMAIL': config['to'], 'SMTP_HOST': config['host'],
                'SMTP_USER': config['user'], 'SMTP_PASSWORD': config['password']}
    return [name for name, value in required.items() if not value]


def _recently_sent(key, min_interval_hours):
    """
    האם כבר נשלחה התראה באותו מזהה בחלון הזמן.

    אם הבדיקה עצמה נכשלת מחזיר False ושולח — עדיף מייל כפול על תקלה
    שנבלעת בשקט.
    """
    try:
        since = datetime.utcnow() - timedelta(hours=min_interval_hours)
        return db.session.query(AlertLog.id)\
                 .filter(AlertLog.key == key, AlertLog.sent_at >= since)\
                 .first() is not None
    except Exception:
        _log('warning', 'alerts: בדיקת כפילות נכשלה, שולח בכל זאת')
        return False


def _record(key, subject, delivered):
    try:
        db.session.add(AlertLog(key=key, subject=subject[:300],
                                delivered=delivered))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        _log('warning', 'alerts: רישום ההתראה בבסיס הנתונים נכשל')


def _deliver(config, subject, body):
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = config['sender']
    message['To'] = config['to']
    message['Date'] = formatdate(localtime=True)
    message.set_content(body)

    if config['port'] == 465:
        server = smtplib.SMTP_SSL(config['host'], config['port'],
                                  timeout=SMTP_TIMEOUT)
    else:
        server = smtplib.SMTP(config['host'], config['port'],
                              timeout=SMTP_TIMEOUT)
    try:
        if config['port'] != 465:
            server.starttls()
        server.login(config['user'], config['password'])
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_email(subject, body):
    """
    שולח מייל יחיד, בלי איחוד ובלי רישום. מחזיר (האם יצא, הסבר).

    ההסבר מיועד להצגה למנהל — נתיב הדוח מחזיר אותו כדי שלא יצטרך לחפש בלוג
    למה המייל לא הגיע.
    """
    config = _config()
    missing = _missing(config)
    if missing:
        # לא נופלים בשקט: אם השליחה לא מוגדרת, זה עצמו צריך לצעוק בלוג
        reason = 'שליחת המייל אינה מוגדרת (חסר {})'.format(', '.join(missing))
        _log('error', f'alerts: {reason}. ההודעה: {subject}')
        return False, reason

    try:
        _deliver(config, subject, body)
    except (smtplib.SMTPException, socket.error, OSError) as exc:
        reason = f'{exc.__class__.__name__}: {exc}'
        _log('error', f'alerts: השליחה נכשלה ({reason}). ההודעה: {subject}')
        return False, reason
    except Exception as exc:
        reason = str(exc)
        _log('error', f'alerts: השליחה נכשלה ({reason}). ההודעה: {subject}')
        return False, reason

    _log('info', f'alerts: נשלח מייל — {subject}')
    return True, f'נשלח אל {config["to"]}'


def send_alert(subject, body, *, key,
               min_interval_hours=DEFAULT_MIN_INTERVAL_HOURS) -> bool:
    """
    שולח התראה על תקלה. מחזיר True אם מייל אכן יצא.

    key מזהה את סוג התקלה לצורך איחוד. subject ו-body הם טקסט חופשי.
    """
    if _missing(_config()):
        # חוסר הגדרה מדווח כבר ב-send_email, ואין מה לרשום כניסיון
        send_email(subject, body)
        return False

    if _recently_sent(key, min_interval_hours):
        _log('info', f'alerts: התראה על {key} נשלחה לאחרונה, מאוחד')
        return False

    delivered, _reason = send_email(subject, body)
    _record(key, subject, delivered=delivered)
    return delivered
