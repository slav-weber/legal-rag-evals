"""The DeepSeek USER_DATA tripwire must catch a sentinel ANYWHERE in a
message (incl. tool_calls[].function.arguments), and fail-closed on non-text content.

    uv run python tests/test_user_data_tripwire.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import llm_client as L  # noqa: E402
from ml.llm_client import USER_DATA_SENTINEL, mark_user_data  # noqa: E402


def _guard(msgs):
    # _guard_deepseek needs a key to reach the tripwire branch; inject a fake one.
    with mock.patch.object(L, "_DEEPSEEK_API_KEY", "test-key"):
        L._guard_deepseek(msgs)


class Tripwire(unittest.TestCase):
    def test_1_content_string(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": mark_user_data("вул. Прикладна 1")}])

    def test_2_content_list_part(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user",
                     "content": [{"type": "text", "text": mark_user_data("pii")}]}])

    def test_3_tool_call_arguments(self):
        # The hole this closes: a sentinel inside tool_calls[].function.arguments (nested JSON).
        msg = {"role": "assistant", "content": None,
               "tool_calls": [{"id": "c1", "type": "function",
                               "function": {"name": "lookup",
                                            "arguments": '{"q":"' + USER_DATA_SENTINEL
                                            + 'pii' + USER_DATA_SENTINEL + '"}'}}]}
        with self.assertRaises(ValueError):
            _guard([msg])

    def test_4_top_level_string_field(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "tool", "content": "ok", "name": mark_user_data("nm")}])

    def test_5_deeply_nested(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "assistant", "content": "",
                     "meta": {"a": [{"b": mark_user_data("z")}]}}])

    def test_6_user_data_flag(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": "clean", "user_data": True}])

    def test_7_clean_message_allowed(self):
        # Public open data → must NOT raise.
        _guard([{"role": "user", "content": "Текст закону України (відкриті дані)."}])

    def test_8_non_text_content_fail_closed(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user",
                     "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}])

    # --- review probes (names keep the review's letters: B=bytes, C=set,
    #     D=dict-key, E=content-part sibling, G=object.__str__) ---
    def test_B_bytes_value_rejected(self):
        # probe B: bytes cannot be scanned → fail-closed reject, NOT a silent skip.
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": "ok", "blob": b"\x00\x01raw"}])

    def test_C_set_value_rejected(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": "ok", "tags": {"a", "b"}}])

    def test_D_sentinel_in_dict_key(self):
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": "ok", "meta": {mark_user_data("k"): "v"}}])

    def test_E_content_part_sibling_field(self):
        # a marker in a sibling field of a text part (beyond "text") must be caught.
        with self.assertRaises(ValueError):
            _guard([{"role": "user",
                     "content": [{"type": "text", "text": "clean", "note": mark_user_data("x")}]}])

    def test_clean_nested_allowed(self):
        # not a probe letter: a fully clean nested structure (safe scalars, no marker)
        # must NOT raise.
        _guard([{"role": "assistant", "content": "публічний текст",
                 "usage": {"tokens": 42, "ok": True, "ratio": 0.5, "note": None}}])

    def test_G_object_with_sentinel_str_rejected(self):
        # probe G: a custom object whose __str__ hides the sentinel must be REJECTED as
        # uninspectable — never str()'d-and-passed.
        class _Sneaky:
            def __str__(self):
                return mark_user_data("pii")
        with self.assertRaises(ValueError):
            _guard([{"role": "user", "content": "ok", "obj": _Sneaky()}])


class EntryPoints(unittest.TestCase):
    """The tripwire holds where the payload leaves, not only inside the guard. Every DeepSeek entry
    point (call_tool_deepseek on the generation path, and chat_deepseek) refuses a marked, flagged
    or uninspectable payload with ValueError, and the client never sees it: a guard that is tested
    only on its own can be wrapped, logged and skipped at the call site. The SDK client is replaced
    by a recorder; no request leaves the machine."""

    TOOL = {"name": "pravova_dovidka", "description": "",
            "parameters": {"type": "object", "properties": {"vysnovok": {"type": "string"}}}}

    def setUp(self):
        self.sent: list = []                    # the payloads that reached the client
        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=self._create)))
        for patcher in (mock.patch.object(L, "_DEEPSEEK_API_KEY", "test-key"),
                        mock.patch.object(L, "OpenAI", lambda **kw: client)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _create(self, **kw):
        self.sent.append(kw["messages"])
        call = SimpleNamespace(id="tc1", function=SimpleNamespace(arguments='{"vysnovok": "v"}'))
        return SimpleNamespace(
            id="rid", model="m",
            choices=[SimpleNamespace(message=SimpleNamespace(content="v", tool_calls=[call]),
                                     finish_reason="tool_calls")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2,
                                  prompt_cache_hit_tokens=0))

    def _entry_points(self, messages) -> dict:
        return {"call_tool_deepseek": lambda: L.call_tool_deepseek(messages, self.TOOL),
                "chat_deepseek": lambda: L.chat_deepseek(messages)}

    def _assert_refused(self, messages):
        for name, send in self._entry_points(messages).items():
            with self.subTest(entry_point=name):
                with self.assertRaises(ValueError):
                    send()
        self.assertEqual(self.sent, [])                 # nothing reached the client

    def test_marked_user_data_never_reaches_the_client(self):
        self._assert_refused([{"role": "system", "content": "Відповідай українською."},
                              {"role": "user", "content": mark_user_data("вул. Прикладна 1")}])

    def test_user_data_flag_never_reaches_the_client(self):
        self._assert_refused([{"role": "user", "content": "clean", "user_data": True}])

    def test_uninspectable_part_never_reaches_the_client(self):
        self._assert_refused([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:x"}}]}])

    def test_clean_open_data_reaches_the_client(self):
        # the control: the recorder is wired, so "nothing reached the client" above is not vacuous
        messages = [{"role": "user", "content": "Текст закону України (відкриті дані)."}]
        for send in self._entry_points(messages).values():
            send()
        self.assertEqual(self.sent, [messages, messages])


class WalkStrings(unittest.TestCase):
    def test_scans_keys_and_values(self):
        self.assertEqual(sorted(L._walk_strings({"a": "b", "c": ["d"]})), ["a", "b", "c", "d"])

    def test_safe_scalars_skipped(self):
        self.assertEqual(L._walk_strings({"n": 1, "f": 0.5, "b": True, "x": None}),
                         ["n", "f", "b", "x"])

    def test_uninspectable_raises(self):
        with self.assertRaises(ValueError):
            L._walk_strings({"blob": b"raw"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
