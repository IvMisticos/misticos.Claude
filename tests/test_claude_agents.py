from pathlib import Path

from claude_agents import AgentFolder, definition_model


def test_reads_a_definition_with_a_byte_order_mark_and_crlf(tmp_path: Path) -> None:
    text = "\ufeff---\r\nname: x\r\nmodel: opus\r\n---\r\n"
    (tmp_path / "x.md").write_bytes(text.encode())
    assert definition_model("x", [AgentFolder(tmp_path, "*.md")]) == "opus"
