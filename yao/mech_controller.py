#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Aidan Gray (Aidan.Gray@idg.jhu.edu), José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-05-26
# @Filename: mech_controller.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import enum
import re
import warnings

from sdsstools.logger import SDSSLogger

from .exceptions import YaoUserWarning


__all__ = ["MechController"]


class ReplyCode(enum.Enum):
    """Reply error codes."""

    VALID = enum.auto()
    UNPARSABLE_RESPONSE = enum.auto()
    MISMATCHED_COMMAND_ID = enum.auto()
    INVALID_COMMAND_CHECKSUM = enum.auto()
    INVALID_REPLY_CHECKSUM = enum.auto()
    ERR_IN_REPLY = enum.auto()
    CONTROLLER_REBOOTED = enum.auto()
    REBOOT_ACKNOWLEDGED = enum.auto()


class SpecMechReply:
    """A valid response to a command to the specMech."""

    def __init__(self, raw: bytes):

        self.command_id = 0
        self.raw = raw

        self.code = ReplyCode.VALID

        self.reply_sentence: str = ""
        self.data: list[list[str]] = []

        self.parse()

    def __str__(self):
        return self.raw

    def __repr__(self):
        return f"<MechControlReply (raw={self.raw!r})>"

    @staticmethod
    def calculate_checksum(message: bytes):
        """Computes the checksum field for the NMEA protocol.

        The checksum is simple, just an XOR of all the bytes between the
        ``$`` and the ``*`` (not including the delimiters themselves),
        and written in hexadecimal.

        """

        match = re.match(rb"^\$?(?:(.*?)(?:\*(?:[0-9A-Za-z]+)?)?)$", message)
        if match is None:
            raise ValueError(f"Unparsable message {message!r}")

        message = match.group(1)

        checksum = 0
        for b in message:
            checksum ^= b

        return f"{checksum:0X}"

    @staticmethod
    def check_checksum(message: bytes):
        """Checks the checksum from a reply.

        Parameters
        ----------
        message
            The message to check. Must include the checksum ``*XX``.

        """

        match = re.match(rb"^(.+?)\*([0-9A-Fa-f]+)$", message, re.DOTALL)

        if match is None:
            raise ValueError(f"Cannot parse checksum in message {message!r}")

        data, checksum = match.groups()

        return checksum.decode() == SpecMechReply.calculate_checksum(data)

    def parse(self):
        """Parses the raw reply."""

        # Check if the the response indicates a reboot. ! only ever happens if
        # a reboot has occurred.
        if b"!" in self.raw:
            self.code = ReplyCode.CONTROLLER_REBOOTED
            return

        # Get only the part without telnet subnegotiations and without the
        # terminator.
        match1 = re.match(b"(?:\xff.+\xf0)?(.*?)\x00?\n?>", self.raw, re.DOTALL)

        if match1 is None or len(match1.groups()) != 1:
            self.code = ReplyCode.UNPARSABLE_RESPONSE
            return

        data = match1.group(1)

        # Check if the the response indicates a reboot.
        if data == b"":
            self.code = ReplyCode.REBOOT_ACKNOWLEDGED
            return

        match2 = re.match(rb"(\$S2CMD.+?)\r(?:\x00?\n(.+)\r)?", data, re.DOTALL)

        if match2 is None or len(match2.groups()) != 2:
            self.code = ReplyCode.UNPARSABLE_RESPONSE
            return

        cmd, replies = match2.groups()

        if not self.check_checksum(cmd):
            self.code = ReplyCode.INVALID_COMMAND_CHECKSUM
            return

        match_command_id = re.match(rb".+?;([0-9])+\*", cmd)
        if match_command_id is None:
            warnings.warn(
                f"Failed matching command ID in command echo {cmd!r}",
                YaoUserWarning,
            )
        else:
            self.command_id = int(match_command_id.group(1))

        # The reply is only an echo of the command, without additional data.
        if replies is None:
            return

        reply_list = re.split(b"\r\x00\n", replies)

        for reply in reply_list:
            if not self.check_checksum(reply):
                self.code = ReplyCode.INVALID_REPLY_CHECKSUM
                return

            match3 = re.match(rb"^\$S2([A-Za-z]+),(.+?)\*[0-9A-Fa-f]+$", reply)

            if match3 is None or len(match2.groups()) != 2:
                self.code = ReplyCode.UNPARSABLE_RESPONSE
                return

            sentence, data_pack = match3.groups()
            if sentence == b"ERR":
                self.code = ReplyCode.ERR_IN_REPLY

            self.sentence = sentence.decode()

            # The data includes the sentence and the timestamp.
            self.data.append([f"S2{self.sentence}"] + data_pack.decode().split(","))


