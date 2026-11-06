import json
import sys

type Message = dict[str, object]


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


def answer_with_notifications_so_far() -> None:
    notifications: list[Message] = []
    while (message := read_message()) is not None:
        if "id" in message:
            send({"jsonrpc": "2.0", "id": message["id"], "result": notifications})
        else:
            notifications.append(message)


answer_with_notifications_so_far()
