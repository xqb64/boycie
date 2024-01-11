from pathlib import Path
import asks
import re
import trio
import datetime
import logging
import base64
import os
from dataclasses import dataclass


@dataclass
class Commander:
    nick: str
    ident: str
    hostname: str

    def __str__(self):
        return f"{self.nick}!{self.ident}@{self.hostname}"


commander = Commander(nick="adder", ident="~adder", hostname="user/adder")

COMMANDS: list[str] = ["!say", "!join", "!start_lesson", "!end_lesson"]

AUTOJOIN_CHANNELS: list[str] = ["##learnmath"]

NETWORK = "irc.libera.chat"
PORT = 6697
NICK = "boycie"
REAL_NAME = "Boycie"
USER_NAME = "boycie"

TERMINATOR = b"\r\n"

WORKING_DIR: Path = Path("/home") / "alex" / ".boycie"

PASSWORD: str = os.environ["BOYCIE_PASSWORD"]

credentials: str = f"{NICK}\0{NICK}\0{PASSWORD}"
encoded_credentials: str = base64.b64encode(credentials.encode()).decode()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(f"{WORKING_DIR}/boycie.log"),
        logging.StreamHandler(),
    ],
)


logger: logging.Logger = logging.getLogger(__name__)


def _contains_complete_msg(buffer: bytearray) -> bool:
    return TERMINATOR in buffer


async def say(stream, target: str, message: str) -> None:
    await send(stream, "PRIVMSG %s :%s" % (target, message))


async def join(stream, channel: str) -> None:
    await send(stream, "JOIN %s" % channel)


async def send(stream, message: str) -> None:
    message = message.encode("UTF-8")
    await stream.send_all(message + TERMINATOR)


async def recv_msg(stream, buffer: bytearray) -> bytes:
    while True:
        if _contains_complete_msg(buffer):
            break
        chunk = await stream.receive_some()
        buffer.extend(chunk)

    msg_boundary = buffer.index(TERMINATOR)
    msg = buffer[:msg_boundary]

    del buffer[: len(msg + TERMINATOR)]

    return bytes(msg)


def is_command(msg: str) -> bool:
    return msg in COMMANDS


def prettyprint_timedelta(start: datetime.datetime, end: datetime.datetime) -> str:
    delta = end - start
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours} hours, {minutes} minutes, {seconds} seconds"


def extract_possible_links(msg: str) -> list:
    links = []
    while True:
        match = re.search("(?P<url>https?://[^\s]+)", msg)
        if match:
            links.append(match.group("url"))
            msg = msg[match.end("url") :]
        else:
            break
    return links


def is_image(link: str) -> bool:
    return link.endswith(".png") or link.endswith(".jpg") or link.endswith(".jpeg")


async def download_image(link: str) -> None:
    response = await asks.get(link)
    # e.g. turn this:
    # https://upload.wikimedia.org/wikipedia/.../440px-Transformer3d_col3.svg.png
    # into this: 440px-Transformer3d_col3.svg.png
    filename = link.split("/")[-1]
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    with open(WORKING_DIR / date / filename, "wb") as f:
        f.write(response.content)


async def main() -> None:
    buffer = bytearray()
    stream = await trio.open_ssl_over_tcp_stream(NETWORK, PORT)

    logger.info("Authenticating...")

    await send(stream, "CAP REQ :sasl")
    await send(stream, "AUTHENTICATE PLAIN")
    await send(
        stream, "AUTHENTICATE {credentials}".format(credentials=encoded_credentials)
    )
    await send(stream, "CAP END")

    logger.info("Authentication completed.")

    await send(stream, "NICK %s" % NICK)
    await send(stream, "USER %s * 0: %s" % (USER_NAME, REAL_NAME))

    logger.info("Connected to %s:%s" % (NETWORK, PORT))

    # autojoin channels, if any
    for channel in AUTOJOIN_CHANNELS:
        await join(stream, channel)
        logger.info("Joined %s" % channel)

    lesson_start = None

    f = None

    while True:
        msg = await recv_msg(stream, buffer)
        msg = msg.decode("UTF-8").strip()

        # msg example:
        # :adder!~adder@user/adder PRIVMSG ##learnmath :!start_lesson

        logger.info(msg)

        if msg == "":
            logger.info("Connection closed")
            break

        # autoreply to pings
        if msg.startswith("PING"):
            reply = msg.replace("PING", "PONG")
            logger.debug("PONG")
            await send(stream, reply)

        # if we're in a lesson, log the chat
        if f is not None:
            split = msg.split(" :")
            # split: [':adder!~adder@user/adder PRIVMSG ##learnmath', '!start_lesson']

            user = split[0].lstrip(":").split("!")[0]
            # user: adder

            clean_msg = ":".join(split[1:])
            # clean_msg: !start_lesson

            if not is_command(clean_msg):
                # write to file and flush immediately since we don't want
                # to lose any data if the bot dies
                f.write(f"<{user}> {clean_msg}\n")
                f.flush()

                # check for links
                links = extract_possible_links(clean_msg)
                for link in links:
                    if is_image(link):
                        logger.info("Downloading image: %s" % link)
                        await download_image(link)

        # if the message is from a commander, check if it's a command
        if msg[1:].startswith(str(commander)):
            msg_from_commander = msg.split(":")
            command = msg_from_commander[-1]

            logger.info("Message from commander: %s" % command)

            if command.startswith("!say"):
                cmd = command.strip().split(" ")
                target, speech = cmd[1], cmd[2:]
                await say(stream, target, " ".join(speech))

            elif command.startswith("!join"):
                await join(stream, command[6:])

            elif command.startswith("!start_lesson"):
                channel = msg.split(" ")[2]

                await say(stream, channel, "ok")

                lesson_start = datetime.datetime.now()
                date = datetime.datetime.now().strftime("%Y-%m-%d")

                (WORKING_DIR / date).mkdir(exist_ok=True)

                f = open(f"{WORKING_DIR}/{date}/lesson.txt", "w")

                logger.info("Lesson started")

            elif command.startswith("!end_lesson"):
                channel = msg.split(" ")[2]
                lesson_end = datetime.datetime.now()

                await say(
                    stream,
                    channel,
                    "ok: %s" % prettyprint_timedelta(lesson_start, lesson_end),
                )

                f.close()
                f = None

                logger.info("Lesson ended")


if __name__ == "__main__":
    trio.run(main)
