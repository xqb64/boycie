import trio


COMMANDERS = [
    'adder!~adder@user/adder',
    'adder`!~adder@user/adder'
]

NETWORK = 'irc.libera.chat'
PORT = 6667
NICK = 'Boycie'
REAL_NAME = 'Boycie'
USER_NAME = 'Boycie'


async def say(stream, target: str, message: str) -> None:
    await send(stream, "PRIVMSG %s :%s" % (target, message))

async def join(stream, channel: str) -> None:
    await send(stream, "JOIN %s" % channel)

async def send(stream, message: str) -> None:
    message = message.encode('UTF-8')
    await stream.send_all(message + b'\r\n')

async def recv_until(stream, terminator: bytes) -> bytes:
    buffer = b''

    while True:
        msg = await stream.receive_some()
        buffer += msg

        if msg.endswith(terminator):
            break

    return buffer

async def main() -> None:
    stream = await trio.open_tcp_stream(NETWORK, PORT)

    await send(stream, "NICK %s" % NICK)
    await send(stream, "USER %s * 0: %s" % (USER_NAME, REAL_NAME))

    while True:
        msg = await recv_until(stream, b'\r\n')
        msg = msg.decode('UTF-8').strip()

        print('Got a message: %s' % msg)

        if msg == '':
            break

        if msg.startswith('PING'):
            reply = msg.replace('PING', 'PONG')
            await send(stream, reply)
        
        if any(msg[1:].startswith(x) for x in COMMANDERS):
            msg_from_commander = msg.split(':')
            command = msg_from_commander[-1]

            if command.startswith('!say'):
                cmd = command.strip().split(' ')
                target, speech = cmd[1], cmd[2:]
                await say(stream, target, ' '.join(speech))

            elif command.startswith('!join'):
                await join(stream, command[6:])


if __name__ == '__main__':
    trio.run(main)