import json
import sys
from typing import Any

type Message = dict[str, Any]

CLASS, METHOD, FUNCTION = 5, 6, 12
DEPRECATED = 1
INTERNAL_ERROR = -32603


class ErrorReply(Exception):
    pass


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


def definition(uri: str, line: int) -> Message:
    with_range = {"uri": uri, "range": starting_at(0, 6)}
    without_range = {"uri": uri}
    without_uri = {"range": starting_at(0, 6)}
    return [with_range, without_range, without_uri][line]


def hover() -> Message:
    signature = {"kind": "markdown", "value": "class Greeter"}
    return {"contents": [signature, "Greets people."]}


CALL_SITE = starting_at(1, 4)


def directory_of(uri: str) -> str:
    return uri.rsplit("/", 1)[0]


def function(directory_uri: str, name: str) -> Message:
    return {
        "name": name,
        "kind": FUNCTION,
        "tags": [DEPRECATED],
        "detail": f"def {name}()",
        "uri": f"{directory_uri}/{name}.py",
        "range": starting_at(0, 0),
        "selectionRange": starting_at(0, 4),
        "vendorData": {"name": name},
    }


def function_in(uri: str) -> Message:
    name = uri.rsplit("/", 1)[1].removesuffix(".py")
    return function(directory_of(uri), name)


def calls(item: Message, other_end: str, other_name: str) -> list[Message]:
    if item != function_in(item["uri"]):
        return []
    other = function(directory_of(item["uri"]), other_name)
    return [{other_end: other, "fromRanges": [CALL_SITE]}]


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
                uri = params["textDocument"]["uri"]
                return definition(uri, params["position"]["line"])
            case "textDocument/hover":
                return hover()
            case "textDocument/rename":
                raise ErrorReply("rename is not supported")
            case "textDocument/prepareCallHierarchy":
                return [function_in(params["textDocument"]["uri"])]
            case "callHierarchy/incomingCalls":
                return calls(params["item"], "from", "welcome")
            case "callHierarchy/outgoingCalls":
                return calls(params["item"], "to", "greet")
        return None


def reply_body(server: GreeterServer, message: Message) -> Message:
    try:
        return {"result": server.answer(message["method"], message.get("params") or {})}
    except ErrorReply as error:
        return {"error": {"code": INTERNAL_ERROR, "message": str(error)}}


def serve() -> None:
    server = GreeterServer()
    while (message := read_message()) is not None:
        body = reply_body(server, message)
        if "id" in message:
            send({"jsonrpc": "2.0", "id": message["id"], **body})


serve()
