"""User-facing task states shared by the worker and both task views."""

STATE_LABELS = {
    "draft": "초안",
    "queued": "대기",
    "starting": "시작 확인 중",
    "running": "진행",
    "reconciling": "상태 확인 중",
    "needs_review": "확인 필요",
    "failed": "실패",
    "stopped": "중단",
    "complete": "완료",
}

REASON_LABELS = {
    "reconciliation_required": "이전 실행의 시작·종료 상태를 먼저 대조한 뒤 계속 실행하세요.",
    "history_verification_failed": "원본 또는 실행 결과를 끝까지 확인하지 못했습니다. 연결 상태를 확인한 뒤 다시 대조하세요.",
    "candidate_changed": "해당 후보가 변경되거나 완료·취소되었습니다. 최신 후보를 확인하세요.",
    "thread_read_unavailable": "이 대화를 읽을 수 없습니다. 프로젝트 제외 설정과 연결을 확인하세요.",
    "request_expired": "이미 해결되었거나 만료된 요청입니다.",
    "request_response_unknown": "답변 전송 결과가 불명확합니다. 요청 상태를 다시 확인하세요.",
    "execution_scope_unverified": "Desktop 실행 연결을 확인하지 못했습니다.",
    "source_changed": "대화가 변경되었습니다. 변경 비교 후 다시 등록하세요.",
    "source_version_upgrade": "이전 버전에서 저장한 작업입니다. 원본을 다시 검토하세요.",
    "conversation_busy": "대화의 현재 작업이 끝나기를 기다립니다.",
    "project_busy": "같은 프로젝트의 작업이 진행 중입니다.",
    "repository_busy": "같은 저장소의 작업이 진행 중입니다.",
    "project_paused": "프로젝트가 일시 정지되었습니다.",
    "previous_task_needs_attention": "이전 작업의 결과 확인이 필요합니다.",
    "parallel_limit": "동시 실행 자리를 기다립니다.",
    "concurrency_limit": "동시 실행 자리를 기다립니다.",
    "manual_confirmation_required": "결과를 확인한 뒤 완료 확인을 눌러주세요.",
    "restart_reconciliation": "재시작 후 원래 실행 상태를 확인해야 합니다.",
    "execution_response_unknown": "실행 응답이 불명확합니다. 재전송 없이 상태를 확인하세요.",
    "user_input_required": "승인 또는 사용자 입력을 기다립니다.",
    "decryption_failed": "암호화 항목을 열 수 없습니다.",
    "paused_before_send": "전송 전에 일시 정지되었습니다.",
    "command_evidence_missing": "등록한 명령의 실행 근거를 확인하지 못했습니다.",
    "artifact_evidence_missing": "등록한 파일의 확인 근거가 없습니다.",
    "artifact_check_failed": "등록한 파일이 없습니다.",
    "command_failed": "등록한 명령이 실패했습니다.",
    "turn_failed": "Codex 실행이 실패했습니다.",
    "turn_interrupted": "Codex 실행이 중단되었습니다.",
    "execution_path_unavailable": "실행 위치를 확인할 수 없습니다.",
    "execution_target_changed": "대상 대화의 프로젝트 또는 경로가 변경되었습니다.",
    "execution_target_unavailable": "실행할 대화 정보를 확인하지 못했습니다.",
    "turn_identity_unknown": "실행 턴의 식별 정보를 확인하지 못했습니다.",
    "turn_not_terminal": "실행이 아직 종료되지 않았습니다.",
    "completion_evidence_invalid": "완료 근거를 읽을 수 없습니다.",
    "completion_check_required": "완료 조건을 추가하세요.",
    "execution_target_required": "대화와 실행 위치를 확인하세요.",
    "duplicate_task": "같은 작업이 이미 저장되어 있습니다.",
    "review_version_changed": "검토 이후 내용이 변경되었습니다. 다시 확인하세요.",
    "protected_data_unavailable": "암호화 데이터를 열 수 없습니다.",
    "account_required": "로그인 계정을 확인한 뒤 다시 시도하세요.",
    "active_task_cannot_remove": "실행 중인 항목은 삭제할 수 없습니다.",
    "terminal_evidence_required": "실행 상태와 종료 근거를 먼저 확인하세요.",
    "batch_selection_required": "실행할 대기 작업을 선택하세요.",
    "batch_selection_changed": "선택한 작업의 상태가 바뀌었습니다.",
    "task_missing": "작업이 더 이상 존재하지 않습니다.",
    "server_request_expired": "이미 해결되었거나 만료된 요청입니다.",
}


def reason_text(reason):
    return (
        REASON_LABELS.get(reason, "요청을 처리하지 못했습니다. 최신 상태를 확인하세요.")
        if reason
        else ""
    )


def item_spec(item):
    return item.get("spec") or item.get("summary") or {}
