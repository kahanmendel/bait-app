from hdate import HebrewDate
from datetime import timedelta, date


def check_kavua(vesetot_list: list) -> dict | None:
    if len(vesetot_list) < 3:
        return None

    last3 = vesetot_list[-3:]
    days = [HebrewDate.from_gdate(v.gregorian_date).day for v in last3]
    onahs = [v.onah for v in last3]
    if len(set(days)) == 1 and len(set(onahs)) == 1:
        return {
            'type': 'yom_hachodesh', 'hebrew_day': days[0], 'onah': onahs[0],
            'message': f'זוהתה וסת קבועה ביום {days[0]} לחודש, עונת {"יום" if onahs[0] == "yom" else "לילה"}'
        }

    if len(vesetot_list) >= 4:
        last4 = vesetot_list[-4:]
        haflagot = [(last4[i].gregorian_date - last4[i-1].gregorian_date).days + 1
                    for i in range(1, 4)]
        if len(set(haflagot)) == 1 and len(set([v.onah for v in last4[1:]])) == 1:
            return {
                'type': 'haflagah', 'days': haflagot[0], 'onah': last4[-1].onah,
                'message': f'זוהתה וסת קבועה בהפלגה של {haflagot[0]} ימים, עונת {"יום" if last4[-1].onah == "yom" else "לילה"}'
            }
    return None


def _next_hebrew_month_date(g_date: date, target_day: int):
    hd = HebrewDate.from_gdate(g_date)
    next_d = g_date + timedelta(days=29)
    hd_next = HebrewDate.from_gdate(next_d)
    if hd_next.month == hd.month:
        next_d += timedelta(days=2)
        hd_next = HebrewDate.from_gdate(next_d)
    try:
        target = HebrewDate(hd_next.year, hd_next.month, target_day)
        return target.to_gdate()
    except Exception:
        return None


def _check_tikou(expected_date: date, vesetot_list: list) -> bool:
    for v in vesetot_list:
        if v.gregorian_date < expected_date:
            end_date = v.gregorian_date + timedelta(days=v.duration_days - 1)
            if end_date >= expected_date:
                return True
    return False


def _check_haflagah_ketana(expected_date: date, last_veeset_date: date,
                            vesetot_list: list, kavua_days: int) -> bool:
    for v in vesetot_list:
        if last_veeset_date < v.gregorian_date < expected_date:
            delta = (expected_date - v.gregorian_date).days + 1
            if delta < kavua_days:
                return True
    return False


def should_cancel_kavua(kavua_record, vesetot_list: list, user) -> bool:
    """
    בודק האם לבטל וסת קבועה.

    יום החודש:
      - 3 חודשים עברו ולא ראתה ביום הקבוע + עונה = מתבטל
      - גם בלי ווסתות כלל (3 חודשים עברו = מספיק)

    הפלגה:
      - צריך לפחות 3 ווסתות אחרי הקבועה
      - כל וסת שלא הגיעה בהפלגה הצפויה = פספוס
      - 3 פספוסים ברצף = מתבטל
    """
    if not kavua_record.active:
        return False

    today = date.today()
    established = kavua_record.established_at.date()
    missed_count = 0

    if kavua_record.type == 'yom_hachodesh':
        # יום החודש: בודק לפי חודשים שעברו — גם בלי ווסתות
        current_date = established

        for _ in range(36):
            expected_date = _next_hebrew_month_date(
                current_date, kavua_record.hebrew_day_of_month)

            if expected_date is None or expected_date > today:
                break

            saw_exact = any(
                v.gregorian_date == expected_date and v.onah == kavua_record.onah
                for v in vesetot_list)

            if saw_exact:
                missed_count = 0
                current_date = expected_date
                continue

            if user.minhag_tikou and _check_tikou(expected_date, vesetot_list):
                current_date = expected_date
                continue

            missed_count += 1
            if missed_count >= 3:
                return True
            current_date = expected_date

    elif kavua_record.type == 'haflagah':
        # הפלגה: צריך לפחות 3 ווסתות אחרי הקבועה
        vesetot_after = [v for v in vesetot_list
                         if v.gregorian_date > established]

        if len(vesetot_after) < 3:
            return False  # אין מספיק ווסתות לבדוק

        # בודק לפי ווסתות בפועל — לא לפי תאריכים עתידיים
        for i, v in enumerate(vesetot_after):
            # מה ההפלגה מהוסת הקודמת?
            if i == 0:
                prev_date = established
            else:
                prev_date = vesetot_after[i-1].gregorian_date

            actual_haflagah = (v.gregorian_date - prev_date).days + 1
            expected_date = prev_date + timedelta(days=kavua_record.haflagah_days - 1)

            # ראתה בדיוק ביום הצפוי + אותה עונה
            saw_exact = (v.gregorian_date == expected_date and
                         v.onah == kavua_record.onah)

            if saw_exact:
                missed_count = 0
                continue

            # תיקו — ראתה לפני וזה המשיך
            if user.minhag_tikou and _check_tikou(expected_date, vesetot_after[:i+1]):
                continue

            # מנהג הפלגה ארוכה — הגיעה בהפלגה קצרה יותר
            if (user.minhag_haflagah_aruka and
                    actual_haflagah < kavua_record.haflagah_days):
                continue

            # פספוס — ראתה בהפלגה שונה
            missed_count += 1
            if missed_count >= 3:
                return True

    return False


def get_kavua_expected(kavua_record, last_veeset) -> dict | None:
    if not kavua_record or not kavua_record.active:
        return None

    from logic.calculations import hdate_str

    if kavua_record.type == 'yom_hachodesh':
        expected_date = _next_hebrew_month_date(
            last_veeset.gregorian_date, kavua_record.hebrew_day_of_month)
        if not expected_date:
            return None
        return {
            'type': 'kavua_yom_hachodesh',
            'gregorian_date': expected_date,
            'hebrew_date': hdate_str(expected_date),
            'onah': kavua_record.onah,
            'label': f'⭐ וסת קבועה — יום {kavua_record.hebrew_day_of_month} לחודש, עונת {"יום" if kavua_record.onah == "yom" else "לילה"}'
        }

    elif kavua_record.type == 'haflagah':
        expected_date = last_veeset.gregorian_date + timedelta(
            days=kavua_record.haflagah_days - 1)
        return {
            'type': 'kavua_haflagah',
            'gregorian_date': expected_date,
            'hebrew_date': hdate_str(expected_date),
            'onah': kavua_record.onah,
            'haflagah_days': kavua_record.haflagah_days,
            'label': f'⭐ וסת קבועה — הפלגה {kavua_record.haflagah_days} ימים, עונת {"יום" if kavua_record.onah == "yom" else "לילה"}'
        }
    return None
