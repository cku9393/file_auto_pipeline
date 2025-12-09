"""
Intake Service: 채팅/파일 → intake_session.json

ADR-0003 불변성 규칙:
- messages 원문은 절대 수정 금지
- 후처리 결과는 append 이벤트로만 추가
- 사용자 수정값은 user_corrections에 기록
- 원문 덮어쓰기 시도 시 에러
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.ssot_job import atomic_write_json
from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import (
    IntakeAttachment,
    IntakeMessage,
    IntakeSession,
    PhotoMapping,
    UserCorrection,
)


class IntakeService:
    """
    Intake 세션 관리 서비스.

    intake_session.json 생성 및 append-only 업데이트.
    """

    SCHEMA_VERSION = "1.0"

    def __init__(self, job_dir: Path):
        """
        Args:
            job_dir: Job 폴더 경로
        """
        self.job_dir = job_dir
        self.inputs_dir = job_dir / "inputs"
        self.uploads_dir = self.inputs_dir / "uploads"
        self.session_path = self.inputs_dir / "intake_session.json"

    def create_session(self) -> IntakeSession:
        """
        새 Intake 세션 생성.

        Returns:
            IntakeSession
        """
        # 폴더 구조 생성
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        session = IntakeSession(
            schema_version=self.SCHEMA_VERSION,
            session_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            immutable=True,
        )

        self._save_session(session)
        return session

    def load_session(self) -> IntakeSession:
        """
        기존 세션 로드.

        Returns:
            IntakeSession

        Raises:
            PolicyRejectError: INTAKE_SESSION_CORRUPT
        """
        if not self.session_path.exists():
            return self.create_session()

        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))

            # schema_version 필수 체크
            if "schema_version" not in data:
                raise PolicyRejectError(
                    ErrorCodes.INTAKE_SESSION_CORRUPT,
                    error="schema_version missing",
                    path=str(self.session_path),
                )

            return self._dict_to_session(data)

        except json.JSONDecodeError as e:
            raise PolicyRejectError(
                ErrorCodes.INTAKE_SESSION_CORRUPT,
                error=str(e),
                path=str(self.session_path),
            ) from e

    def add_message(
        self,
        role: str,
        content: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> IntakeMessage:
        """
        메시지 추가 (append-only).

        Args:
            role: "user" 또는 "assistant"
            content: 메시지 내용
            attachments: [(filename, bytes), ...] 첨부 파일

        Returns:
            추가된 IntakeMessage
        """
        session = self.load_session()

        # 첨부 파일 저장
        saved_attachments = []
        if attachments:
            for filename, file_bytes in attachments:
                saved_path = self._save_upload(filename, file_bytes)
                saved_attachments.append(
                    IntakeAttachment(
                        filename=filename,
                        size=len(file_bytes),
                        path=str(saved_path.relative_to(self.job_dir)),
                    )
                )

        message = IntakeMessage(
            role=role,
            content=content,
            timestamp=datetime.now(UTC).isoformat(),
            attachments=saved_attachments,
        )

        session.messages.append(message)
        self._save_session(session)

        return message

    def add_ocr_result(
        self,
        filename: str,
        result: Any,
    ) -> None:
        """
        OCR 결과 추가 (append-only).

        ADR-0003: model_requested + model_used 필수

        Args:
            filename: 원본 파일명
            result: OCRResult
        """
        session = self.load_session()

        # model_used 필수 체크
        if result.model_used is None:
            raise PolicyRejectError(
                ErrorCodes.INTAKE_SESSION_CORRUPT,
                error="model_used is required for OCR result",
                filename=filename,
            )

        session.ocr_results[filename] = result
        self._save_session(session)

    def add_extraction_result(
        self,
        result: Any,
    ) -> None:
        """
        LLM 추출 결과 추가 (append-only).

        ADR-0003: model_requested + model_used 필수

        Args:
            result: ExtractionResult
        """
        session = self.load_session()

        # model_used 필수 체크
        if result.model_used is None:
            raise PolicyRejectError(
                ErrorCodes.INTAKE_SESSION_CORRUPT,
                error="model_used is required for extraction result",
            )

        # 기존 결과가 있으면 에러 (immutable)
        if session.extraction_result is not None:
            raise PolicyRejectError(
                ErrorCodes.INTAKE_IMMUTABLE_VIOLATION,
                error="extraction_result already exists. Cannot overwrite.",
            )

        session.extraction_result = result
        self._save_session(session)

    def add_user_correction(
        self,
        field: str,
        original: Any,
        corrected: Any,
        user: str = "user",
    ) -> None:
        """
        사용자 수정 기록 추가.

        ADR-0003: 원문은 수정하지 않고 corrections에 기록

        Args:
            field: 수정된 필드명
            original: 원래 값
            corrected: 수정된 값
            user: 수정자
        """
        session = self.load_session()

        correction = UserCorrection(
            field=field,
            original=original,
            corrected=corrected,
            corrected_at=datetime.now(UTC).isoformat(),
            corrected_by=user,
        )

        session.user_corrections.append(correction)
        self._save_session(session)

    def get_final_fields(self) -> dict[str, Any]:
        """
        최종 필드 값 반환 (추출 + 수정 적용).

        Returns:
            필드 딕셔너리
        """
        session = self.load_session()

        if session.extraction_result is None:
            return {}

        # 추출 결과를 기본값으로
        fields = dict(session.extraction_result.fields)

        # 사용자 수정 적용
        for correction in session.user_corrections:
            fields[correction.field] = correction.corrected

        return fields

    def add_photo_mapping(
        self,
        slot_key: str,
        filename: str,
        raw_path: str,
    ) -> PhotoMapping:
        """
        사진 슬롯 매핑 추가.

        Args:
            slot_key: 슬롯 키 (예: overview, label_serial)
            filename: 원본 파일명
            raw_path: 저장된 raw 경로

        Returns:
            PhotoMapping
        """
        session = self.load_session()

        mapping = PhotoMapping(
            slot_key=slot_key,
            filename=filename,
            raw_path=raw_path,
            mapped_at=datetime.now(UTC).isoformat(),
        )

        # 기존 매핑 업데이트 (같은 슬롯이면 교체)
        session.photo_mappings = [
            m for m in session.photo_mappings if m.slot_key != slot_key
        ]
        session.photo_mappings.append(mapping)

        self._save_session(session)
        return mapping

    def get_photo_mappings(self) -> dict[str, PhotoMapping]:
        """
        현재 사진 매핑 상태 조회.

        Returns:
            {slot_key: PhotoMapping}
        """
        session = self.load_session()
        return {m.slot_key: m for m in session.photo_mappings}

    def _save_upload(self, filename: str, file_bytes: bytes) -> Path:
        """업로드 파일 저장."""
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # 파일명 충돌 방지
        target = self.uploads_dir / filename
        counter = 1
        while target.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            target = self.uploads_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        target.write_bytes(file_bytes)
        return target

    def _save_session(self, session: IntakeSession) -> None:
        """세션을 파일로 저장."""
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        data = self._session_to_dict(session)
        atomic_write_json(self.session_path, data)

    def _session_to_dict(self, session: IntakeSession) -> dict[str, Any]:
        """IntakeSession → dict."""
        return {
            "schema_version": session.schema_version,
            "session_id": session.session_id,
            "created_at": session.created_at,
            "immutable": session.immutable,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "attachments": [
                        {
                            "filename": a.filename,
                            "size": a.size,
                            "path": a.path,
                        }
                        for a in m.attachments
                    ],
                }
                for m in session.messages
            ],
            "ocr_results": {
                k: v.to_dict() if hasattr(v, "to_dict") else v
                for k, v in session.ocr_results.items()
            },
            "extraction_result": (
                session.extraction_result.to_dict()
                if session.extraction_result
                and hasattr(session.extraction_result, "to_dict")
                else session.extraction_result
            ),
            "user_corrections": [
                {
                    "field": c.field,
                    "original": c.original,
                    "corrected": c.corrected,
                    "corrected_at": c.corrected_at,
                    "corrected_by": c.corrected_by,
                }
                for c in session.user_corrections
            ],
            "photo_mappings": [
                {
                    "slot_key": p.slot_key,
                    "filename": p.filename,
                    "raw_path": p.raw_path,
                    "mapped_at": p.mapped_at,
                }
                for p in session.photo_mappings
            ],
        }

    def _dict_to_session(self, data: dict[str, Any]) -> IntakeSession:
        """dict → IntakeSession."""
        from src.app.providers.base import OCRResult as ProviderOCRResult

        session = IntakeSession(
            schema_version=data["schema_version"],
            session_id=data["session_id"],
            created_at=data["created_at"],
            immutable=data.get("immutable", True),
        )

        # Messages
        for m in data.get("messages", []):
            session.messages.append(
                IntakeMessage(
                    role=m["role"],
                    content=m["content"],
                    timestamp=m["timestamp"],
                    attachments=[
                        IntakeAttachment(
                            filename=a["filename"],
                            size=a["size"],
                            path=a["path"],
                        )
                        for a in m.get("attachments", [])
                    ],
                )
            )

        # OCR Results
        for k, v in data.get("ocr_results", {}).items():
            session.ocr_results[k] = ProviderOCRResult(
                success=v["success"],
                text=v.get("text"),
                confidence=v.get("confidence"),
                model_requested=v.get("model_requested"),
                model_used=v.get("model_used"),
                fallback_triggered=v.get("fallback_triggered", False),
                processed_at=v.get("processed_at"),
                error_message=v.get("error_message"),
            )

        # Extraction Result
        if data.get("extraction_result"):
            from src.app.providers.base import (
                ExtractionResult as ProviderExtractionResult,
            )

            er = data["extraction_result"]
            session.extraction_result = ProviderExtractionResult(
                success=er.get("success", True),
                fields=er.get("fields", {}),
                measurements=er.get("measurements", []),
                missing_fields=er.get("missing_fields", []),
                warnings=er.get("warnings", []),
                confidence=er.get("confidence"),
                suggested_template_id=er.get("suggested_template_id"),
                model_requested=er.get("model_requested"),
                model_used=er.get("model_used"),
                extracted_at=er.get("extracted_at"),
                # === 조건부 재현성 메타데이터 ===
                provider=er.get("provider"),
                model_params=er.get("model_params"),
                request_id=er.get("request_id"),
                # === Raw 저장 ===
                llm_raw_output=er.get("llm_raw_output"),
                llm_raw_output_hash=er.get("llm_raw_output_hash"),
                llm_raw_truncated=er.get("llm_raw_truncated", False),
                # === 프롬프트 분리 저장 ===
                prompt_template_id=er.get("prompt_template_id"),
                prompt_template_version=er.get("prompt_template_version"),
                prompt_user_variables=er.get("prompt_user_variables"),
                prompt_rendered=er.get("prompt_rendered"),
                prompt_hash=er.get("prompt_hash"),
                prompt_used=er.get("prompt_used"),  # 하위 호환
                # === 추출 방법 ===
                extraction_method=er.get("extraction_method"),
                regex_version=er.get("regex_version"),
            )

        # User Corrections
        for c in data.get("user_corrections", []):
            session.user_corrections.append(
                UserCorrection(
                    field=c["field"],
                    original=c["original"],
                    corrected=c["corrected"],
                    corrected_at=c["corrected_at"],
                    corrected_by=c.get("corrected_by", "user"),
                )
            )

        # Photo Mappings
        for p in data.get("photo_mappings", []):
            session.photo_mappings.append(
                PhotoMapping(
                    slot_key=p["slot_key"],
                    filename=p["filename"],
                    raw_path=p["raw_path"],
                    mapped_at=p["mapped_at"],
                )
            )

        return session
