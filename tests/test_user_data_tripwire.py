"""The DeepSeek USER_DATA tripwire must catch a sentinel ANYWHERE in a
message (incl. tool_calls[].function.arguments), and fail-closed on non-text content.

    uv run python tests/test_user_data_tripwire.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
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
