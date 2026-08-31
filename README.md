# bait-app

מערכת לניהול וסתות וטהרת המשפחה — Flask + PostgreSQL, רצה על Google Cloud Run.

**Production:** https://bait-app-602446976212.europe-west1.run.app

## מבנה

```
main.py            application factory של Flask
extensions.py      db + login_manager
models.py          User, Veeset, VesetKavua, Reminder, PhoneSession
logic/             חישובי הלכה — עונות, וסתות קבועות, הפלגות, הפסק טהרה, טבילה
routes/            blueprints: auth, dashboard, veeset, settings, reminders,
                   pregnancy, admin, cron, api (JSON), yemot (שלוחות טלפוניות)
templates/         תבניות Jinja
```

## הרצה מקומית

```bash
cp .env.example .env      # ומלא ערכים
pip install -r requirements.txt
python main.py            # http://127.0.0.1:5000
```

בלי `DATABASE_URL` המערכת משתמשת ב-SQLite מקומי (`instance/bait_app.db`).

## דיפלוי

כל push ל-`main` מפעיל Cloud Build trigger שבונה את ה-`Dockerfile`, דוחף
ל-Artifact Registry ומעדכן את שירות Cloud Run `bait-app` ב-`europe-west1`.
הקונפיגורציה נמצאת ב-[cloudbuild.yaml](cloudbuild.yaml).

- GCP project: `project-027a37d6-72c3-49bc-9bf`
- Region: `europe-west1`
- Cloud SQL: `project-027a37d6-72c3-49bc-9bf:europe-west1:bait-app-db`

### משתני סביבה בענן

מוזרקים מ-Secret Manager אל השירות: `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET`,
`YEMOT_API_SECRET`. ראה [.env.example](.env.example) לתיאור כל אחד.

## ממשקים חיצוניים

| נתיב | תיאור |
|------|-------|
| `/api/*` | REST/JSON — אימות ב-`X-API-Key` או `X-Session-Token` |
| `/yemot/*` | שלוחות ימות המשיח — פרוטוקול טקסט של ymgateway |
| `/cron/*` | Cloud Scheduler — אימות ב-`Authorization: Bearer $CRON_SECRET` |

### הגדרת השלוחה בימות המשיח

בממשק הניהול של ימות, בשלוחה הרצויה:

```ini
type=api
api_link=https://bait-app-602446976212.europe-west1.run.app/yemot
api_add_0=secret=<YEMOT_API_SECRET>
api_phone_send=yes
api_call_id_send=yes
api_did_send=yes
api_wait_answer_music_on_hold=yes
say_api_answer=no
api_log=yes
api_end_goto=/
```

- הסוד עובר ב-`api_add_0` ולא בתוך `api_link`. ימות מצרפת את הפרמטרים שלה
  בסימן שאלה נוסף במקום ב-`&`, ולכן query string ב-`api_link` מגיע מעוות
  (`secret=<הסוד>?ApiCallId=...`). השרת חוסם זאת ממילא, אבל ההגדרה הנכונה
  היא `api_add_0`.
- `api_phone_send=yes` הכרחי — בלי מספר המתקשרת אין זיהוי בכלל.
- `say_api_answer` חייב להיות `no`, אחרת ימות תקריא את הפקודות עצמן במקום
  לבצע אותן. שווה להדליק זמנית רק לדיבוג.
- נקודה היא מפריד בין הודעות, ולכן `logic/yemot.py` מסיר אותה ואת שאר
  התווים האסורים מכל טקסט TTS.
- בכל שדה ב-`read=` נשלח ערך מפורש. שדה ריק באמצע נקרא כאפס, ו-`sec_wait`
  ריק פירושו שהשיחה תתנתק מיד אחרי ההודעה.
- לאבחון: `Log/LogApi.ymgr` בספריית ימות מציג כל בקשה ותשובה, כאשר `=`
  מוצג כ-`^`, `&` כ-`*` ו-`,` כ-`>`.

**הזרימה ליניארית בכוונה — כל ענף מסתיים בניתוק ולא בחזרה לתפריט.** ימות
אינה דורסת ערך שכבר נאסף בשיחה: קריאה חוזרת עם `re_enter` מוסיפה עותק נוסף,
והישן ממשיך להגיע בכל בקשה. ענף שמחזיר את המתקשרת לתפריט נכנס לכן ללולאה
אינסופית שרצה בלי המתנה להקשה. `test_yemot.py` כולל בדיקת רגרסיה שמוודאת
שאף ענף אינו מחזיר `read` על `menu`.

ימות מזהה את המתקשרת לפי `ApiPhone`. מספר שרשום כ-`phone` או כ-`phone_husband`
מזדהה בקוד האישי ומקבל תפריט: דיווח ראייה חדשה, ימי פרישה קרובים, פרטי
הראייה האחרונה, תזכורות קרובות, הוספת תזכורת, והגדרות (מנהגים, ימי ספירה,
שעות תזכורת, ושינוי הקוד של המספר שממנו התקשרו).

כותרת תזכורת נבחרת מרשימה קבועה ולא מוקלדת, כי אין דרך אמינה להזין טקסט
עברי מלוח המקשים. להזנה חופשית יידרש מצב `stt` או הקלטה, ששניהם דורשים
הגדרה נוספת בצד ימות.

**ערך שנקרא עם `typing_playback_mode` חוזר מפורמט ולא כספרות גולמיות** —
שעה חוזרת כ-`10-10` ותאריך כ-`01-01-2026`. `_digits()` מסנן כל תו שאינו
ספרה לפני הפענוח.

מספר שאינו מוכר מקבל מסלול הרשמה — בוחר קוד אישי, מקיש אותו פעמיים, והחשבון
נוצר **לא מאושר**. עד שהמנהל יאשר אותו במסך `/admin`, כל שיחה מהמספר הזה
עונה "החשבון שלך ממתין לאישור המנהל" בלי לבקש קוד. הרשמה טלפונית לעולם אינה
מעניקה הרשאות ניהול, כי מזהה מתקשר ניתן לזיוף.

### קודים לשני המספרים

לכל חשבון יש שני מספרים ושני קודים: `pin_hash` לאישה ו-`pin_hash_husband`
לבעל. כל עוד לא נקבע קוד נפרד לבעל, שני המספרים נכנסים עם הקוד המשותף — כך
משתמשים קיימים אינם ננעלים בחוץ. `check_pin_for(phone, pin)` בוחר את הקוד
לפי המספר שממנו נכנסו, ומשמש באתר, ב-API וב-`/yemot` כאחד. שינוי הקודים
נעשה במסך ההגדרות, ואפשר לבטל שם את הקוד הנפרד ולחזור לקוד משותף.

בדיקות מקומיות:

```bash
python test_yemot.py
```

```bash
python test_accounts.py
```
