import json
import unittest

from claim_audit import validate_audit
from grounded_speech import GroundingError, SentenceDecoder, render_sentence

FACTS = {
    "title": "Backend Developer",
    "company": "Acme",
    "location": "Tel Aviv",
    "score": "82",
    "reasons": "Your 3.7 years of Python experience match the listed stack.",
    "apply_url": "https://example.com/jobs/123",
}

def envelope(text, stance="neutral"):
    return {"sentence": text, "stance": stance}

class GroundedSpeechTests(unittest.TestCase):
    def test_natural_wording_has_no_required_phrase_or_starter(self):
        for text in ("Absolutely.", "Honestly, that sounds frustrating.", "Maybe we should look closer?", "I see why that part bothers you."):
            self.assertEqual(render_sentence(envelope(text), FACTS).text, text)

    def test_qa028_natural_prose_has_no_joined_duplicate_facts_and_is_audited(self):
        facts = {
            **FACTS,
            "title": "Artificial Intelligence & Machine Learning Engineer",
            "company": "Sandisk",
            "location": "Lev Yatir, South District, Israel",
        }
        text = (
            "Sandisk's Artificial Intelligence & Machine Learning Engineer role in "
            "Lev Yatir, South District, Israel looks promising because your 3.7 years "
            "of experience align with its work."
        )
        speech = render_sentence(envelope(text, "recommend"), facts)
        validate_audit(
            {
                "claims": [
                    {"field": "company", "value": facts["company"]},
                    {"field": "title", "value": facts["title"]},
                    {"field": "location", "value": facts["location"]},
                ],
                "stance": "recommend",
                "unsupported": [],
            },
            facts,
            text,
        )
        self.assertEqual(speech.text, text)
        self.assertEqual(speech.text.count(facts["title"]), 1)
        self.assertEqual(speech.text.count(facts["company"]), 1)
        self.assertNotIn("EngineerSandisk", speech.text)

    def test_exact_url_and_verified_reason_number_are_allowed(self):
        text = "Your 3.7 years fit this role. Apply at https://example.com/jobs/123."
        self.assertEqual(render_sentence(envelope(text), FACTS).text, text)

    def test_numbers_in_verified_identity_fields_are_allowed(self):
        facts = {
            **FACTS,
            "title": "Engineer Level 2",
            "company": "Studio 54",
            "location": "District 7",
        }
        text = "Studio 54's Engineer Level 2 role is in District 7."
        self.assertEqual(render_sentence(envelope(text), facts).text, text)

    def test_invented_url_and_number_are_rejected(self):
        for text, facts, reason in (
            ("Apply at https://invented.example/jobs/123.", FACTS, "unsupported_url"),
            ("The score is 91.", FACTS, "unsupported_number"),
            (
                "Reference 42 looks relevant.",
                {**FACTS, "reasons": "See https://evidence.example/item/42"},
                "unsupported_number",
            ),
            (
                "Reference 99 looks relevant.",
                {**FACTS, "id": "posting-99"},
                "unsupported_number",
            ),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(GroundingError, reason):
                render_sentence(envelope(text), facts)

    def test_missing_posting_and_wrong_score_band_fail(self):
        for facts, payload in (({**FACTS, "score": "65"}, envelope("I recommend applying.", "recommend")), ({**FACTS, "score": "35"}, envelope("A weaker option.", "weak_option"))):
            with self.subTest(payload=payload), self.assertRaises(GroundingError):
                render_sentence(payload, facts)

    def test_first_envelope_is_available_before_response_end(self):
        first = json.dumps(envelope("How does that sound?"))
        decoder = SentenceDecoder()
        self.assertEqual(decoder.push(first[:15]), [])
        self.assertEqual(decoder.push(first[15:]), [envelope("How does that sound?")])
        decoder.finish()

    def test_second_valid_envelope_is_rejected_in_same_or_later_chunk(self):
        first = json.dumps(envelope("How does that sound?"))
        second = json.dumps(envelope("We can look closer."))

        with self.subTest(delivery="same chunk"):
            decoder = SentenceDecoder()
            with self.assertRaisesRegex(GroundingError, "too_many_speech_envelopes"):
                decoder.push(first + second)

        with self.subTest(delivery="later chunk"):
            decoder = SentenceDecoder()
            self.assertEqual(decoder.push(first), [envelope("How does that sound?")])
            with self.assertRaisesRegex(GroundingError, "too_many_speech_envelopes"):
                decoder.push(second)

    def test_malformed_and_unbounded_output_fail(self):
        for output in ('```json', '{"sentence":', 'x' * 4097):
            with self.subTest(output=output[:30]), self.assertRaises(GroundingError):
                decoder = SentenceDecoder()
                decoder.push(output)
                decoder.finish()
        with self.assertRaises(GroundingError):
            render_sentence(envelope("x" * 701), FACTS)

if __name__ == "__main__":
    unittest.main()
