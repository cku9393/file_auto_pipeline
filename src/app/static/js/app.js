/**
 * Manufacturing Docs Pipeline - Frontend JS
 * HTMX 기반 최소 스택
 */

// =============================================================================
// Session Management
// =============================================================================

/**
 * 세션 ID 생성/조회
 */
function getSessionId() {
    let sessionId = sessionStorage.getItem('chat_session_id');
    if (!sessionId) {
        sessionId = crypto.randomUUID();
        sessionStorage.setItem('chat_session_id', sessionId);
    }
    return sessionId;
}

/**
 * 새 세션 시작
 */
function newSession() {
    const sessionId = crypto.randomUUID();
    sessionStorage.setItem('chat_session_id', sessionId);
    return sessionId;
}

// =============================================================================
// File Upload
// =============================================================================

/**
 * 파일 선택 시 미리보기 업데이트
 */
function handleFileSelect(event) {
    const preview = document.getElementById('file-preview');
    if (!preview) return;

    preview.innerHTML = '';

    for (const file of event.target.files) {
        const chip = document.createElement('span');
        chip.className = 'file-chip';
        chip.innerHTML = `📎 ${file.name} <button type="button" onclick="removeFile(this, '${file.name}')">&times;</button>`;
        preview.appendChild(chip);
    }
}

/**
 * 파일 제거 (미리보기에서)
 */
function removeFile(button, filename) {
    button.parentElement.remove();
    // TODO: 실제 파일 입력에서도 제거
}

// =============================================================================
// HTMX Event Handlers
// =============================================================================

// 페이지 로드 시 세션 ID 설정
document.addEventListener('DOMContentLoaded', function() {
    const sessionInput = document.getElementById('session-id');
    if (sessionInput) {
        sessionInput.value = getSessionId();
    }

    // 파일 입력 이벤트
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect);
    }
});

// HTMX 요청 전 세션 ID 추가
document.body.addEventListener('htmx:configRequest', function(event) {
    const sessionId = getSessionId();
    if (event.detail.parameters) {
        event.detail.parameters['session_id'] = sessionId;
    }
});

// 요청 성공 후 처리
document.body.addEventListener('htmx:afterRequest', function(event) {
    // 채팅 입력 초기화
    if (event.detail.target.id === 'chat-messages' && event.detail.successful) {
        const textarea = document.querySelector('.chat-input-form textarea');
        if (textarea) {
            textarea.value = '';
        }

        const filePreview = document.getElementById('file-preview');
        if (filePreview) {
            filePreview.innerHTML = '';
        }

        const fileInput = document.getElementById('file-input');
        if (fileInput) {
            fileInput.value = '';
        }

        // 스크롤 맨 아래로
        event.detail.target.scrollTop = event.detail.target.scrollHeight;
    }
});

// 에러 처리
document.body.addEventListener('htmx:responseError', function(event) {
    console.error('HTMX Error:', event.detail);
    alert('오류가 발생했습니다. 다시 시도해주세요.');
});

// =============================================================================
// Override Modal
// =============================================================================

/**
 * Override 모달 열기
 */
function openOverrideModal(field) {
    // HTMX로 모달 내용 로드
    htmx.ajax('GET', `/api/chat/override-dialog?field=${field}`, {
        target: '#override-modal',
        swap: 'innerHTML'
    });
}

/**
 * Override 적용
 */
function applyOverride(field, reason) {
    htmx.ajax('POST', '/api/chat/override', {
        values: {
            field: field,
            reason: reason,
            session_id: getSessionId()
        },
        target: '#chat-messages',
        swap: 'beforeend'
    });

    // 모달 닫기
    document.getElementById('override-modal').innerHTML = '';
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * 날짜 포맷팅
 */
function formatDate(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString('ko-KR');
}

/**
 * 파일 크기 포맷팅
 */
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
