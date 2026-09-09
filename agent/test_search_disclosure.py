import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from livekit.agents import Agent, llm

from coach import JobCoach
from intent import Intent, fast_intent
from tools import Posting, SessionState
from user import User


class DisclosureTests(unittest.IsolatedAsyncioTestCase):
    async def test_widening_evidence_reaches_writer_and_auditor_only_on_result_turn(self):
        posting = Posting(uuid4(), "Developer", "Example", "Israel", 82, "Relevant skills.", "https://example.com/apply")
        state = SessionState()
        writer_facts, audit_facts, contexts = [], [], []

        async def find(filters):
            return [] if filters.query else [posting]

        class Coach(JobCoach):
            @property
            def state(self):
                return state

            async def _resolve_intent(self, text):
                return fast_intent(text) or Intent("discuss")

            async def _audit_speech(self, text, facts, references):
                audit_facts.append(facts)

        async def model(_agent, context, *_args):
            contexts.append(context)
            current = next(m.text_content for m in context.messages() if (m.text_content or "").startswith("CURRENT_FACTS: "))
            facts = json.loads(current.removeprefix("CURRENT_FACTS: "))
            writer_facts.append(facts)
            text = "I widened the subject search." if "outcome" in facts else "Let's look closer."
            yield json.dumps({"parts": [{"text": text}], "stance": "neutral"})

        coach = Coach(User.default(), find_jobs=find)
        context = llm.ChatContext.empty()
        with patch.object(Agent.default, "llm_node", model):
            for utterance in ("find jobs in Israel with Rust", "tell me more"):
                message = context.add_message(role="user", content=utterance)
                await coach._prepare_turn(context, message)
                self.assertTrue([x async for x in coach.llm_node(context, [], None)])
        self.assertIn("removed only that query", writer_facts[0]["outcome"])
        self.assertEqual(writer_facts, audit_facts)
        self.assertNotIn("outcome", writer_facts[1])
        self.assertFalse(state.search_widened)
        self.assertFalse(any((m.text_content or "").startswith("SEARCH_RESULT:") for c in contexts for m in c.messages()))


if __name__ == "__main__":
    unittest.main()
