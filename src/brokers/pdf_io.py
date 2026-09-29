"""PDF 열기 공통 처리 — 암호 PDF 감지·한국어 안내."""

from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Any, Iterator

PASSWORD_PDF_HELP = (
    "이 PDF는 **암호(비밀번호)가 걸려** 있어 내용을 읽을 수 없습니다.\n\n"
    "**해결 방법**\n"
    "1. PDF를 받을 때 안내된 암호(생년월일 6자리, 계좌번호, 사업자번호 등)를 "
    "아래 **PDF 암호** 입력란에 입력한 뒤 다시 파싱하세요.\n"
    "2. HTS/MTS/홈택스 등에서 **암호 없는 PDF**로 다시 다운로드하세요.\n"
    "3. 가능하면 **CSV·Excel** 거래내역으로 업로드하세요."
)

PASSWORD_WRONG_HELP = (
    "입력한 PDF 암호가 맞지 않습니다. "
    "PDF 수신 안내(문자·메일)에 적힌 암호를 확인하거나, "
    "암호 없는 파일로 다시 받아 업로드하세요."
)


def is_pdf_bytes(file_bytes: bytes) -> bool:
    return bool(file_bytes) and file_bytes[:4] == b"%PDF"


def is_pdf_encrypted(file_bytes: bytes) -> bool:
    """트레일러 /Encrypt 존재 여부로 암호 PDF를 빠르게 감지."""
    if not is_pdf_bytes(file_bytes):
        return False
    tail = file_bytes[-8192:] if len(file_bytes) > 8192 else file_bytes
    return b"/Encrypt" in tail or b"/Encrypt" in file_bytes


def is_password_protected_error(exc: BaseException) -> bool:
    try:
        from pdfminer.pdfdocument import PDFPasswordIncorrect
    except ImportError:
        PDFPasswordIncorrect = ()  # type: ignore[misc, assignment]

    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, PDFPasswordIncorrect):
            return True
        name = type(cur).__name__
        if "Password" in name or "password" in str(cur).lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def pdf_open_error_message(
    exc: BaseException,
    *,
    file_bytes: bytes | None = None,
    password_attempted: bool = False,
) -> str:
    encrypted = bool(file_bytes is not None and is_pdf_encrypted(file_bytes))
    if is_password_protected_error(exc) or encrypted:
        return PASSWORD_WRONG_HELP if password_attempted else PASSWORD_PDF_HELP
    return f"PDF를 읽을 수 없습니다: {exc}"


@contextmanager
def open_pdf(
    file_bytes: bytes,
    *,
    password: str | None = None,
) -> Iterator[Any]:
    """pdfplumber.open 래퍼. 암호·손상 PDF는 ValueError(한국어)로 변환."""
    import pdfplumber

    if not is_pdf_bytes(file_bytes):
        raise ValueError("PDF 형식이 아닙니다. 파일이 손상되었거나 다른 형식일 수 있습니다.")

    pw = password if password is not None else ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes), password=pw) as pdf:
            yield pdf
    except ImportError as exc:
        raise ImportError(
            "pdfplumber가 설치되어 있지 않습니다. "
            "`pip install pdfplumber` 후 다시 시도하세요."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        attempted = bool(password)
        raise ValueError(
            pdf_open_error_message(
                exc,
                file_bytes=file_bytes,
                password_attempted=attempted,
            )
        ) from exc
