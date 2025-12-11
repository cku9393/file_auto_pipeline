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
 * 세션 ID 설정 (sessionStorage + DOM 양방향 동기화)
 */
function setSessionId(sessionId) {
    if (sessionId) {
        sessionStorage.setItem('chat_session_id', sessionId);
        const sessionInput = document.getElementById('session-id');
        if (sessionInput) sessionInput.value = sessionId;
    }
}

/**
 * 새 세션 시작
 */
function newSession() {
    const sessionId = crypto.randomUUID();
    setSessionId(sessionId);
    return sessionId;
}

// =============================================================================
// DOM Helpers
// =============================================================================

/**
 * HTML 이스케이프
 */
function escapeHtml(s) {
    return String(s)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

/**
 * 채팅 메시지 추가
 */
function appendChatMessage(role, text) {
    const box = document.getElementById('chat-messages');
    if (!box) return;

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = escapeHtml(text).replaceAll('\n', '<br>');
    box.appendChild(div);

    box.scrollTop = box.scrollHeight;
}

/**
 * 파일 칩 렌더링
 */
function renderFileChips(files) {
    const list = document.getElementById('file-list'); // HTML id와 일치
    if (!list) return;

    list.innerHTML = '';
    for (const file of files) {
        const chip = document.createElement('span');
        chip.className = 'file-chip';
        chip.textContent = `📎 ${file.name}`;
        list.appendChild(chip);
    }
}

/**
 * 파일 칩 초기화
 */
function clearFileChips() {
    const list = document.getElementById('file-list');
    if (list) list.innerHTML = '';
}

// =============================================================================
// File Upload (즉시 업로드 방식)
// =============================================================================

/**
 * 단일 파일 업로드
 */
async function uploadOneFile(file) {
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('session_id', getSessionId());

    const res = await fetch('/api/chat/upload', {
        method: 'POST',
        body: fd,
    });

    if (!res.ok) {
        const t = await res.text();
        throw new Error(`upload failed: ${res.status} ${t}`);
    }

    return await res.json();
}

/**
 * 채팅창에 HTML 삽입 (서버에서 받은 HTML 조각)
 */
function appendHtmlToChat(html) {
    const box = document.getElementById('chat-messages');
    if (!box || !html) return;

    box.insertAdjacentHTML('beforeend', html);
    box.scrollTop = box.scrollHeight;
}

/**
 * 파일 선택 시 즉시 업로드
 */
async function handleFileSelect(event) {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;

    // UI에 선택 표시
    renderFileChips(files);

    // 사용자에게 업로드 시작 알림 (여러 파일일 경우에만)
    if (files.length > 1) {
        appendChatMessage('assistant', `파일 ${files.length}개 업로드 중...`);
    }

    // 단일 파일 API라 순차 업로드 (안정적)
    for (const file of files) {
        try {
            const data = await uploadOneFile(file);

            // 서버에서 생성한 HTML 조각이 있으면 사용 (OCR 상세 메시지 포함)
            if (data.messages_html) {
                appendHtmlToChat(data.messages_html);
            } else {
                // Fallback: 기존 방식으로 간단 메시지 생성
                let msg = `업로드 완료: ${escapeHtml(data.filename)}`;
                if (data.slot_mapped) msg += ` (slot: ${escapeHtml(data.slot_mapped)})`;
                if (data.ocr_executed) msg += ` / OCR: ${data.ocr_success ? '성공' : '실패'}`;
                appendChatMessage('assistant', msg);
            }

            // 세션 ID 동기화 (서버가 새로 생성했을 수 있음)
            if (data.session_id) {
                setSessionId(data.session_id);
            }

        } catch (e) {
            // 업로드 실패 메시지
            const errorMsg = `업로드 실패: ${escapeHtml(file.name)}<br>${escapeHtml(e.message || '알 수 없는 오류')}`;
            appendHtmlToChat(`<div class="message assistant error">${errorMsg}</div>`);
            console.error('Upload failed:', e);
        }
    }

    // 같은 파일 재선택 가능하게 reset
    event.target.value = '';
    clearFileChips();
}

// =============================================================================
// HTMX Event Handlers
// =============================================================================

// 페이지 로드 시 초기화
document.addEventListener('DOMContentLoaded', function() {
    // DOM의 session-id를 sessionStorage와 동기화 (둘 중 하나만 있어도 맞춰짐)
    const sessionInput = document.getElementById('session-id');
    if (sessionInput) {
        const existing = sessionInput.value || sessionStorage.getItem('chat_session_id');
        setSessionId(existing || getSessionId());
    }

    // 파일 입력 이벤트
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect);
    }
});

// HTMX 요청 전 세션 ID + content 추가 (TOCTOU-safe 폼 직렬화)
document.body.addEventListener('htmx:configRequest', function(event) {
    const sessionId = getSessionId();
    event.detail.parameters = event.detail.parameters || {};
    event.detail.parameters['session_id'] = sessionId;

    // chat-form 제출 시 content 명시적 추가 (HTMX 직렬화 문제 방지)
    if (event.detail.elt && event.detail.elt.id === 'chat-form') {
        const textarea = document.querySelector('#chat-form textarea[name="content"]');
        if (textarea && typeof textarea.value === 'string') {
            event.detail.parameters['content'] = textarea.value;
        }
    }
});

