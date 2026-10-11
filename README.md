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

The assistant uses an offline timetable Q&A helper by default; it can answer
about teachers, subjects, classes, teacher expertise, and saved schedules. Full
open-ended AI is opt-in: set `TIMETABLE_ENABLE_CLOUD_AI=1` and the provider API
key (for example, `GROQ_API_KEY`) as Render environment secrets. Prompts and demo
timetable context are sent to that provider when enabled. Never put API keys or
database files in GitHub or the browser.

Choose **हिन्दी में जवाब** or **Answer in English** in the assistant to set both
the answer language and speech-recognition language. Speech input uses the
browser's speech-recognition service, not a server-side microphone package.
Open the demo over HTTPS, use a supported browser such as Chrome or Edge, and
allow microphone access in the site's browser settings. If speech recognition
is blocked or unavailable, type the question in the chat instead.

WhatsApp and email screens provide local-only previews in the browser version;
they do not collect credentials, save recipient details, or send real messages.
Live messaging is intentionally disabled so the public demo cannot accidentally
contact real recipients or incur charges. Microphone input depends on browser
support and permission.
