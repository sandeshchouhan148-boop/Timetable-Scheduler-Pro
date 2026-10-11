"""Provider client and local timetable helpers for Timetable Scheduler Pro."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


REQUEST_TIMEOUT_SECONDS = 20
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class AIService:
    """Small OpenAI-compatible client configured entirely through the environment."""

    def __init__(self, provider: str, model: str, url: str, api_key: str) -> None:
        self.provider = provider
        self.model = model
        self.url = url
        self.api_key = api_key.strip()

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "AIService":
        env = os.environ if environ is None else environ
        provider = env.get("AI_PROVIDER", "groq").strip().casefold()
        if provider == "groq":
            return cls(
                provider="groq",
                model=env.get("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip(),
                url="https://api.groq.com/openai/v1/chat/completions",
                api_key=env.get("GROQ_API_KEY", ""),
            )
        if provider in {"nvidia", "nvidia-nim"}:
            return cls(
                provider="nvidia",
                model=env.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct").strip(),
                url=env.get(
                    "NVIDIA_BASE_URL",
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                ).strip(),
                api_key=env.get("NVIDIA_API_KEY", ""),
            )
        if provider in {"xai", "grok"}:
            return cls(
                provider="xai",
                model=env.get("XAI_MODEL", "grok-3-mini").strip(),
                url="https://api.x.ai/v1/chat/completions",
                api_key=env.get("XAI_API_KEY", ""),
            )
        if provider == "openai-compatible":
            base_url = env.get("AI_BASE_URL", "").strip().rstrip("/")
            if base_url and not base_url.endswith("/chat/completions"):
                base_url += "/chat/completions"
            return cls(
                provider=provider,
                model=env.get("AI_MODEL", "").strip(),
                url=base_url,
                api_key=env.get("AI_API_KEY", ""),
            )
        return cls(provider=provider, model="", url="", api_key="")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.url)

    def _offline_answer(self, prompt: str, context: dict) -> str:
        query = prompt.casefold()
        teachers = context.get("teachers", [])
        subjects = context.get("subjects", [])
        classes = context.get("classes", [])
        timetable = context.get("generated_timetable", {})

        if any(word in query for word in ("teacher", "teachers", "adhyapak", "शिक्षक")):
            return "Teachers: " + (", ".join(teachers) if teachers else "none added yet.")
        if any(word in query for word in ("subject", "subjects", "vishay", "विषय")):
            return "Subjects: " + (", ".join(subjects) if subjects else "none added yet.")
        if any(word in query for word in ("class", "classes", "kaksha", "कक्षा")):
            return "Classes: " + (", ".join(classes) if classes else "none added yet.")

        requested_class = next(
            (name for name in classes if name.casefold() in query), None
        )
        requested_teacher = next(
            (name for name in teachers if name.casefold() in query), None
        )
        schedule_query = any(
            word in query
            for word in ("schedule", "timetable", "routine", "time table", "samay", "period")
        )
        if schedule_query or requested_class or requested_teacher:
            entries = []
            for day, day_data in timetable.items():
                for class_name, periods in day_data.items():
                    if requested_class and class_name.casefold() != requested_class.casefold():
                        continue
                    for period, entry in periods.items():
                        if (
                            requested_teacher
                            and entry.get("teacher", "").casefold()
                            != requested_teacher.casefold()
                        ):
                            continue
                        entries.append(
                            f"{day}, {class_name}, period {period}: "
                            f"{entry.get('subject', '')} — {entry.get('teacher', '')} "
                            f"({entry.get('room', '')})"
                        )
            if entries:
                return "Offline timetable results:\n" + "\n".join(entries[:50])
            return (
                "No matching timetable entries found. Generate a timetable or try "
                "a class/teacher name."
            )
        return (
            "Offline timetable helper: ask to list teachers, subjects, classes, "
            "or a class/teacher schedule. To generate a schedule, ask 'generate "
            "timetable' and provide the days/periods in the Generate Schedule screen."
        )

    def ask(self, prompt: str, context: dict) -> str:
        prompt = prompt.strip()
        if not prompt:
            return "AI Error: prompt is empty."
        offline = self._offline_answer(prompt, context)
        if not self.configured:
            if self.provider not in {"groq", "nvidia", "xai", "openai-compatible"}:
                error = f"AI Error: unsupported AI_PROVIDER '{self.provider}'."
            elif not self.api_key:
                error = f"AI Error: {self.provider} API key is not configured."
            else:
                error = f"AI Error: {self.provider} model or endpoint is not configured."
            return error + "\n\n" + offline

        system = (
            "You are Scheduler Pro AI. Respond in the user's language "
            "(Hindi/English/Hinglish)."
        )
        if context:
            system += " Data: " + json.dumps(context, ensure_ascii=False, default=str)
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 600,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        request.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty assistant content")
            return content.strip()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:300]
            exc.close()
            if exc.code == 401:
                error = f"AI Error: {self.provider} rejected the API key (HTTP 401)."
            elif exc.code == 403 and (
                "1010" in details
                or "cloudflare" in (exc.headers.get("Server", "") if exc.headers else "").casefold()
            ):
                error = (
                    f"AI Error: {self.provider} request is blocked by Cloudflare "
                    "(HTTP 403, error 1010). It was not retried. Try another provider "
                    "or network."
                )
            elif exc.code == 403:
                error = f"AI Error: {self.provider} access denied (HTTP 403). {details}"
            elif exc.code == 404:
                error = (
                    f"AI Error: model/endpoint not found (HTTP 404). "
                    f"Check {self.provider.upper()}_MODEL and endpoint."
                )
            elif exc.code == 429:
                error = f"AI Error: {self.provider} rate limit (HTTP 429). Try later."
            else:
                error = f"AI Error: {self.provider} returned HTTP {exc.code}. {details}"
            return error + "\n\n" + offline
        except (urllib.error.URLError, TimeoutError) as exc:
            return (
                f"AI Error: could not reach {self.provider} within "
                f"{REQUEST_TIMEOUT_SECONDS} seconds: {exc}\n\n{offline}"
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            return f"AI Error: invalid {self.provider} response: {exc}\n\n{offline}"


def is_timetable_generation_request(prompt: str) -> bool:
    query = prompt.casefold()
    return any(
        phrase in query
        for phrase in (
            "generate timetable",
            "generate a timetable",
            "generate schedule",
            "generate a schedule",
            "create timetable",
            "create a timetable",
            "create schedule",
            "make timetable",
            "make a timetable",
            "make schedule",
            "timetable banao",
            "schedule banao",
            "routine banao",
            "timetable bana",
            "schedule bana",
        )
    )


def generate_clash_free_timetable(
    teachers: list[str],
    subjects: list[str],
    classes: list[str],
    expertise: dict[str, list[str]],
    classrooms: list[str],
    days: list[str],
    periods_per_day: int,
) -> dict:
    """Create a schedule with no teacher or room overlap in the same period."""
    if not teachers or not subjects or not classes:
        raise ValueError("Add at least one teacher, subject, and class first.")
    if not days or any(not day.strip() for day in days):
        raise ValueError("Provide at least one non-empty timetable day.")
    if periods_per_day < 1:
        raise ValueError("Periods per day must be at least 1.")
    if classrooms and len(classrooms) < len(classes):
        raise ValueError(
            "Not enough classrooms to schedule every class without a room clash."
        )
    if len(teachers) < len(classes):
        raise ValueError(
            "Not enough teachers to teach all classes simultaneously without clashes."
        )

    timetable: dict = {}
    teacher_load = {teacher: 0 for teacher in teachers}
    rooms = classrooms or ["TBD"] * len(classes)

    for day_index, day in enumerate(days):
        timetable[day] = {}
        for class_name in classes:
            timetable[day][class_name] = {}

        for period in range(1, periods_per_day + 1):
            period_offset = day_index * periods_per_day + period - 1
            ordered_classes = sorted(
                classes,
                key=lambda class_name: sum(
                    1
                    for teacher in teachers
                    for subject in subjects
                    if not expertise.get(teacher)
                    or subject in expertise[teacher]
                ),
            )
            used_teachers: set[str] = set()
            used_rooms: set[str] = set()
            assignments: dict[str, tuple[str, str, str]] = {}

            def assign(class_index: int) -> bool:
                if class_index == len(ordered_classes):
                    return True

                class_name = ordered_classes[class_index]
                subject_order = subjects[
                    period_offset % len(subjects):
                ] + subjects[: period_offset % len(subjects)]
                options = []
                for subject in subject_order:
                    eligible = [
                        teacher
                        for teacher in teachers
                        if (not expertise.get(teacher) or subject in expertise[teacher])
                        and teacher not in used_teachers
                    ]
                    eligible.sort(key=lambda teacher: teacher_load[teacher])
                    for teacher in eligible:
                        for room in rooms:
                            if room not in used_rooms:
                                options.append((subject, teacher, room))

                for subject, teacher, room in options:
                    used_teachers.add(teacher)
                    used_rooms.add(room)
                    assignments[class_name] = (subject, teacher, room)
                    if assign(class_index + 1):
                        return True
                    used_teachers.remove(teacher)
                    used_rooms.remove(room)
                    del assignments[class_name]
                return False

            if not assign(0):
                raise ValueError(
                    f"Could not create a clash-free schedule for {day}, "
                    f"period {period}. Check teacher subject expertise and available rooms."
                )

            for class_name, (subject, teacher, room) in assignments.items():
                teacher_load[teacher] += 1
                timetable[day][class_name][period] = {
                    "subject": subject,
                    "teacher": teacher,
                    "room": room,
                }
    return timetable
