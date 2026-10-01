import unittest
from datetime import datetime, timezone

from app.services.model_context import (
    EARLIER_LEFT_OUT,
    HISTORY_STEP,
    MAX_HISTORY,
    PHOTO_KEPT_FOR,
    PHOTO_SENT_EARLIER,
    assistant_instructions,
    history_start,
    model_messages,
    with_turn_context,
)

PHOTO = "data:image/png;base64,YQ=="


def conversation(count):
    """Alternating person/assistant messages, the person first."""
    return [{"sender": "user" if i % 2 == 0 else "bot", "text": f"m{i}"} for i in range(count)]


class InstructionsTests(unittest.TestCase):
    def test_the_assistant_prompt_its_purpose_and_app_notes_never_change_per_turn(self):
        bot = {"name": "Atlas", "role": "Research and writing", "system_prompt": "You are Atlas, a helpful AI assistant."}
        instructions = assistant_instructions(bot)
        self.assertTrue(instructions.startswith("You are Atlas, a helpful AI assistant."))
        self.assertIn("What you're for: Research and writing.", instructions)
        self.assertIn("Open Dots", instructions)
        self.assertNotIn(str(datetime.now().year), instructions)  # no clock up front
        self.assertEqual(instructions, assistant_instructions(dict(bot)))

    def test_a_role_already_in_the_prompt_is_not_repeated(self):
        bot = {"name": "Coder", "role": "Code review", "system_prompt": "You do code review for Dan."}
        self.assertNotIn("What you're for", assistant_instructions(bot))


class HistoryWindowTests(unittest.TestCase):
    def test_short_conversations_are_sent_whole(self):
        self.assertEqual(history_start(MAX_HISTORY), 0)

    def test_long_ones_move_their_start_in_steps(self):
        starts = {history_start(count) for count in range(MAX_HISTORY + 1, MAX_HISTORY + HISTORY_STEP)}
        self.assertEqual(starts, {HISTORY_STEP})
        self.assertEqual(history_start(MAX_HISTORY + HISTORY_STEP), 2 * HISTORY_STEP)
        for count in range(MAX_HISTORY + 1, 400):
            self.assertLessEqual(count - history_start(count), MAX_HISTORY)
            self.assertGreaterEqual(count - history_start(count), MAX_HISTORY - HISTORY_STEP)

    def test_a_cut_conversation_opens_with_the_person_and_says_so(self):
        messages = model_messages(conversation(MAX_HISTORY + 2))
        self.assertEqual(messages[0]["role"], "user")
        self.assertTrue(messages[0]["content"].startswith(EARLIER_LEFT_OUT))
        self.assertEqual(messages[-1]["content"], f"m{MAX_HISTORY + 1}")

    def test_failed_replies_and_other_items_stay_out(self):
        stored = [
            {"sender": "user", "text": "hi"},
            {"sender": "bot", "text": "error", "is_error": True},
            {"sender": "system", "text": "note"},
            {"sender": "user", "text": "again"},
        ]
        self.assertEqual([m["content"] for m in model_messages(stored)], ["hi", "again"])


class PhotoTests(unittest.TestCase):
    def test_only_the_newest_photo_is_sent_again(self):
        stored = [
            {"sender": "user", "text": "first photo", "image_url": PHOTO},
            {"sender": "bot", "text": "a cat"},
            {"sender": "user", "text": "", "image_url": PHOTO + "Zg=="},
            {"sender": "bot", "text": "a dog"},
            {"sender": "user", "text": "and its ears?"},
        ]
        messages = model_messages(stored)
        self.assertIsNone(messages[0]["image_url"])
        self.assertEqual(messages[0]["content"], f"first photo\n\n{PHOTO_SENT_EARLIER}")
        self.assertEqual(messages[2]["image_url"], PHOTO + "Zg==")


    def test_a_photo_stops_being_sent_after_a_few_more_messages(self):
        stored = [{"sender": "user", "text": "look", "image_url": PHOTO}, {"sender": "bot", "text": "a cat"}]
        for i in range(PHOTO_KEPT_FOR - 1):
            stored += [{"sender": "user", "text": f"q{i}"}, {"sender": "bot", "text": f"a{i}"}]
        self.assertEqual(model_messages(stored)[0]["image_url"], PHOTO)
        stored.append({"sender": "user", "text": "one more"})
        self.assertIsNone(model_messages(stored)[0]["image_url"])
        self.assertIn(PHOTO_SENT_EARLIER, model_messages(stored)[0]["content"])


class TurnContextTests(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 5, 17, tzinfo=timezone.utc)

    def test_the_time_and_an_action_result_go_at_the_end(self):
        messages = [{"role": "user", "content": "plan my week", "image_url": None}]
        result = with_turn_context(messages, self.NOW, "Action result (search.web): {}")
        self.assertTrue(result[-1]["content"].startswith("plan my week\n\n---\n"))
        self.assertIn("- Now: Thursday, 01 October 2026, 05:17 UTC", result[-1]["content"])
        self.assertIn("- Action result (search.web): {}", result[-1]["content"])
        self.assertEqual(messages[0]["content"], "plan my week")  # the stored conversation is untouched

    def test_nothing_is_added_when_the_person_did_not_speak_last(self):
        messages = [{"role": "assistant", "content": "hello", "image_url": None}]
        self.assertEqual(with_turn_context(messages, self.NOW), messages)


if __name__ == "__main__":
    unittest.main()
