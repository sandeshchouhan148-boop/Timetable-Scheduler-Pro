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

    def _offline_answer(self, prompt: str, context: dict, language: str = "hi") -> str:
        in_hindi = language == "hi"
        query = prompt.casefold()
        teachers = context.get("teachers", [])
        subjects = context.get("subjects", [])
        classes = context.get("classes", [])
        timetable = context.get("generated_timetable", {})
        expertise = context.get("teacher_expertise", {})
        greeting = any(
            word in query.split()
            for word in ("hi", "hello", "hey", "namaste", "नमस्ते", "हाय")
        )
        if greeting:
            return (
                "नमस्ते! मैं इस डेमो के शिक्षक, विषय, कक्षाएँ और टाइमटेबल बता सकता हूँ। "
                "पूछें: “Mathematics कौन पढ़ाता है?” या “Class 9-A का Monday टाइमटेबल दिखाएँ।”"
                if in_hindi
                else "Hello! I can help with this demo's teachers, subjects, classes, "
                "and timetable. Try “who teaches Mathematics?” or “show Class 9-A "
                "timetable on Monday”."
            )

        list_intent = any(
            word in query
            for word in (
                "list", "show all", "show me", "kitne", "kitni", "कितने", "कितनी",
                "सूची", "दिखाओ", "बताओ", "सभी",
            )
        )
        teacher_query = any(
            word in query
            for word in (
                "teacher", "teachers", "teach", "who", "kaun",
                "adhyapak", "padhata", "padhati", "padhate", "शिक्षक", "शिक्षकों", "पढ़ाते",
            )
        )
        subject_query = any(word in query for word in ("subject", "subjects", "vishay", "विषय"))
        class_query = any(word in query for word in ("class", "classes", "kaksha", "कक्षा", "कक्षाएँ", "कक्षाएं"))

        if teacher_query and list_intent:
            names = ", ".join(teachers) if teachers else ("अभी कोई नहीं जोड़ा गया" if in_hindi else "none added yet")
            return ("शिक्षक: " if in_hindi else "Teachers: ") + names
        if subject_query and list_intent:
            names = ", ".join(subjects) if subjects else ("अभी कोई नहीं जोड़ा गया" if in_hindi else "none added yet")
            return ("विषय: " if in_hindi else "Subjects: ") + names
        if class_query and list_intent:
            names = ", ".join(classes) if classes else ("अभी कोई नहीं जोड़ा गया" if in_hindi else "none added yet")
            return ("कक्षाएँ: " if in_hindi else "Classes: ") + names
        matching_subjects = [
            subject for subject in subjects if subject.casefold() in query
        ]
        if teacher_query and matching_subjects:
            matched = matching_subjects[0]
            names = [
                name for name, assigned in expertise.items() if matched in assigned
            ]
            return (
                (
                    f"{matched} विषय पढ़ाने वाले शिक्षक हैं: {', '.join(names)}।"
                    if in_hindi
                    else f"{matched} is taught by {', '.join(names)}."
                )
                if names
                else (
                    f"{matched} विषय से अभी कोई शिक्षक जुड़ा नहीं है।"
                    if in_hindi
                    else f"No teacher is currently linked to {matched}."
                )
            )
        if any(word in query for word in ("how many", "count", "total", "कितने", "कितनी", "कितना")):
            if teacher_query:
                count = len(teachers)
                return f"शिक्षकों की संख्या {count} है।" if in_hindi else f"There {'is' if count == 1 else 'are'} {count} teacher{'s' if count != 1 else ''}."
            if subject_query:
                count = len(subjects)
                return f"विषयों की संख्या {count} है।" if in_hindi else f"There {'is' if count == 1 else 'are'} {count} subject{'s' if count != 1 else ''}."
            if class_query:
                count = len(classes)
                return f"कक्षाओं की संख्या {count} है।" if in_hindi else f"There {'is' if count == 1 else 'are'} {count} class{'es' if count != 1 else ''}."

        requested_class = next(
            (
                name
                for name in classes
                if name.casefold() in query
                or name.casefold().removeprefix("class ").strip() in query
            ),
            None,
        )
        requested_teacher = next(
            (name for name in teachers if name.casefold() in query), None
        )
        requested_day = next(
            (
                day
                for day in timetable
                if day.casefold() in query
            ),
            None,
        )
        schedule_query = any(
            word in query
            for word in ("schedule", "timetable", "routine", "time table", "samay", "period", "show")
        )
        if schedule_query or requested_class or requested_teacher:
            entries = []
            for day, day_data in timetable.items():
                if requested_day and day.casefold() != requested_day.casefold():
                    continue
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
                if in_hindi:
                    return "टाइमटेबल:\n" + "\n".join(
                        f"{day}, कक्षा {class_name}, पीरियड {period}: "
                        f"{entry.get('subject', '')} — शिक्षक {entry.get('teacher', '')} "
                        f"(कमरा {entry.get('room', '')})"
                        for day, day_data in timetable.items()
                        if not requested_day or day.casefold() == requested_day.casefold()
                        for class_name, periods in day_data.items()
                        if not requested_class or class_name.casefold() == requested_class.casefold()
                        for period, entry in periods.items()
                        if not requested_teacher or entry.get("teacher", "").casefold() == requested_teacher.casefold()
                    )
                return "Offline timetable results:\n" + "\n".join(entries[:50])
            return (
                "इस जानकारी से मेल खाता टाइमटेबल नहीं मिला। टाइमटेबल बनाएँ या कक्षा, "
                "शिक्षक और दिन का नाम जाँचें।"
                if in_hindi
                else "No matching timetable entries found for that filter. Generate a "
                "timetable or check the class, teacher, and day names."
            )
        return (
            "मैं शिक्षक, विषय, कक्षा और टाइमटेबल की जानकारी दे सकता हूँ। पूछें: "
            "“शिक्षकों की सूची”, “कितनी कक्षाएँ हैं?” या “Class 9-A का Monday टाइमटेबल दिखाएँ।”"
            if in_hindi
            else "I can answer questions about teachers, subjects, classes, and "
            "timetables. Try “list teachers”, “how many classes?”, or “show "
            "Class 9-A timetable Monday”."
        )

    def ask(self, prompt: str, context: dict, language: str = "hi") -> str:
        prompt = prompt.strip()
        if not prompt:
            return "AI Error: prompt is empty."
        if language not in {"hi", "en"}:
            raise ValueError("language must be 'hi' or 'en'")
        offline = self._offline_answer(prompt, context, language)
        if not self.configured:
            if self.provider == "offline":
                return offline
            if self.provider not in {"groq", "nvidia", "xai", "openai-compatible"}:
                error = f"AI Error: unsupported AI_PROVIDER '{self.provider}'."
            elif not self.api_key:
                error = f"AI Error: {self.provider} API key is not configured."
            else:
                error = f"AI Error: {self.provider} model or endpoint is not configured."
            return error + "\n\n" + offline

        response_language = "Hindi" if language == "hi" else "English"
        system = (
            "You are Scheduler Pro AI. Respond only in "
            f"{response_language}, regardless of the language used in the question. "
            "Preserve names and subject titles as written."
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