class MechController:
    """Controller for the spectrograph mechanics.

    The `.MechController` handles the connection to the spectrograph
    mechanics microcontroller. A description of the communication
    protocol is available `here <https://bit.ly/38Xn2VE>`__.

    Parameters
    ----------
    address
        The IP address or host of the mech server.
    port
        The port of the host of the mech server.
    log
        A logger to which to write.

    """

    def __init__(self, address: str, port: int = 23, log: SDSSLogger | None = None):

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        self.reboot: bool = False
        self.command_number: int = 0

        self.log = log or SDSSLogger("boss-spech-mech-client")

        self.spechMechAddress = address
        self.specMechPort = port

        self.lock = asyncio.Lock()

    async def start(self):
        """Opens a connection with the given IP and port."""

        self.log.info(
            f"Opening connection with {self.spechMechAddress} "
            f"on port {self.specMechPort}"
        )

        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self.log.asyncio_exception_handler)

        self.reader, self.writer = await asyncio.open_connection(
            self.spechMechAddress,
            self.specMechPort,
        )

    async def send_data(self, command: str, timeout: float = 1):
        """Sends the given string to the specMech and then awaits a response.

        Currently when a command is sent the controller is locked and any
        new command is blocked until a reply for the currenly running command
        arrives or a timeout happens.

        Parameters
        ----------
        command
            A string that is sent to specMech.
        timeout
            How long to wait for replies.

        Returns
        -------
        replies
            A tuple in which the first element is bytes array with the raw reply,
            and successive items are tuples with the data associated with each
            reply. If a timeout occurred before

        """

        # Only send '!\r' to acknowledge a reboot
        if command == "!":
            commandFinal = command + "\r"
        else:
            # Increment command number
            self.command_number += 1

            # Add command identifier to the command
            commandFinal = command + ";" + str(self.command_number) + "\r"

        # Send the command
        self.log.debug(f"Sent to specMech: {commandFinal!r}")

        if self.writer is None:
            raise RuntimeError("SpecMech client not connected.")

        async with self.lock:
            self.writer.write(commandFinal.encode())
            reply = await self.read_data()

        return reply

    async def read_data(self):
        """Awaits responses from specMech until the EOM character '>' is seen.

        Returns
        -------
        mech_reply
            A `.SpecMechReply` object with the reply received.

        """

        if self.reader is None:
            raise RuntimeError("SpecMech client not connected.")

        dataRaw = await self.reader.read(1024)

        # Continue accepting responses until '>' is received
        while b">" not in dataRaw and b"!" not in dataRaw:
            dataRawTmp = await self.reader.read(1024)
            dataRaw = dataRaw + dataRawTmp

        self.log.debug(f"Received from specMech: {dataRaw!r}")

        reply = SpecMechReply(dataRaw)

        if reply.code == ReplyCode.CONTROLLER_REBOOTED:
            self.reboot = True
        else:
            self.reboot = False

        return reply

    async def close(self):
        """Closes the connection with specMech."""

        self.log.info("Closing the connection to the specMech.")

        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()
