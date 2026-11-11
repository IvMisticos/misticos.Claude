import hashlib
from typing import NamedTuple

from plugin_paths import DATA_ROOT
from session_state import locked_session_file, read_record, write_record

RECEIPT_DIR = DATA_ROOT / "rules-receipts"


class RulesReceipt(NamedTuple):
    received: str = ""
    sent_at_session_start: str = ""


def rules_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def has_received(session_id: str, digest: str) -> bool:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        return read_record(receipt_file, RulesReceipt()).received == digest


def note_sent_at_session_start(session_id: str, digest: str) -> None:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        receipt = read_record(receipt_file, RulesReceipt())
        write_record(receipt_file, receipt._replace(sent_at_session_start=digest))


def confirm_session_start_copy(session_id: str) -> None:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        receipt = read_record(receipt_file, RulesReceipt())
        if receipt.sent_at_session_start:
            write_record(receipt_file, RulesReceipt(receipt.sent_at_session_start))


def note_received(session_id: str, digest: str) -> None:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        write_record(receipt_file, RulesReceipt(digest))
