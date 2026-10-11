import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from ai_service import AIService


class OfflineAssistantTests(unittest.TestCase):
    def setUp(self):
        self.ai = AIService("offline", "", "", "")
        self.context = {
            "teachers": ["Asha Demo", "Kavita Rao"],
            "subjects": ["Mathematics", "Computer Science", "Science"],
            "classes": ["Class 9-A"],
            "classrooms": ["Room 101"],
            "labs": ["Science Lab"],
            "teacher_expertise": {
                "Asha Demo": ["Mathematics"],
                "Kavita Rao": ["Computer Science", "Science"],
            },
            "generated_timetable": {
                "Monday": {
                    "Class 9-A": {
                        "1": {
                            "subject": "Mathematics",
                            "teacher": "Asha Demo",
                            "room": "Room 101",
                        },
                        "2": {
                            "subject": "Science",
                            "teacher": "Kavita Rao",
                            "room": "Room 101",
                        },
                    },
                },
            },
        }

    def ask(self, prompt, language="en"):
        return self.ai.ask(prompt, self.context, language=language)

    def test_answers_teacher_expertise_and_subject_assignments(self):
        self.assertIn("Computer Science, Science", self.ask("what subjects does Kavita Rao teach?"))
        self.assertIn("Asha Demo", self.ask("who teaches Mathematics?"))

    def test_lists_and_counts_rooms_and_labs(self):
        self.assertIn("There are 2 rooms", self.ask("how many rooms?"))
        self.assertIn("Science Lab", self.ask("show all rooms"))

    def test_filters_timetable_by_period_and_room(self):
        answer = self.ask("show Class 9-A Monday period 2")
        self.assertIn("Science", answer)
        self.assertNotIn("Mathematics", answer)
        room_answer = self.ask("which classes use Room 101?")
        self.assertIn("Class 9-A", room_answer)

    def test_reports_current_timetable_workload(self):
        answer = self.ask("teacher workload")
        self.assertIn("Asha Demo: 1", answer)
        self.assertIn("Kavita Rao: 1", answer)

    def test_returns_hindi_for_hindi_language_selection(self):
        self.assertIn("शिक्षक", self.ask("कितने शिक्षक हैं?", language="hi"))


class DemoDataTests(unittest.TestCase):
    def test_expanded_demo_data_migrates_once_and_asset_add_works(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "demo.sqlite3"
            with patch.object(server, "DATABASE", database):
                server.initialize_database()
                with server.open_database() as connection:
                    state = server.fetch_state(connection)
                    self.assertEqual(len(state["teachers"]), 6)
                    self.assertIn("Class 10-A", state["classes"])
                    self.assertIn("Computer Lab", state["labs"])

                    result = server.PreviewHandler.handle_post(
                        object.__new__(server.PreviewHandler),
                        connection,
                        "/api/assets",
                        {"category": "teachers", "name": "Test Teacher"},
                    )
                    self.assertTrue(result["ok"])
                    self.assertIn(
                        "Test Teacher",
                        [teacher["name"] for teacher in server.fetch_state(connection)["teachers"]],
                    )

                    connection.execute(
                        "UPDATE teachers SET is_deleted = 1 WHERE name = ?",
                        ("Kavita Rao",),
                    )
                    connection.commit()

                server.initialize_database()
                with server.open_database() as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT is_deleted FROM teachers WHERE name = ?",
                            ("Kavita Rao",),
                        ).fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM teachers WHERE name = ?",
                            ("Kavita Rao",),
                        ).fetchone()[0],
                        1,
                    )

    def test_asset_add_rejects_missing_category(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "demo.sqlite3"
            with patch.object(server, "DATABASE", database):
                server.initialize_database()
                with server.open_database() as connection:
                    with self.assertRaisesRegex(ValueError, "asset type"):
                        server.PreviewHandler.handle_post(
                            object.__new__(server.PreviewHandler),
                            connection,
                            "/api/assets",
                            {"name": "Missing Type"},
                        )


if __name__ == "__main__":
    unittest.main()
