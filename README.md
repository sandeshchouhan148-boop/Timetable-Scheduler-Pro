# Timetable Scheduler Pro — hosted web demo

**Live demo:** <https://timetable-scheduler-pro.onrender.com>

A browser version of the Timetable Scheduler Pro desktop app. It includes the
dashboard, asset management, teacher expertise, timetable generation and
history, workload analytics, feedback, backup, and assistant. The demo uses
fictional sample data and a separate SQLite database; it never opens or uploads
the desktop app's database.

## Hosted demo

The app is deployed on Render from this repository using `render.yaml`.
Sign in with:

- **Username:** `admin`
- **Password:** `admin123`

This password is public by design for the fictional-data demo. Anyone can sign
in and change the shared sample data; do not enter real school information.

The web process binds to Render's assigned port and `0.0.0.0`. The server
requires the deployment secrets at startup, uses signed `HttpOnly`,
`SameSite=Lax`, `Secure` session cookies, checks request origins on changes,
and limits failed sign-in attempts. The demo is one shared account and one
shared dataset: only use fictional data.

### Free-service data limits

The included Render service uses its free plan and a local SQLite database.
Render's free filesystem is ephemeral: sample or edited timetable data may be
reset after a redeploy, restart, or instance replacement. This is suitable for
a shareable demo, not real school records or reliable long-term storage. For
persistent multi-user data, replace SQLite with a managed database and add
proper per-user accounts before using real information. Do not enable paid
resources unless you choose them in Render.

## Run the hosted version locally

On Windows, run `run-local.bat`. It asks for a local demo password and creates
a random session secret for that launch. It stores its isolated database in
this folder's ignored `data` directory, not in the desktop app's database.
Keep the terminal open while using `http://127.0.0.1:8000`.

## AI and privacy

The assistant uses an offline helper by default. Cloud AI is opt-in; only set
`TIMETABLE_ENABLE_CLOUD_AI=1` and the corresponding provider API key as Render
environment secrets if you want assistant prompts and demo timetable context
sent to that provider. Never put AI API keys or database files in GitHub.

WhatsApp and email sending remain disabled in the browser version so a public
demo cannot accidentally send real or billable messages. Microphone input
depends on browser support and permission.
