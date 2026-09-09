import json
import unittest

from grounded_speech import GroundingError, SentenceDecoder, render_sentence

FACTS = {"title": "Backend Developer", "company": "Acme", "location": "Tel Aviv", "score": "82", "reasons": "Your Python experience matches the listed stack.", "apply_url": "https://example.com/jobs/123"}

def envelope(text, stance="neutral"):
    return {"parts": [{"text": text}], "stance": stance}

class GroundedSpeechTests(unittest.TestCase):
    def test_natural_wording_has_no_required_phrase_or_starter(self):
        for text in ("Absolutely.", "Honestly, that sounds frustrating.", "Maybe we should look closer?", "I see why that part bothers you."):
            self.assertEqual(render_sentence(envelope(text), FACTS).text, text)

    def test_code_renders_facts_and_exact_reason_quotes(self):
        payload = {"parts": [{"text": "I'd look at "}, {"fact": "title"}, {"text": " at "}, {"fact": "company"}, {"text": ". Your "}, {"fact": "reasons", "quote": "Python"}, {"text": " experience looks relevant."}], "stance": "recommend"}
        self.assertEqual(render_sentence(payload, FACTS).text, "I'd look at Backend Developer at Acme. Your Python experience looks relevant.")

    def test_invented_facts_and_quotes_cannot_be_rendered(self):
        for part in ({"fact": "other_company"}, {"fact": "company", "quote": "Stripe"}, {"fact": "score", "quote": "91"}, {"fact": "apply_url", "quote": "https://invented.example"}, {"fact": "salary"}, {"company": "Stripe"}):
            with self.subTest(part=part), self.assertRaises(GroundingError):
                render_sentence({"parts": [part], "stance": "neutral"}, FACTS)

    def test_url_or_score_split_between_text_parts_is_rejected(self):
        for fragments in (("https://invent", "ed.example"), ("The score is ", "91")):
            with self.subTest(fragments=fragments), self.assertRaises(GroundingError):
                render_sentence({"parts": [{"text": x} for x in fragments], "stance": "neutral"}, FACTS)

    def test_missing_posting_and_wrong_score_band_fail(self):
        for facts, payload in (({}, {"parts": [{"fact": "company"}], "stance": "neutral"}), ({**FACTS, "score": "65"}, envelope("I recommend applying.", "recommend")), ({**FACTS, "score": "35"}, envelope("A weaker option.", "weak_option"))):
            with self.subTest(payload=payload), self.assertRaises(GroundingError):
                render_sentence(payload, facts)

    def test_first_envelope_is_available_before_response_end(self):
        first = json.dumps(envelope("How does that sound?"))
        decoder = SentenceDecoder()
        self.assertEqual(decoder.push(first[:15]), [])
        self.assertEqual(decoder.push(first[15:]), [envelope("How does that sound?")])
        self.assertEqual(decoder.push("\n" + json.dumps(envelope("We can look closer."))), [envelope("We can look closer.")])
        decoder.finish()

    def test_malformed_and_unbounded_output_fail(self):
        for output in ('```json', '{"parts":', 'x' * 4097):
            with self.subTest(output=output[:30]), self.assertRaises(GroundingError):
                decoder = SentenceDecoder()
                decoder.push(output)
                decoder.finish()
        with self.assertRaises(GroundingError):
            render_sentence(envelope("x" * 701), FACTS)

if __name__ == "__main__":
    unittest.main()
