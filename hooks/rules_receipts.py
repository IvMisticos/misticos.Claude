from typing import NamedTuple

from plugin_paths import DATA_ROOT
from session_state import locked_session_file, read_record, write_record

RECEIPT_DIR = DATA_ROOT / "rules-receipts"


class RulesReceipt(NamedTuple):
    digest: str = ""


def has_received(session_id: str, digest: str) -> bool:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        return read_record(receipt_file, RulesReceipt()).digest == digest


def note_received(session_id: str, digest: str) -> None:
    with locked_session_file(RECEIPT_DIR, session_id) as receipt_file:
        write_record(receipt_file, RulesReceipt(digest))
