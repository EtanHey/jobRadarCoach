import unittest

from intent import IntentActionConflict, IntentError, fast_intent, validate_intent


class IntentTests(unittest.TestCase):
    def test_non_search_filters_have_a_typed_conflict(self):
        with self.assertRaises(IntentActionConflict):
            validate_intent(
                {"action": "discuss", "filters": {"remote": True}, "more_options": False},
                "Would remote work be good for me?",
            )

    def test_bus_requests_keep_location_without_quantifier_query(self):
        for text in (
            "Find me some jobs in Israel",
            "Can you find me any jobs in Israel?",
            "I want something in Israel",
            "No, but I said that I wanted something in Israel.",
            "Show me a few good roles in Israel please",
        ):
            with self.subTest(text=text):
                result = fast_intent(text)
                self.assertEqual(result.action, "search")
                self.assertEqual(result.filters, {"location": "Israel"})

    def test_explicit_constraints_and_company_survive(self):
        result = fast_intent("Find me a senior remote Python role in Israel with a score above 70.")
        self.assertEqual(result.filters, {
            "location": "Israel", "seniority": "senior", "remote": True,
            "query": "Python", "min_score": 70,
        })
        self.assertEqual(fast_intent("Find me jobs at Acme").filters, {"query": "Acme"})

    def test_more_is_explicit_not_a_word_inside_a_discussion(self):
        self.assertEqual(fast_intent("next one").action, "next")
        self.assertFalse(fast_intent("next one").more_options)
        self.assertTrue(fast_intent("show me more options").more_options)
        self.assertIsNone(fast_intent("Tell me more about why this is a match"))
        self.assertIsNone(fast_intent("Next year I might want to move"))
        self.assertIsNone(fast_intent("Why is the Israel location good for me?"))

    def test_model_cannot_invent_constraints(self):
        for filters in ({"location": "Israel"}, {"query": "Python"}, {"min_score": 90}, {"remote": True}):
            with self.subTest(filters=filters), self.assertRaises(IntentError):
                validate_intent({"action": "search", "filters": filters, "more_options": False}, "find jobs")

    def test_filler_from_model_is_dropped_without_losing_real_filter(self):
        result = validate_intent({"action": "search", "filters": {"query": "some", "location": "Israel"}, "more_options": False}, "find me some jobs in Israel")
        self.assertEqual(result.filters, {"location": "Israel"})

    def test_literal_query_is_not_enough_without_a_subject(self):
        for query in ("some", "any", "something", "a few", "more", "new", "good", "please"):
            result = validate_intent({"action": "search", "filters": {"query": query}, "more_options": False}, f"find me {query} jobs")
            self.assertEqual(result.filters, {})

    def test_invalid_model_shapes_and_more_permissions_fail(self):
        for payload in (
            {"action": "delete", "filters": {}, "more_options": False},
            {"action": "search", "filters": {"salary": 100}, "more_options": False},
            {"action": "search", "filters": {"min_score": True}, "more_options": False},
            {"action": "next", "filters": {}, "more_options": True},
        ):
            with self.subTest(payload=payload), self.assertRaises(IntentError):
                validate_intent(payload, "next")


if __name__ == "__main__":
    unittest.main()
