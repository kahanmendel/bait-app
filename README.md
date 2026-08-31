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
api_link=https://bait-app-602446976212.europe-west1.run.app/yemot?secret=<YEMOT_API_SECRET>
```

ימות מזהה את המתקשרת לפי `ApiPhone`, ולכן המספר חייב להיות רשום אצלה כ-`phone`
או כ-`phone_husband`. אחרי הזדהות בקוד האישי נפתח תפריט:
דיווח ראייה חדשה, ימי פרישה קרובים, פרטי הראייה האחרונה, ותזכורות קרובות.

בדיקה מקומית של הזרימה במלואה:

```bash
python test_yemot.py
```
