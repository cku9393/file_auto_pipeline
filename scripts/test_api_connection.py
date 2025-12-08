#!/usr/bin/env python
"""
API 연결 테스트 스크립트.

실행:
    uv run python scripts/test_api_connection.py
"""

import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv()


async def test_anthropic():
    """Anthropic Claude API 테스트."""
    print("\n" + "=" * 60)
    print("🧪 Anthropic Claude API 테스트")
    print("=" * 60)

    api_key = os.environ.get("MY_ANTHROPIC_KEY")
    if not api_key or api_key.startswith("sk-ant-api03-..."):
        print("❌ MY_ANTHROPIC_KEY가 설정되지 않았습니다.")
        print("   .env 파일에 실제 API 키를 입력하세요.")
        return False

    print(f"✅ API 키 발견: {api_key[:20]}...")

    try:
        from src.app.providers.anthropic import ClaudeProvider

        provider = ClaudeProvider(
            model="claude-sonnet-4-20250514",  # 더 저렴한 모델로 테스트
            api_key=api_key,
        )

        print("📤 테스트 요청 전송 중...")
        response = await provider.complete("Say 'Hello, API test successful!' in Korean.")

        print(f"📥 응답: {response}")
        print("✅ Anthropic API 연결 성공!")
        return True

    except Exception as e:
        print(f"❌ Anthropic API 오류: {type(e).__name__}: {e}")
        return False


async def test_gemini():
    """Google Gemini API 테스트."""
    print("\n" + "=" * 60)
    print("🧪 Google Gemini API 테스트")
    print("=" * 60)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key or api_key.startswith("AI..."):
        print("❌ GOOGLE_API_KEY가 설정되지 않았습니다.")
        print("   .env 파일에 실제 API 키를 입력하세요.")
        return False

    print(f"✅ API 키 발견: {api_key[:15]}...")

    try:
        from src.app.providers.gemini import GeminiOCRProvider

        provider = GeminiOCRProvider(
            model="gemini-2.0-flash",  # 빠른 모델로 테스트
            api_key=api_key,
        )

        # 간단한 테스트 이미지 (1x1 흰색 PNG)
        # 실제 OCR 테스트를 위한 최소 이미지
        import base64
        # 1x1 white pixel PNG (valid minimal PNG)
        test_image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )

        print("📤 테스트 요청 전송 중 (간단한 이미지)...")
        result = await provider.extract_text(test_image, "image/png")

        print(f"📥 OCR 결과: success={result.success}")
        if result.text:
            print(f"   텍스트: {result.text[:100]}...")
        print(f"   모델: {result.model_used}")
        print("✅ Gemini API 연결 성공!")
        return True

    except Exception as e:
        print(f"❌ Gemini API 오류: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_gemini_with_real_image():
    """실제 이미지로 Gemini OCR 테스트."""
    print("\n" + "=" * 60)
    print("🧪 Gemini OCR 실제 이미지 테스트")
    print("=" * 60)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key or api_key.startswith("AI..."):
        print("⏭️ API 키가 없어 스킵")
        return False

    # 테스트용 이미지 경로 확인
    test_images = list(Path("tests/fixtures").rglob("*.jpg")) + \
                  list(Path("tests/fixtures").rglob("*.png"))

    if not test_images:
        print("⏭️ 테스트 이미지가 없어 스킵")
        print("   tests/fixtures/ 에 테스트 이미지를 추가하세요.")
        return True  # 이미지 없음은 실패가 아님

    try:
        from src.app.providers.gemini import GeminiOCRProvider

        provider = GeminiOCRProvider(api_key=api_key)

        test_image_path = test_images[0]
        print(f"📁 테스트 이미지: {test_image_path}")

        image_bytes = test_image_path.read_bytes()
        suffix = test_image_path.suffix.lower()
        mime_type = "image/jpeg" if suffix in [".jpg", ".jpeg"] else "image/png"

        print("📤 OCR 요청 전송 중...")
        result = await provider.extract_text(image_bytes, mime_type)

        print(f"📥 OCR 결과:")
        print(f"   성공: {result.success}")
        print(f"   텍스트 길이: {len(result.text or '')} 자")
        if result.text:
            print(f"   텍스트 미리보기: {result.text[:200]}...")

        return result.success

    except Exception as e:
        print(f"❌ 오류: {type(e).__name__}: {e}")
        return False


async def main():
    """메인 테스트 실행."""
    print("🚀 API 연결 테스트 시작")
    print("=" * 60)

    results = {}

    # Anthropic 테스트
    results["anthropic"] = await test_anthropic()

    # Gemini 테스트
    results["gemini"] = await test_gemini()

    # 실제 이미지 OCR 테스트 (선택)
    # results["gemini_real"] = await test_gemini_with_real_image()

    # 결과 요약
    print("\n" + "=" * 60)
    print("📊 테스트 결과 요약")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("🎉 모든 API 연결 테스트 통과!")
    else:
        print("⚠️ 일부 테스트 실패. .env 파일을 확인하세요.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
