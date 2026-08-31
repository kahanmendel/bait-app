from datetime import date, timedelta
from hdate import HebrewDate

def hdate_str(g_date):
    hd = HebrewDate.from_gdate(g_date)
    return f'{hd.day} {hd.month} {hd.year}'

def calc_onah_beinonit(last_veeset) -> dict:
    expected_date = last_veeset.gregorian_date + timedelta(days=29)
    return {
        'type': 'onah_beinonit',
        'gregorian_date': expected_date,
        'hebrew_date': hdate_str(expected_date),
        'onah': last_veeset.onah,
        'label': f'עונה בינונית — עונת {"יום" if last_veeset.onah == "yom" else "לילה"}'
    }

def calc_yom_hachodesh(last_veeset) -> dict:
    hd_last = HebrewDate.from_gdate(last_veeset.gregorian_date)
    day = hd_last.day
    next_month = last_veeset.gregorian_date + timedelta(days=29)
    hd_next = HebrewDate.from_gdate(next_month)
    if hd_next.month == hd_last.month:
        next_month += timedelta(days=2)
        hd_next = HebrewDate.from_gdate(next_month)
    try:
        target = HebrewDate(hd_next.year, hd_next.month, day)
        expected_date = target.to_gdate()
    except Exception:
        expected_date = next_month
    return {
        'type': 'yom_hachodesh',
        'gregorian_date': expected_date,
        'hebrew_date': hdate_str(expected_date),
        'onah': last_veeset.onah,
        'label': f'יום החודש — עונת {"יום" if last_veeset.onah == "yom" else "לילה"}'
    }

def calc_haflagah(prev_veeset, last_veeset, user=None,
                  all_vesetot=None) -> list:
    """
    מחשב הפלגה. מחזיר רשימה של עד 2 הפלגות.
    all_vesetot מועבר מבחוץ — לא שואל DB.
    """
    if not prev_veeset:
        return []

    delta = (last_veeset.gregorian_date - prev_veeset.gregorian_date).days + 1
    expected_date = last_veeset.gregorian_date + timedelta(days=delta - 1)

    results = [{
        'type': 'haflagah',
        'gregorian_date': expected_date,
        'hebrew_date': hdate_str(expected_date),
        'onah': last_veeset.onah,
        'haflagah_days': delta,
        'label': f'הפלגה {delta} ימים — עונת {"יום" if last_veeset.onah == "yom" else "לילה"}'
    }]

    # מנהג הפלגה ארוכה — בדיקה מהרשימה שהועברה
    if user and user.minhag_haflagah_aruka and all_vesetot:
        idx = next((i for i, v in enumerate(all_vesetot)
                    if v.gregorian_date == last_veeset.gregorian_date), None)
        if idx is not None and idx >= 2:
            prev2 = all_vesetot[idx - 2]
            prev1 = all_vesetot[idx - 1]
            old_delta = (prev1.gregorian_date - prev2.gregorian_date).days + 1
            if old_delta > delta:
                old_expected = last_veeset.gregorian_date + timedelta(days=old_delta - 1)
                results.append({
                    'type': 'haflagah',
                    'gregorian_date': old_expected,
                    'hebrew_date': hdate_str(old_expected),
                    'onah': last_veeset.onah,
                    'haflagah_days': old_delta,
                    'label': f'הפלגה {old_delta} ימים (קודמת) — עונת {"יום" if last_veeset.onah == "yom" else "לילה"}'
                })
    return results

def get_or_zarua(expected: dict) -> dict:
    if expected['onah'] == 'layla':
        return {**expected, 'onah': 'yom',
                'label': f'אור זרוע ({expected["label"]})', 'type': 'or_zarua'}
    else:
        prev_date = expected['gregorian_date'] - timedelta(days=1)
        return {**expected, 'gregorian_date': prev_date,
                'hebrew_date': hdate_str(prev_date), 'onah': 'layla',
                'label': f'אור זרוע ({expected["label"]})', 'type': 'or_zarua'}

def get_all_expected(user, vesetot_list: list) -> list:
    if not vesetot_list:
        return []
    last = vesetot_list[-1]
    prev = vesetot_list[-2] if len(vesetot_list) >= 2 else None
    results = []

    ob = calc_onah_beinonit(last)
    yh = calc_yom_hachodesh(last)
    # מעביר את הרשימה המלאה — לא שואל DB
    hf_list = calc_haflagah(prev, last, user, all_vesetot=vesetot_list)

    results.append(ob)
    results.append(yh)
    results.extend(hf_list)

    if user.minhag_or_zarua:
        results.append(get_or_zarua(ob))
        results.append(get_or_zarua(yh))
        for hf in hf_list:
            results.append(get_or_zarua(hf))

    return sorted(results, key=lambda x: x['gregorian_date'])
