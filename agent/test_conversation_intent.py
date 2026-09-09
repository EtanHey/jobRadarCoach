import unittest
from uuid import uuid4

from livekit.agents import llm

from coach import JobCoach
from intent import Intent, fast_intent
from tools import JobFilters, NO_STRONG_JOBS, Posting, SessionState
from user import User


def posting(score=85):
    return Posting(uuid4(), "Developer", "Example", "Israel", score, "Relevant stack.", "https://example.com/apply")


class CoachUnderTest(JobCoach):
    def __init__(self, state, find_jobs=None):
        self.test_state = state
        super().__init__(User.default(), find_jobs=find_jobs)

    @property
    def state(self):
        return self.test_state

    async def _resolve_intent(self, text):
        return fast_intent(text) or Intent("discuss")


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def prepare(self, coach, text):
        context = llm.ChatContext.empty()
        message = context.add_message(role="user", content=text)
        await coach._prepare_turn(context, message)
        return context

    async def test_next_stops_before_medium_until_more_is_requested(self):
        first, second = posting(), posting(65)
        state = SessionState(candidates=(first, second))
        coach = CoachUnderTest(state)
        await self.prepare(coach, "yes")
        self.assertEqual(state.turn_posting, first)
        await self.prepare(coach, "next")
        self.assertEqual(state.deterministic_reply, NO_STRONG_JOBS)
        self.assertIsNone(state.turn_posting)
        await self.prepare(coach, "show me more options")
        self.assertEqual(state.turn_posting, second)

    async def test_discussion_does_not_advance_or_requery(self):
        first, second = posting(), posting()
        state = SessionState(candidates=(first, second))
        coach = CoachUnderTest(state)
        await self.prepare(coach, "yes")
        await self.prepare(coach, "Tell me more about why this is a fit")
        self.assertEqual(state.turn_posting, first)
        self.assertEqual(state.cursor, 0)

    async def test_zero_subject_widens_only_query_and_discloses_it(self):
        calls = []
        match = posting()

        async def find(filters):
            calls.append(filters)
            return [] if filters.query else [match]

        state = SessionState()
        context = await self.prepare(CoachUnderTest(state, find), "Find Python jobs in Israel")
        self.assertEqual(calls, [JobFilters(location="Israel", query="Python"), JobFilters(location="Israel")])
        self.assertTrue(state.search_widened)
        self.assertEqual(state.turn_posting, match)
        self.assertTrue(any("widened" in (m.text_content or "") for m in context.messages()))

    async def test_requery_cannot_repeat_a_delivered_posting(self):
        old, new = posting(), posting()
        state = SessionState(discussed_posting_ids={old.id})

        async def find(_filters):
            return [old, new]

        await self.prepare(CoachUnderTest(state, find), "Find some jobs in Israel")
        self.assertEqual(state.turn_posting, new)

    async def test_failed_search_cannot_resume_an_old_unfiltered_posting(self):
        old = posting()
        state = SessionState(candidates=(old,), current_posting=old, cursor=0)

        async def fail(_filters):
            raise RuntimeError("lookup unavailable")

        coach = CoachUnderTest(state, fail)
        await self.prepare(coach, "Find jobs in Israel")
        await self.prepare(coach, "Tell me more about it")
        self.assertIsNone(state.current_posting)
        self.assertIsNone(state.turn_posting)
        self.assertTrue(state.lookup_error)


if __name__ == "__main__":
    unittest.main()
