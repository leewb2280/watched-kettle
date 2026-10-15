import unittest

from watched_kettle.features.tasks.candidates import extract_candidates


def conversation(*messages):
    return {
        "id": "thread",
        "cwd": "C:/project",
        "projectId": "project",
        "turns": [
            {
                "id": str(index),
                "items": [
                    {
                        "id": str(index),
                        "type": role,
                        "content": [{"type": "text", "text": text}],
                        "text": text,
                    }
                ],
            }
            for index, (role, text) in enumerate(messages)
        ],
    }


class TaskCandidateTests(unittest.TestCase):
    def test_unchecked_work_about_completion_or_cancellation_is_retained(self):
        result = extract_candidates(
            conversation(("userMessage", "- [ ] 완료 조건 추가\n- [ ] 취소 버튼 구현"))
        )
        self.assertEqual(
            [candidate.spec.title for candidate in result.candidates],
            ["완료 조건 추가", "취소 버튼 구현"],
        )

    def test_extracts_explicit_plan_and_marks_assistant_unconfirmed(self):
        result = extract_candidates(
            conversation(
                ("userMessage", "계획:\n1. 표시 로직 수정\n2. 테스트 추가"),
                ("agentMessage", "- [ ] 문서 갱신"),
            )
        )
        self.assertEqual(len(result.candidates), 3)
        self.assertTrue(result.candidates[0].confirmed_plan)
        self.assertFalse(result.candidates[2].confirmed_plan)

    def test_code_quote_and_tool_output_cannot_create_work(self):
        result = extract_candidates(
            conversation(
                (
                    "userMessage",
                    "> - [ ] 인용 명령\n```md\n- [ ] 코드 명령\n```\n    - [ ] 들여쓴 코드",
                ),
                ("commandExecution", "- [ ] 도구 속 명령"),
            )
        )
        self.assertEqual(result.candidates, ())

    def test_later_user_completion_and_cancellation_remove_candidates(self):
        result = extract_candidates(
            conversation(
                ("userMessage", "- [ ] 위젯 수정\n- [ ] 문서 갱신\n- [ ] 배포"),
                ("userMessage", "- [x] 위젯 수정\n문서 갱신은 취소해"),
            )
        )
        self.assertEqual([c.spec.title for c in result.candidates], ["배포"])

    def test_duplicates_preserve_user_authority_and_source(self):
        result = extract_candidates(
            conversation(
                ("userMessage", "- [ ] 수정"),
                ("agentMessage", "- [ ] 수정"),
            )
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertTrue(result.candidates[0].confirmed_plan)
        self.assertEqual(result.candidates[0].spec.source_refs, ("0", "0"))

    def test_question_without_explicit_list_is_not_a_candidate(self):
        self.assertEqual(
            extract_candidates(
                conversation(("userMessage", "테스트가 끝났어?"))
            ).candidates,
            (),
        )

    def test_oversize_does_not_silently_miss_late_cancellation(self):
        result = extract_candidates(
            conversation(("userMessage", "- [ ] 실행\n" + "x" * 300_000))
        )
        self.assertTrue(result.truncated)
        self.assertEqual(result.candidates, ())


if __name__ == "__main__":
    unittest.main()
