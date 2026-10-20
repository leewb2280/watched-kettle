"""Codex failure wording, wait tooltips and the uncertain-row limit on actual Qt rows."""

from datetime import datetime, timedelta
import unittest

from tests import test_bubble_state_regressions as helpers
from tests import test_codex_subagent_wait as waits
from watched_kettle.features.project_activity.service import resume_time_text


class CodexBubbleWordingTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window
    wait = waits.SubagentWaitProjectionTests.wait
    child = waits.SubagentWaitProjectionTests.child

    def test_uncertain_row_is_dropped_after_fifteen_minutes(self):
        self.start()
        self.advance(61)
        self.assertEqual(self.row().badge.text(), "응답 없음")
        self.assertEqual(self.window().content.summary, "응답 없음 1개")
        self.advance(15 * 60 - 62)
        self.assertIn("a", self.projects.activities)
        self.advance(2)
        self.assertNotIn("a", self.projects.activities)
        self.assertFalse(self.projects.cards)

    def test_waiting_parent_is_kept_while_its_subagent_works(self):
        self.start()
        self.child()
        self.wait()
        for _ in range(20):
            self.advance(50)
            self.send("heartbeat", thread="child", agent_scope="subagent")
        # The parent itself has been silent for 1000 seconds.
        self.assertIn("a", self.projects.activities)
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        self.assertEqual(
            self.row().badge.toolTip(),
            "서브에이전트 작업이 끝나기를 기다리고 있습니다.",
        )

    def test_failure_reason_badges_and_tooltips(self):
        cases = {
            "usage_limit": ("사용량 한도", "Codex 사용량 한도에 도달해"),
            "rate_limit": ("요청 한도", "요청이 몰려"),
            "budget_limit": ("예산 한도", "사용 예산에 도달해"),
            "context_limit": ("대화 길이 초과", "대화가 너무 길어"),
            "provider_error": ("서버 오류", "Codex 서버 문제로"),
            "unknown": ("실패", ""),
        }
        for reason, (badge, tooltip) in cases.items():
            with self.subTest(reason=reason):
                self.projects.reset()
                self.start(turn=reason)
                self.send("failed", turn=reason, outcome_reason=reason)
                self.assertEqual(self.row().badge.text(), badge)
                if tooltip:
                    self.assertIn(tooltip, self.row().badge.toolTip())
                else:
                    self.assertEqual(self.row().badge.toolTip(), "")

    def test_resume_time_text_today_and_other_day(self):
        now = datetime(2026, 10, 20, 9, 0).astimezone()
        today = now.replace(hour=15, minute=20)
        self.assertEqual(resume_time_text(today.timestamp(), now), "15:20")
        later = today + timedelta(days=3)
        self.assertEqual(
            resume_time_text(later.timestamp(), now),
            f"{later.month}/{later.day} 15:20",
        )
        self.assertEqual(resume_time_text(10**20), "")


if __name__ == "__main__":
    unittest.main()
