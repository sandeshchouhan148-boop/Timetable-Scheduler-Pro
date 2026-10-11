"""Serve the authenticated Timetable Scheduler Pro web demo."""

from __future__ import annotations

import base64
import hmac
import json
import os
import smtplib
import sqlite3
import ssl
import sys
import time
import zipfile
from contextlib import closing
from email.message import EmailMessage
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ai_service import (
    AIService,
    generate_clash_free_timetable,
    is_timetable_generation_request,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "public"
DATABASE = Path(
    os.environ.get("TIMETABLE_DB_PATH", str(ROOT / "data" / "timetable.sqlite3"))
).resolve()
HOST = os.environ.get("TIMETABLE_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ADMIN_USERNAME = os.environ.get("TIMETABLE_ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("TIMETABLE_ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("TIMETABLE_SESSION_SECRET", "")
COOKIE_SECURE = os.environ.get("TIMETABLE_COOKIE_SECURE", "1").strip() != "0"
SESSION_LIFETIME_SECONDS = 12 * 60 * 60
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LIVE_MESSAGING_ENABLED = os.environ.get("TIMETABLE_ENABLE_LIVE_MESSAGING", "").strip().casefold() in {
    "1",
    "true",
    "yes",
}
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
ALLOWED_WHATSAPP_RECIPIENTS = {
    number.strip()
    for number in os.environ.get("TIMETABLE_ALLOWED_WHATSAPP_RECIPIENTS", "").split(",")
    if number.strip()
}
SMTP_HOST = os.environ.get("TIMETABLE_SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("TIMETABLE_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("TIMETABLE_SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("TIMETABLE_SMTP_PASSWORD", "")
ALLOWED_EMAIL_RECIPIENTS = {
    address.strip().casefold()
    for address in os.environ.get("TIMETABLE_ALLOWED_EMAIL_RECIPIENTS", "").split(",")
    if address.strip()
}
MESSAGE_SEND_ATTEMPTS: dict[str, list[float]] = {}
EXPORT_RATE_LIMIT: dict[str, list[float]] = {}
ASSET_TABLES = {
    "teachers": "teachers",
    "subjects": "subjects",
    "classes": "classes",
    "classrooms": "classrooms",
    "labs": "lab_rooms",
}
AI_ENABLED = os.environ.get("TIMETABLE_ENABLE_CLOUD_AI", "").strip().casefold() in {
    "1",
    "true",
    "yes",
}
AI = AIService.from_env() if AI_ENABLED else AIService.from_env({"AI_PROVIDER": "offline"})
EXPANDED_DEMO_DATA_KEY = "expanded_demo_data_v1"


def open_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(open_database()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'viewer'
            );
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                is_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                is_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                is_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                is_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS lab_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                is_deleted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS teacher_expertise (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher TEXT NOT NULL,
                subject TEXT NOT NULL,
                UNIQUE (teacher, subject)
            );
            CREATE TABLE IF NOT EXISTS timetable_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT,
                day TEXT,
                period INTEGER,
                subject TEXT,
                teacher TEXT,
                room TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher TEXT,
                message TEXT,
                sentiment TEXT,
                issue_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ai_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0:
            teachers = [
                ("Asha Demo", "asha@example.invalid", ""),
                ("Rohan Demo", "rohan@example.invalid", ""),
                ("Meera Demo", "meera@example.invalid", ""),
            ]
            connection.executemany(
                "INSERT INTO teachers (name, email, phone) VALUES (?, ?, ?)",
                teachers,
            )
            connection.executemany(
                "INSERT INTO subjects (name) VALUES (?)",
                [("Mathematics",), ("Science",), ("English",)],
            )
            connection.executemany(
                "INSERT INTO classes (name) VALUES (?)",
                [("Class 9-A",), ("Class 9-B",)],
            )
            connection.executemany(
                "INSERT INTO classrooms (name) VALUES (?)",
                [("Room 101",), ("Room 102",)],
            )
            connection.executemany(
                "INSERT INTO teacher_expertise (teacher, subject) VALUES (?, ?)",
                [
                    ("Asha Demo", "Mathematics"),
                    ("Asha Demo", "Science"),
                    ("Rohan Demo", "Mathematics"),
                    ("Rohan Demo", "English"),
                    ("Meera Demo", "Science"),
                    ("Meera Demo", "English"),
                ],
            )
            schedule = generate_clash_free_timetable(
                teachers=[teacher[0] for teacher in teachers],
                subjects=["Mathematics", "Science", "English"],
                classes=["Class 9-A", "Class 9-B"],
                expertise={
                    "Asha Demo": ["Mathematics", "Science"],
                    "Rohan Demo": ["Mathematics", "English"],
                    "Meera Demo": ["Science", "English"],
                },
                classrooms=["Room 101", "Room 102"],
                days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                periods_per_day=6,
            )
            rows = [
                (class_name, day, period, entry["subject"], entry["teacher"], entry["room"])
                for day, classes in schedule.items()
                for class_name, periods in classes.items()
                for period, entry in periods.items()
            ]
            connection.executemany(
                "INSERT INTO timetable_entries "
                "(class_name, day, period, subject, teacher, room) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        if not connection.execute(
            "SELECT 1 FROM app_metadata WHERE key = ?",
            (EXPANDED_DEMO_DATA_KEY,),
        ).fetchone():
            connection.executemany(
                "INSERT OR IGNORE INTO teachers (name, email, phone) VALUES (?, ?, ?)",
                [
                    ("Kavita Rao", "kavita@example.invalid", ""),
                    ("Arjun Mehta", "arjun@example.invalid", ""),
                    ("Nisha Kapoor", "nisha@example.invalid", ""),
                ],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO subjects (name) VALUES (?)",
                [
                    ("Computer Science",),
                    ("Hindi",),
                    ("Social Studies",),
                ],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO classes (name) VALUES (?)",
                [("Class 8-A",), ("Class 10-A",)],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO classrooms (name) VALUES (?)",
                [("Room 103",), ("Room 104",)],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO lab_rooms (name) VALUES (?)",
                [("Computer Lab",), ("Science Lab",)],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO teacher_expertise (teacher, subject) VALUES (?, ?)",
                [
                    ("Kavita Rao", "Mathematics"),
                    ("Kavita Rao", "Computer Science"),
                    ("Kavita Rao", "Hindi"),
                    ("Arjun Mehta", "Science"),
                    ("Arjun Mehta", "Social Studies"),
                    ("Arjun Mehta", "Computer Science"),
                    ("Nisha Kapoor", "English"),
                    ("Nisha Kapoor", "Hindi"),
                    ("Nisha Kapoor", "Social Studies"),
                ],
            )
            connection.execute(
                "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                (EXPANDED_DEMO_DATA_KEY, "1"),
            )
        connection.commit()


def fetch_state(connection: sqlite3.Connection) -> dict:
    def asset_names(table: str, deleted: bool = False) -> list[str]:
        rows = connection.execute(
            f"SELECT name FROM {table} WHERE is_deleted = ? ORDER BY id",
            (int(deleted),),
        )
        return [row["name"] for row in rows]

    teachers = [
        dict(row)
        for row in connection.execute(
            "SELECT name, email, phone FROM teachers "
            "WHERE is_deleted = 0 ORDER BY id"
        )
    ]
    expertise: dict[str, list[str]] = {}
    for row in connection.execute(
        "SELECT teacher, subject FROM teacher_expertise ORDER BY id"
    ):
        expertise.setdefault(row["teacher"], []).append(row["subject"])

    timetable: dict[str, dict[str, dict[int, dict[str, str]]]] = {}
    for row in connection.execute(
        "SELECT class_name, day, period, subject, teacher, room "
        "FROM timetable_entries ORDER BY day, class_name, period"
    ):
        timetable.setdefault(row["day"], {}).setdefault(row["class_name"], {})[
            row["period"]
        ] = {
            "subject": row["subject"],
            "teacher": row["teacher"],
            "room": row["room"],
        }

    history = [
        dict(row)
        for row in connection.execute(
            "SELECT class_name, day, period, subject, teacher, room, created_at "
            "FROM timetable_entries ORDER BY created_at DESC, id DESC LIMIT 500"
        )
    ]
    feedback = [
        dict(row)
        for row in connection.execute(
            "SELECT teacher, message, sentiment, issue_type, created_at "
            "FROM feedback ORDER BY created_at DESC, id DESC LIMIT 100"
        )
    ]
    ai_history = [
        dict(row)
        for row in connection.execute(
            "SELECT role, content FROM ai_history ORDER BY created_at ASC, id ASC LIMIT 40"
        )
    ]
    deleted = {
        category: asset_names(table, deleted=True)
        for category, table in ASSET_TABLES.items()
    }
    return {
        "teachers": teachers,
        "subjects": asset_names("subjects"),
        "classes": asset_names("classes"),
        "classrooms": asset_names("classrooms"),
        "labs": asset_names("lab_rooms"),
        "teacher_expertise": expertise,
        "generated_timetable": timetable,
        "days": list(timetable),
        "history": history,
        "feedback": feedback,
        "ai_history": ai_history,
        "deleted": deleted,
        "user": ADMIN_USERNAME,
        "role": "admin",
        "ai_provider": AI.provider,
        "ai_configured": AI.configured,
        "messaging": {
            "live_enabled": LIVE_MESSAGING_ENABLED,
            "whatsapp_ready": bool(
                LIVE_MESSAGING_ENABLED
                and TWILIO_ACCOUNT_SID
                and TWILIO_AUTH_TOKEN
                and TWILIO_WHATSAPP_FROM
                and ALLOWED_WHATSAPP_RECIPIENTS
            ),
            "email_ready": bool(
                LIVE_MESSAGING_ENABLED
                and SMTP_HOST
                and SMTP_USER
                and SMTP_PASSWORD
                and ALLOWED_EMAIL_RECIPIENTS
            ),
        },
    }


def excel_workbook(state: dict) -> bytes:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ElementTree.register_namespace("", namespace)
    ElementTree.register_namespace("r", relationships)
    sheet = ElementTree.Element(f"{{{namespace}}}worksheet")
    sheet_data = ElementTree.SubElement(sheet, f"{{{namespace}}}sheetData")
    headers = ("Day", "Class", "Period", "Subject", "Teacher", "Room")
    rows = [headers]
    for day, classes in state["generated_timetable"].items():
        for class_name, periods in classes.items():
            for period, item in periods.items():
                rows.append(
                    (day, class_name, period, item["subject"], item["teacher"], item["room"])
                )

    for row_number, values in enumerate(rows, start=1):
        row = ElementTree.SubElement(
            sheet_data, f"{{{namespace}}}row", {"r": str(row_number)}
        )
        for column_number, value in enumerate(values):
            column_name = chr(ord("A") + column_number)
            cell = ElementTree.SubElement(
                row,
                f"{{{namespace}}}c",
                {"r": f"{column_name}{row_number}"},
            )
            if row_number > 1 and column_number == 2:
                cell.set("t", "n")
                ElementTree.SubElement(cell, f"{{{namespace}}}v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                inline = ElementTree.SubElement(cell, f"{{{namespace}}}is")
                ElementTree.SubElement(inline, f"{{{namespace}}}t").text = str(value)

    workbook = ElementTree.Element(f"{{{namespace}}}workbook")
    sheets = ElementTree.SubElement(workbook, f"{{{namespace}}}sheets")
    ElementTree.SubElement(
        sheets,
        f"{{{namespace}}}sheet",
        {"name": "Timetable", "sheetId": "1", f"{{{relationships}}}id": "rId1"},
    )
    content_types = ElementTree.Element(
        "Types",
        xmlns="http://schemas.openxmlformats.org/package/2006/content-types",
    )
    ElementTree.SubElement(
        content_types,
        "Default",
        {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"},
    )
    ElementTree.SubElement(
        content_types,
        "Default",
        {"Extension": "xml", "ContentType": "application/xml"},
    )
    ElementTree.SubElement(
        content_types,
        "Override",
        {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"},
    )
    ElementTree.SubElement(
        content_types,
        "Override",
        {"PartName": "/xl/worksheets/sheet1.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"},
    )
    package_relationships = ElementTree.Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    ElementTree.SubElement(
        package_relationships,
        "Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "xl/workbook.xml",
        },
    )
    workbook_relationships = ElementTree.Element(
        "Relationships",
        xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
    )
    ElementTree.SubElement(
        workbook_relationships,
        "Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            "Target": "worksheets/sheet1.xml",
        },
    )

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ElementTree.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ElementTree.tostring(package_relationships, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/workbook.xml", ElementTree.tostring(workbook, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/_rels/workbook.xml.rels", ElementTree.tostring(workbook_relationships, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/worksheets/sheet1.xml", ElementTree.tostring(sheet, encoding="utf-8", xml_declaration=True))
    return output.getvalue()


def timetable_pdf(timetable: dict) -> bytes:
    lines = ["Timetable Scheduler Pro"]
    for day, classes in timetable.items():
        lines.append("")
        lines.append(day)
        for class_name, periods in classes.items():
            lines.append(f"Class: {class_name}")
            for period, item in periods.items():
                lines.append(
                    f"P{period}: {item['subject']} | {item['teacher']} | {item['room']}"
                )

    wrapped_lines = []
    for line in lines:
        while len(line) > 88:
            split_at = line.rfind(" ", 0, 88)
            if split_at < 1:
                split_at = 88
            wrapped_lines.append(line[:split_at])
            line = line[split_at:].lstrip()
        wrapped_lines.append(line)
    chunks = [wrapped_lines[index:index + 48] for index in range(0, len(wrapped_lines), 48)] or [["No timetable entries."]]

    objects: list[bytes] = []
    page_ids = []
    for page_index, chunk in enumerate(chunks):
        page_id = 4 + page_index * 2
        content_id = page_id + 1
        page_ids.append(page_id)
        commands = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for index, line in enumerate(chunk):
            if index:
                commands.append("T*")
            safe_line = line.encode("cp1252", "replace").decode("cp1252")
            escaped = safe_line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj")
        commands.append("ET")
        content = "\n".join(commands).encode("cp1252", "replace")
        objects.extend(
            [
                f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>\nendobj\n".encode("ascii"),
                f"{content_id} 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
                + content
                + b"\nendstream\nendobj\n",
            ]
        )
    pages = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    base_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Kids [{pages}] /Count {len(page_ids)} >>\nendobj\n".encode("ascii"),
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for entry in base_objects + objects:
        offsets.append(len(output))
        output.extend(entry)
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        if self.path.startswith("/api/"):
            print(f"{self.log_date_time_string()} API {self.command}")
            return
        super().log_message(format, *args)

    def respond_json(
        self,
        value: object,
        status: int = HTTPStatus.OK,
        cookie: str | None = None,
    ) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def make_session_cookie(self) -> str:
        expires = int(time.time()) + SESSION_LIFETIME_SECONDS
        signature = hmac.new(
            SESSION_SECRET.encode("utf-8"), str(expires).encode("ascii"), "sha256"
        ).hexdigest()
        cookie = f"{expires}:{signature}"
        attributes = [
            f"timetable_session={cookie}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={SESSION_LIFETIME_SECONDS}",
        ]
        if COOKIE_SECURE:
            attributes.append("Secure")
        return "; ".join(attributes)

    def clear_session_cookie(self) -> str:
        attributes = [
            "timetable_session=",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0",
        ]
        if COOKIE_SECURE:
            attributes.append("Secure")
        return "; ".join(attributes)

    def is_authenticated(self) -> bool:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies["timetable_session"].value
            expiry_text, signature = token.rsplit(":", 1)
            expires = int(expiry_text)
        except (KeyError, ValueError):
            return False
        if expires <= int(time.time()):
            return False
        expected = hmac.new(
            SESSION_SECRET.encode("utf-8"), expiry_text.encode("ascii"), "sha256"
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def check_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def require_authenticated(self) -> bool:
        if not self.is_authenticated():
            self.respond_json({"error": "Please sign in to continue."}, HTTPStatus.UNAUTHORIZED)
            return False
        if not self.check_origin():
            self.respond_json({"error": "Cross-origin request rejected."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if not 1 <= length <= 64_000:
            raise ValueError("Request body must be between 1 and 64 KB.")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/session":
            if not self.is_authenticated():
                self.respond_json({"authenticated": False}, HTTPStatus.UNAUTHORIZED)
                return
            self.respond_json({"authenticated": True, "username": ADMIN_USERNAME})
            return
        if path.startswith("/api/") and not self.require_authenticated():
            return
        if path == "/api/state":
            try:
                with closing(open_database()) as connection:
                    self.respond_json(fetch_state(connection))
            except sqlite3.Error as exc:
                print(f"Could not load the timetable database: {exc}", file=sys.stderr)
                self.respond_json(
                    {"error": "Could not read the timetable database."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if path == "/api/export.pdf":
            if not self.check_export_rate_limit():
                return
            try:
                with closing(open_database()) as connection:
                    timetable = fetch_state(connection)["generated_timetable"]
                pdf = timetable_pdf(timetable)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/pdf")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="timetable-scheduler.pdf"',
                )
                self.send_header("Content-Length", str(len(pdf)))
                self.end_headers()
                self.wfile.write(pdf)
            except (sqlite3.Error, OSError) as exc:
                print(f"Could not export timetable PDF: {exc}", file=sys.stderr)
                self.respond_json(
                    {"error": "Could not export the timetable PDF."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if path == "/api/backup":
            if not self.check_export_rate_limit():
                return
            try:
                with closing(open_database()) as connection:
                    backup = json.dumps(
                        fetch_state(connection), ensure_ascii=False, indent=2
                    ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="timetable-scheduler-backup.json"',
                )
                self.send_header("Content-Length", str(len(backup)))
                self.end_headers()
                self.wfile.write(backup)
            except sqlite3.Error as exc:
                print(f"Could not export timetable backup: {exc}", file=sys.stderr)
                self.respond_json(
                    {"error": "Could not export the timetable data."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if path == "/api/export.xlsx":
            if not self.check_export_rate_limit():
                return
            try:
                with closing(open_database()) as connection:
                    workbook = excel_workbook(fetch_state(connection))
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="timetable-scheduler.xlsx"',
                )
                self.send_header("Content-Length", str(len(workbook)))
                self.end_headers()
                self.wfile.write(workbook)
            except (sqlite3.Error, ElementTree.ParseError, OSError) as exc:
                print(f"Could not export timetable Excel workbook: {exc}", file=sys.stderr)
                self.respond_json(
                    {"error": "Could not export the timetable workbook."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if path.startswith("/api/"):
            self.respond_json({"error": "API route not found."}, HTTPStatus.NOT_FOUND)
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/logout":
            self.respond_json({"ok": True}, cookie=self.clear_session_cookie())
            return
        if path in {"/api/messaging/whatsapp", "/api/messaging/email"}:
            try:
                if not self.require_authenticated():
                    return
                data = self.read_json()
                if path.endswith("/whatsapp"):
                    self.send_whatsapp_message(data)
                else:
                    self.send_email_message(data)
            except ValueError as exc:
                self.respond_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        try:
            data = self.read_json()
            if path == "/api/login":
                self.login(data)
                return
            if not self.require_authenticated():
                return
            with closing(open_database()) as connection:
                with connection:
                    response = self.handle_post(
                        connection, path, data
                    )
            self.respond_json(response)
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError:
            self.respond_json({"error": "That item already exists."}, HTTPStatus.CONFLICT)
        except sqlite3.Error as exc:
            print(f"Could not save timetable data: {exc}", file=sys.stderr)
            self.respond_json(
                {"error": "Could not save the requested change."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def login(self, data: dict) -> None:
        if not self.check_origin():
            self.respond_json(
                {"error": "Cross-origin sign-in rejected."},
                HTTPStatus.FORBIDDEN,
            )
            return
        now = time.time()
        address = self.client_address[0]
        attempts = [
            timestamp
            for timestamp in LOGIN_ATTEMPTS.get(address, [])
            if now - timestamp < 300
        ]
        if len(attempts) >= 5:
            LOGIN_ATTEMPTS[address] = attempts
            self.respond_json(
                {"error": "Too many sign-in attempts. Wait five minutes and try again."},
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        username = data.get("username")
        password = data.get("password")
        valid_input = (
            isinstance(username, str)
            and isinstance(password, str)
            and len(username) <= 120
            and len(password) <= 256
        )
        valid_credentials = valid_input and hmac.compare_digest(
            username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8")
        ) and hmac.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
        if not valid_credentials:
            attempts.append(now)
            LOGIN_ATTEMPTS[address] = attempts
            self.respond_json(
                {"error": "Incorrect username or password."},
                HTTPStatus.UNAUTHORIZED,
            )
            return
        LOGIN_ATTEMPTS.pop(address, None)
        self.respond_json(
            {"ok": True, "username": ADMIN_USERNAME},
            cookie=self.make_session_cookie(),
        )

    def check_message_rate_limit(self) -> bool:
        now = time.time()
        address = self.client_address[0]
        attempts = [
            timestamp
            for timestamp in MESSAGE_SEND_ATTEMPTS.get(address, [])
            if now - timestamp < 300
        ]
        if len(attempts) >= 5:
            MESSAGE_SEND_ATTEMPTS[address] = attempts
            self.respond_json(
                {"error": "Too many message requests. Wait five minutes and try again."},
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return False
        attempts.append(now)
        MESSAGE_SEND_ATTEMPTS[address] = attempts
        return True

    def check_export_rate_limit(self) -> bool:
        now = time.time()
        address = self.client_address[0]
        attempts = [
            timestamp
            for timestamp in EXPORT_RATE_LIMIT.get(address, [])
            if now - timestamp < 60
        ]
        if len(attempts) >= 10:
            EXPORT_RATE_LIMIT[address] = attempts
            self.respond_json(
                {"error": "Too many exports. Wait one minute and try again."},
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return False
        attempts.append(now)
        EXPORT_RATE_LIMIT[address] = attempts
        return True

    def send_whatsapp_message(self, data: dict) -> None:
        if not LIVE_MESSAGING_ENABLED:
            self.respond_json(
                {"error": "Live WhatsApp sending is disabled. This demo only supports previews."},
                HTTPStatus.FORBIDDEN,
            )
            return
        if not self.check_message_rate_limit():
            return
        recipient = data.get("phone")
        message = data.get("message")
        if (
            not isinstance(recipient, str)
            or recipient not in ALLOWED_WHATSAPP_RECIPIENTS
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > 2000
        ):
            self.respond_json(
                {"error": "Use an authorized recipient and a message up to 2000 characters."},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
            self.respond_json(
                {"error": "WhatsApp sending is not configured on the server."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        form = urlencode(
            {
                "From": f"whatsapp:{TWILIO_WHATSAPP_FROM}",
                "To": f"whatsapp:{recipient}",
                "Body": message.strip(),
            }
        ).encode("utf-8")
        credentials = base64.b64encode(
            f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{quote(TWILIO_ACCOUNT_SID, safe='')}/Messages.json",
            data=form,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", "replace")
            print(f"Twilio request failed ({exc.code}): {detail}", file=sys.stderr)
            self.respond_json(
                {"error": "WhatsApp provider rejected the request. Check server credentials and recipient authorization."},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(f"Could not send WhatsApp message: {exc}", file=sys.stderr)
            self.respond_json(
                {"error": "Could not reach the WhatsApp provider."},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        self.respond_json({"ok": True, "message_id": result.get("sid", "")})

    def send_email_message(self, data: dict) -> None:
        if not LIVE_MESSAGING_ENABLED:
            self.respond_json(
                {"error": "Live email sending is disabled. This demo only supports previews."},
                HTTPStatus.FORBIDDEN,
            )
            return
        if not self.check_message_rate_limit():
            return
        recipient = data.get("email")
        subject = data.get("subject")
        message_text = data.get("message")
        if (
            not isinstance(recipient, str)
            or recipient.casefold() not in ALLOWED_EMAIL_RECIPIENTS
            or not isinstance(subject, str)
            or not subject.strip()
            or len(subject) > 200
            or any(character in subject for character in "\r\n")
            or not isinstance(message_text, str)
            or not message_text.strip()
            or len(message_text) > 2000
        ):
            self.respond_json(
                {"error": "Use an authorized email recipient, valid subject, and message up to 2000 characters."},
                HTTPStatus.BAD_REQUEST,
            )
            return
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            self.respond_json(
                {"error": "Email sending is not configured on the server."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        email = EmailMessage()
        email["From"] = SMTP_USER
        email["To"] = recipient
        email["Subject"] = subject.strip()
        email.set_content(message_text.strip())
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as client:
                client.starttls(context=ssl.create_default_context())
                client.login(SMTP_USER, SMTP_PASSWORD)
                client.send_message(email)
        except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
            print(f"Could not send email: {exc}", file=sys.stderr)
            self.respond_json(
                {"error": "Could not send email. Check server settings and provider status."},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        self.respond_json({"ok": True})

    def handle_post(self, connection: sqlite3.Connection, path: str, data: dict) -> dict:
        if path == "/api/assets":
            category = data.get("category")
            table = ASSET_TABLES.get(category)
            name = data.get("name")
            if not table or not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                raise ValueError("Choose an asset type and enter a name (max 120 characters).")
            name = name.strip()
            connection.execute(
                f"INSERT INTO {table} (name) VALUES (?) "
                "ON CONFLICT(name) DO UPDATE SET is_deleted = 0",
                (name,),
            )
            return {"ok": True}

        if path == "/api/teacher-details":
            name = data.get("name")
            email = data.get("email", "")
            phone = data.get("phone", "")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                raise ValueError("Teacher name is required (max 120 characters).")
            if not isinstance(email, str) or len(email) > 254:
                raise ValueError("Email must be 254 characters or fewer.")
            if not isinstance(phone, str) or len(phone) > 40:
                raise ValueError("Phone must be 40 characters or fewer.")
            connection.execute(
                "INSERT INTO teachers (name, email, phone) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET email = excluded.email, "
                "phone = excluded.phone, is_deleted = 0",
                (name.strip(), email.strip(), phone.strip()),
            )
            return {"ok": True}

        if path == "/api/expertise":
            teacher = data.get("teacher")
            subjects = data.get("subjects")
            if not isinstance(teacher, str) or not isinstance(subjects, list) or not subjects:
                raise ValueError("Choose a teacher and at least one subject.")
            if len(subjects) > 100 or any(not isinstance(subject, str) for subject in subjects):
                raise ValueError("Invalid subject selection.")
            if not connection.execute(
                "SELECT 1 FROM teachers WHERE name = ? AND is_deleted = 0",
                (teacher,),
            ).fetchone():
                raise ValueError("Choose an active teacher.")
            active_subjects = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM subjects WHERE is_deleted = 0"
                )
            }
            if not set(subjects) <= active_subjects:
                raise ValueError("Subject selection contains an inactive subject.")
            connection.execute("DELETE FROM teacher_expertise WHERE teacher = ?", (teacher,))
            connection.executemany(
                "INSERT INTO teacher_expertise (teacher, subject) VALUES (?, ?)",
                ((teacher, subject) for subject in dict.fromkeys(subjects)),
            )
            return {"ok": True}

        if path == "/api/timetable/generate":
            days = data.get("days")
            periods = data.get("periods_per_day")
            if not isinstance(days, list) or not 1 <= len(days) <= 7:
                raise ValueError("Enter 1–7 timetable days.")
            if any(not isinstance(day, str) or not day.strip() or len(day) > 30 for day in days):
                raise ValueError("Each day must be a valid name (max 30 characters).")
            if len(set(days)) != len(days):
                raise ValueError("Timetable days must be unique.")
            if not isinstance(periods, int) or isinstance(periods, bool) or not 1 <= periods <= 12:
                raise ValueError("Periods per day must be between 1 and 12.")
            current = fetch_state(connection)
            schedule = generate_clash_free_timetable(
                teachers=[teacher["name"] for teacher in current["teachers"]],
                subjects=current["subjects"],
                classes=current["classes"],
                expertise=current["teacher_expertise"],
                classrooms=current["classrooms"],
                days=[day.strip() for day in days],
                periods_per_day=periods,
            )
            rows = [
                (class_name, day, period, entry["subject"], entry["teacher"], entry["room"])
                for day, day_data in schedule.items()
                for class_name, periods_by_class in day_data.items()
                for period, entry in periods_by_class.items()
            ]
            connection.execute("DELETE FROM timetable_entries")
            connection.executemany(
                "INSERT INTO timetable_entries "
                "(class_name, day, period, subject, teacher, room) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            return {"ok": True, "days": len(schedule), "entries": len(rows)}

        if path == "/api/feedback":
            teacher = data.get("teacher", "")
            message = data.get("message")
            sentiment = data.get("sentiment", "neutral")
            issue_type = data.get("issue_type", "general")
            if not all(isinstance(value, str) for value in (teacher, message, sentiment, issue_type)):
                raise ValueError("Feedback fields must be text.")
            if not message.strip() or len(message) > 4000:
                raise ValueError("Feedback must be between 1 and 4000 characters.")
            if teacher and not connection.execute(
                "SELECT 1 FROM teachers WHERE name = ? AND is_deleted = 0",
                (teacher,),
            ).fetchone():
                raise ValueError("Choose an active teacher.")
            connection.execute(
                "INSERT INTO feedback (teacher, message, sentiment, issue_type) "
                "VALUES (?, ?, ?, ?)",
                (teacher, message.strip(), sentiment[:40], issue_type[:80]),
            )
            return {"ok": True}

        if path == "/api/assistant":
            prompt = data.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
                raise ValueError("Enter a question (max 2000 characters).")
            language = data.get("language", "hi")
            if not isinstance(language, str) or language not in {"hi", "en"}:
                raise ValueError("Choose Hindi or English for the assistant reply.")
            prompt = prompt.strip()
            state = fetch_state(connection)
            schedule = state["generated_timetable"]
            if is_timetable_generation_request(prompt):
                days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
                schedule = generate_clash_free_timetable(
                    teachers=[teacher["name"] for teacher in state["teachers"]],
                    subjects=state["subjects"],
                    classes=state["classes"],
                    expertise=state["teacher_expertise"],
                    classrooms=state["classrooms"],
                    days=days,
                    periods_per_day=8,
                )
                rows = [
                    (class_name, day, period, entry["subject"], entry["teacher"], entry["room"])
                    for day, day_data in schedule.items()
                    for class_name, periods_by_class in day_data.items()
                    for period, entry in periods_by_class.items()
                ]
                connection.execute("DELETE FROM timetable_entries")
                connection.executemany(
                    "INSERT INTO timetable_entries "
                    "(class_name, day, period, subject, teacher, room) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                answer = (
                    f"{len(days)} दिनों और रोज़ 8 पीरियड का टकराव-मुक्त टाइमटेबल बनाया और सेव किया। "
                    "किसी शिक्षक या कमरे का एक ही समय पर दो जगह उपयोग नहीं हुआ।"
                    if language == "hi"
                    else f"Generated and saved a clash-free timetable for {len(days)} days, "
                    "8 periods/day. No teacher or classroom is double-booked."
                )
            else:
                answer = AI.ask(
                    prompt,
                    {
                        "teachers": [teacher["name"] for teacher in state["teachers"]],
                        "subjects": state["subjects"],
                        "classes": state["classes"],
                        "classrooms": state["classrooms"],
                        "labs": state["labs"],
                        "teacher_expertise": state["teacher_expertise"],
                        "generated_timetable": schedule,
                    },
                    language=language,
                )
            connection.executemany(
                "INSERT INTO ai_history (role, content) VALUES (?, ?)",
                (("user", prompt), ("assistant", answer)),
            )
            return {
                "answer": answer,
                "ai_provider": AI.provider,
                "ai_configured": AI.configured,
            }

        raise ValueError("POST API route not found.")

    def do_DELETE(self) -> None:
        if not self.require_authenticated():
            return
        parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
        if len(parts) != 4 or parts[:2] != ["api", "assets"]:
            self.respond_json({"error": "Delete API route not found."}, HTTPStatus.NOT_FOUND)
            return
        category, path_name = parts[2], parts[3]
        name = self.headers.get("X-Asset-Name", "").strip()
        if name != path_name:
            self.respond_json({"error": "Asset name does not match the request path."}, HTTPStatus.BAD_REQUEST)
            return
        table = ASSET_TABLES.get(category)
        if not table or not name or len(name) > 120:
            self.respond_json({"error": "Choose a valid asset and name."}, HTTPStatus.BAD_REQUEST)
            return
        self.update_deleted_asset(table, name, True)

    def do_PATCH(self) -> None:
        if not self.require_authenticated():
            return
        parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
        if len(parts) != 4 or parts[:2] != ["api", "restore"]:
            self.respond_json({"error": "Restore API route not found."}, HTTPStatus.NOT_FOUND)
            return
        category, path_name = parts[2], parts[3]
        name = self.headers.get("X-Asset-Name", "").strip()
        if name != path_name:
            self.respond_json({"error": "Asset name does not match the request path."}, HTTPStatus.BAD_REQUEST)
            return
        table = ASSET_TABLES.get(category)
        if not table or not name or len(name) > 120:
            self.respond_json({"error": "Choose a valid asset and name."}, HTTPStatus.BAD_REQUEST)
            return
        self.update_deleted_asset(table, name, False)

    def update_deleted_asset(self, table: str, name: str, deleted: bool) -> None:
        try:
            with closing(open_database()) as connection:
                with connection:
                    cursor = connection.execute(
                        f"UPDATE {table} SET is_deleted = ? WHERE name = ? AND is_deleted = ?",
                        (int(deleted), name, int(not deleted)),
                    )
                    if cursor.rowcount == 0:
                        self.respond_json(
                            {"error": "Asset was not found in that state."},
                            HTTPStatus.NOT_FOUND,
                        )
                        return
            self.respond_json({"ok": True})
        except sqlite3.Error as exc:
            print(f"Could not update asset: {exc}", file=sys.stderr)
            self.respond_json(
                {"error": "Could not update the asset."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def main() -> None:
    if not WEB_ROOT.is_dir():
        raise SystemExit(f"Browser UI directory not found: {WEB_ROOT}")
    if not ADMIN_USERNAME or len(ADMIN_USERNAME) > 120:
        raise SystemExit("Set TIMETABLE_ADMIN_USERNAME to a non-empty value (max 120 characters).")
    if not 8 <= len(ADMIN_PASSWORD) <= 256:
        raise SystemExit("Set TIMETABLE_ADMIN_PASSWORD to 8–256 characters.")
    if len(SESSION_SECRET) < 32:
        raise SystemExit("Set TIMETABLE_SESSION_SECRET to a random secret of at least 32 characters.")
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), PreviewHandler)
    print("Starting the Timetable Scheduler Pro web app.")
    print(f"Database: {DATABASE}")
    print(f"Listening on port {PORT}.")
    if AI.configured:
        print(f"Assistant provider: {AI.provider}; API key remains on this computer.")
    else:
        print("Assistant provider: local offline helper.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local web app.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
