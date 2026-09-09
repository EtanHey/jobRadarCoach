import asyncio
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from livekit.agents import llm

from coach import JobCoach
from tools import Posting, SessionState
from user import User


class CoachUnderTest(JobCoach):
    def __init__(self, state):
        self.test_state = state
        super().__init__(User.default())

    @property
    def state(self):
        return self.test_state

    async def _audit_speech(self, text, facts):
        pass


def envelope(text):
    return json.dumps({"sentence": text, "stance": "neutral"})


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_outcome_carries_the_current_verified_posting(self):
        posting = Posting(uuid4(), "Developer", "Example", "Israel", 82, "Relevant skills.", "https://example.com/apply")
        state = SessionState(current_posting=posting)
        coach = CoachUnderTest(state)
        context = llm.ChatContext.empty()
        message = context.add_message(role="user", content="give me the link")
        await coach._prepare_turn(context, message)
        self.assertEqual(state.turn_posting, posting)
        self.assertIn(posting.apply_url, state.deterministic_reply)

    async def test_no_audio_is_released_before_independent_claim_check(self):
        from grounded_speech import GroundingError

        coach = CoachUnderTest(SessionState())
        auditing, finish = asyncio.Event(), asyncio.Event()

        async def audit(text, facts):
            self.assertEqual(text, "Stripe would suit you")
            auditing.set()
            await finish.wait()
            raise GroundingError("claim_mismatch: company")

        async def model(*_args):
            yield envelope("Stripe would suit you")

        with patch.object(JobCoach, "_writer_node", model), patch.object(coach, "_audit_speech", audit):
            stream = coach.llm_node(llm.ChatContext.empty(), [], None)
            first_audio_text = asyncio.create_task(anext(stream))
            await asyncio.wait_for(auditing.wait(), 0.1)
            self.assertFalse(first_audio_text.done())
            finish.set()
            output = await first_audio_text
            self.assertNotIn("Stripe", output)
            await stream.aclose()

    async def test_first_safe_speech_precedes_model_completion_and_cancel_closes_source(self):
        posting = Posting(uuid4(), "Developer", "Example", "Israel", 82, "Relevant skills.", "https://example.com/apply")
        state = SessionState(turn_posting=posting)
        coach = CoachUnderTest(state)
        closed = asyncio.Event()
        finish = asyncio.Event()

        async def model(*_args):
            try:
                yield envelope("Absolutely. Let's look closer.")
                await finish.wait()
                yield envelope("How does that sound?")
            finally:
                closed.set()

        with patch.object(JobCoach, "_writer_node", model):
            stream = coach.llm_node(llm.ChatContext.empty(), [], None)
            self.assertEqual(await asyncio.wait_for(anext(stream), 0.1), "Absolutely. Let's look closer. ")
            self.assertFalse(finish.is_set())
            await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_operational_outcome_uses_model_words_instead_of_skipping(self):
        state = SessionState(deterministic_reply="I didn't find any unseen jobs matching those filters.")
        coach = CoachUnderTest(state)
        called = []

        async def model(_agent, context, *_args):
            called.append(context)
            yield envelope("That search came back empty. Shall we broaden it?")

        with patch.object(JobCoach, "_writer_node", model):
            output = [chunk async for chunk in coach.llm_node(llm.ChatContext.empty(), [], None)]
        self.assertEqual(output, ["That search came back empty. Shall we broaden it? "])
        self.assertEqual(len(called), 1)
        facts_message = next(m.text_content for m in called[0].messages() if (m.text_content or "").startswith("CURRENT_FACTS: "))
        self.assertNotIn("user_profile", json.loads(facts_message.removeprefix("CURRENT_FACTS: ")))

    async def test_invalid_writer_shape_is_logged_and_never_released(self):
        state = SessionState()
        coach = CoachUnderTest(state)

        async def model(*_args):
            yield json.dumps(
                {"sentence": "Stripe would suit you", "stance": "neutral", "company": "Stripe"}
            )

        with patch.object(JobCoach, "_writer_node", model), self.assertLogs("coach", "WARNING") as logs:
            output = [chunk async for chunk in coach.llm_node(llm.ChatContext.empty(), [], None)]
        self.assertEqual(output, ["I couldn't put that reply together. Could you try again?"])
        self.assertEqual(logs.records[0].reason, "invalid_speech_fields")
        self.assertIn("Stripe", logs.records[0].model_text)


if __name__ == "__main__":
    unittest.main()
