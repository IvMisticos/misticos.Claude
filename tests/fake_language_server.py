import json
import sys
from typing import Any

type Message = dict[str, Any]

CLASS, METHOD, FUNCTION = 5, 6, 12
FUNCTION_NAMES = ["greet", "welcome"]
GREET_LINE, WELCOME_LINE = 0, 1


def read_message() -> Message | None:
    length = 0
    while line := sys.stdin.buffer.readline():
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
        if line in (b"\r\n", b"\n"):
            return json.loads(sys.stdin.buffer.read(length))
    return None


def send(message: Message) -> None:
    body = json.dumps(message).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()


def starting_at(line: int, character: int) -> Message:
    position = {"line": line, "character": character}
    return {"start": position, "end": position}


def nested_symbols() -> list[Message]:
    greet = {
        "name": "greet",
        "kind": METHOD,
        "range": starting_at(1, 4),
        "selectionRange": starting_at(1, 8),
    }
    greeter = {
        "name": "Greeter",
        "kind": CLASS,
        "range": starting_at(0, 0),
        "selectionRange": starting_at(0, 6),
        "children": [greet],
    }
    return [greeter]


def flat_symbols(uri: str) -> list[Message]:
    return [
        {
            "name": "Greeter",
            "kind": CLASS,
            "location": {"uri": uri, "range": starting_at(0, 0)},
        },
        {
            "name": "greet",
            "kind": METHOD,
            "location": {"uri": uri, "range": starting_at(1, 4)},
        },
    ]


def workspace_symbols(opened_uris: list[str]) -> list[Message]:
    return [
        {
            "name": "Greeter",
            "kind": CLASS,
            "location": {"uri": uri, "range": starting_at(0, 6)},
        }
        for uri in opened_uris
    ]


CALL_SITE = starting_at(2, 4)


def function(uri: str, line: int) -> Message:
    return {
        "name": FUNCTION_NAMES[line],
        "kind": FUNCTION,
        "uri": uri,
        "range": starting_at(line, 0),
        "selectionRange": starting_at(line, 4),
        "data": {"line": line},
    }


def keeps_data(item: Message) -> bool:
    return item.get("data") == {"line": item["selectionRange"]["start"]["line"]}


def calls(item: Message, other_end: str, other_line: int) -> list[Message]:
    if not keeps_data(item):
        return []
    call = {other_end: function(item["uri"], other_line), "fromRanges": [CALL_SITE]}
    return [call]


class GreeterServer:
    def __init__(self) -> None:
        self.nests_symbols = False
        self.opened_uris: list[str] = []

    def answer(self, method: str, params: Message) -> object:
        match method:
            case "initialize":
                symbol_support = params["capabilities"]["textDocument"]
                self.nests_symbols = symbol_support.get("documentSymbol", {}).get(
                    "hierarchicalDocumentSymbolSupport", False
                )
                return {"capabilities": {}}
            case "textDocument/didOpen":
                self.opened_uris.append(params["textDocument"]["uri"])
            case "textDocument/documentSymbol":
                if self.nests_symbols:
                    return nested_symbols()
                return flat_symbols(params["textDocument"]["uri"])
            case "workspace/symbol":
                return workspace_symbols(self.opened_uris)
            case "textDocument/definition":
                return {"uri": params["textDocument"]["uri"]}
            case "textDocument/prepareCallHierarchy":
                uri = params["textDocument"]["uri"]
                return [function(uri, params["position"]["line"])]
            case "callHierarchy/incomingCalls":
                return calls(params["item"], "from", WELCOME_LINE)
            case "callHierarchy/outgoingCalls":
                return calls(params["item"], "to", GREET_LINE)
        return None


def serve() -> None:
    server = GreeterServer()
    while (message := read_message()) is not None:
        result = server.answer(message["method"], message.get("params") or {})
        if "id" in message:
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})


serve()