// 요청 성공 후 처리
document.body.addEventListener('htmx:afterRequest', function(event) {
    // OOB로 업데이트된 session-id가 있으면 sessionStorage와 동기화
    const domSession = document.getElementById('session-id')?.value;
    if (domSession) setSessionId(domSession);

    // 메시지 전송 폼에서만 textarea 초기화
    const elt = event.detail.elt;
    if (elt && elt.id === 'chat-form' && event.detail.successful) {
        // 올바른 셀렉터: #chat-form 내의 textarea[name="content"]
        const textarea = document.querySelector('#chat-form textarea[name="content"]');
        if (textarea) {
            textarea.value = '';
        }

        // 파일 관련 초기화
        clearFileChips();
        const fileInput = document.getElementById('file-input');
        if (fileInput) {
            fileInput.value = '';
        }

        // 스크롤 맨 아래로
        const chatMessages = document.getElementById('chat-messages');
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
});

// 에러 처리
document.body.addEventListener('htmx:responseError', function(event) {
    console.error('HTMX Error:', event.detail);
    alert('오류가 발생했습니다. 다시 시도해주세요.');
});

// =============================================================================
// Template Registration Modal
// =============================================================================

/**
 * 템플릿 등록 모달 열기
 */
function openTemplateRegisterModal(sessionId, filename, suggestedId, suggestedName) {
    // 모달 HTML 생성
    const modalHtml = `
        <div class="modal-backdrop" onclick="closeTemplateModal()"></div>
        <div class="modal-content">
            <h3>📋 템플릿으로 등록</h3>
            <p>파일: <strong>${escapeHtml(filename)}</strong></p>

            <form id="template-register-form" onsubmit="submitTemplateRegistration(event)">
                <input type="hidden" name="session_id" value="${escapeHtml(sessionId)}">
                <input type="hidden" name="source_filename" value="${escapeHtml(filename)}">

                <div class="form-group">
                    <label for="template-id">템플릿 ID</label>
                    <input type="text" id="template-id" name="template_id"
                           value="${escapeHtml(suggestedId)}"
                           pattern="[a-z0-9_]+" required
                           placeholder="customer_a_inspection">
                    <small>소문자, 숫자, 밑줄만 허용</small>
                </div>

                <div class="form-group">
                    <label for="display-name">표시 이름</label>
                    <input type="text" id="display-name" name="display_name"
                           value="${escapeHtml(suggestedName)}" required
                           placeholder="고객사A 검사성적서">
                </div>

                <div class="form-group">
                    <label for="doc-type">문서 타입</label>
                    <select id="doc-type" name="doc_type">
                        <option value="inspection">검사성적서</option>
                        <option value="report">보고서</option>
                        <option value="other">기타</option>
                    </select>
                </div>

                <div class="modal-buttons">
                    <button type="button" class="btn btn-secondary" onclick="closeTemplateModal()">취소</button>
                    <button type="submit" class="btn btn-primary">등록</button>
                </div>
            </form>

            <div id="template-register-result"></div>
        </div>
    `;

    // 모달 컨테이너에 삽입
    let modal = document.getElementById('template-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'template-modal';
        modal.className = 'modal';
        document.body.appendChild(modal);
    }
    modal.innerHTML = modalHtml;
    modal.style.display = 'flex';
}

/**
 * 템플릿 모달 닫기
 */
function closeTemplateModal() {
    const modal = document.getElementById('template-modal');
    if (modal) {
        modal.style.display = 'none';
        modal.innerHTML = '';
    }
}

/**
 * 템플릿 등록 폼 제출
 */
async function submitTemplateRegistration(event) {
    event.preventDefault();

    const form = event.target;
    const formData = new FormData(form);
    const resultDiv = document.getElementById('template-register-result');

    // 버튼 비활성화 + 로딩 표시
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = '등록 중...';

    try {
        const response = await fetch('/api/templates', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // 성공 메시지
            resultDiv.innerHTML = `
                <div class="alert alert-success">
                    ✅ 템플릿 '${escapeHtml(data.template_id)}'이(가) 등록되었습니다!
                </div>
            `;

            // 채팅창에도 알림
            appendChatMessage('assistant', `✅ 템플릿 '${data.template_id}'이(가) 등록되었습니다.`);

            // 1.5초 후 모달 닫기
            setTimeout(closeTemplateModal, 1500);
        } else {
            // 에러 메시지
            const errorMsg = data.detail?.message || data.message || '등록 실패';
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    ❌ ${escapeHtml(errorMsg)}
                </div>
            `;
            submitBtn.disabled = false;
            submitBtn.textContent = '등록';
        }
    } catch (e) {
        resultDiv.innerHTML = `
            <div class="alert alert-error">
                ❌ 네트워크 오류: ${escapeHtml(e.message)}
            </div>
        `;
        submitBtn.disabled = false;
        submitBtn.textContent = '등록';
    }
}

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
    const modal = document.getElementById('override-modal');
    if (modal) modal.innerHTML = '';
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
