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

from typing import TYPE_CHECKING, Any

from sdsstools.logger import SDSSLogger

from yao import config

from .exceptions import SpecMechError, YaoUserWarning


if TYPE_CHECKING:
    from .actor import YaoCommand


__all__ = ["MechController", "ReplyCode", "SpecMechReply", "STATS", "check_reply"]


#: Stat names accepted by the report command.
STATS: dict[str, str] = {
    "time": "rt",
    "version": "rV",
    "environment": "re",
    "vacuum": "rv",
    "motors": "rd",
    "motor-a": "ra",
    "motor-b": "rb",
    "motor-c": "rc",
    "orientation": "ro",
    "pneumatics": "rp",
    # "nitrogen": "rn",
    "specmech": "rs",
}


def check_reply(reply: SpecMechReply):
    """Checks a specMech reply."""

    if reply.code == ReplyCode.ERR_IN_REPLY:
        for reply_data in reply.data:
            if "ERR" in reply_data[0]:
                code, msg = reply_data[1:]
                raise SpecMechError(f"Error {code} found in specMech reply: {msg!r}.")

    if reply.code == ReplyCode.CONTROLLER_REBOOTED:
        raise SpecMechError(
            "The specMech controller has rebooted. "
            "Acknowledge the reboot before continuing."
        )

    if reply.code == ReplyCode.CONNECTION_FAILED:
        raise SpecMechError("The connection to the specMech failed. Try reconnecting.")

    if reply.code != ReplyCode.VALID and reply.code != ReplyCode.REBOOT_ACKNOWLEDGED:
        raise SpecMechError(f"Failed parsing specMech reply: {reply.code.name!r}.")


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
    CONNECTION_FAILED = enum.auto()


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

        return f"{checksum:02X}"

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

            match3 = re.match(rb"^\$S2([A-Za-z0-9]+),(.+?)\*[0-9A-Fa-f]+$", reply)

            if match3 is None or len(match2.groups()) != 2:
                self.code = ReplyCode.UNPARSABLE_RESPONSE
                return

            sentence, data_pack = match3.groups()
            if sentence == b"ERR":
                self.code = ReplyCode.ERR_IN_REPLY

            # The data includes the sentence and the timestamp.
            self.data.append([sentence.decode()] + data_pack.decode().split(","))


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

        connect = asyncio.open_connection(self.spechMechAddress, self.specMechPort)
        self.reader, self.writer = await asyncio.wait_for(connect, timeout=3)

    def is_connected(self):
        """Checks if we are connected to the specMech."""

        if not self.writer:
            return False

        return not self.writer.is_closing()

    async def send_data(self, command: str, timeout: float | None = None):
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

        try:
            if self.writer is None:
                raise ConnectionResetError("SpecMech client not connected.")

            async with self.lock:
                self.writer.write(commandFinal.encode())
                reply = await asyncio.wait_for(self.read_data(), timeout)

        except ConnectionResetError:
            reply = SpecMechReply(b"")
            reply.code = ReplyCode.CONNECTION_FAILED

            self.writer = None
            self.reader = None

        return reply

    async def read_data(self):
        """Awaits responses from specMech until the EOM character '>' is seen.

        Returns
        -------
        mech_reply
            A `.SpecMechReply` object with the reply received.

        """

        if self.reader is None:
            raise ConnectionResetError("SpecMech client not connected.")

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

        self.writer = None
        self.reader = None

    async def get_stat(self, stat: str) -> tuple[Any, ...]:
        """Returns the output of the report commands.

        Parameters
        ----------
        stat
            The report stat to recover. One of `.STATS`.

        Returns
        -------
        reply
            The parsed command reply values.

        """

        stat = stat.lower()

        if stat in STATS:
            mech_command = STATS[stat]
        else:
            raise SpecMechError(f"Invalid specMech stat {stat!r}.")

        reply = await self.send_data(mech_command)
        check_reply(reply)

        values = reply.data[0]

        if values[0] == "MTR":
            if stat.startswith("motor-"):
                # Only one reply.
                mtr = values[2]
                mtrPosition = int(values[3])
                mtrSpeed = int(values[5])
                mtrCurrent = int(values[7])
                mtrDirection = values[9]
                mtrLimit = True if values[11] == "Y" else False
                return (mtr, mtrPosition, mtrSpeed, mtrCurrent, mtrDirection, mtrLimit)
            elif stat == "motors":
                # This is the only case in which we have multiple replies.
                # Return only the positions as floats.
                positions = []
                for d in reply.data:
                    positions.append(int(d[3]))
                return tuple(positions)

            else:
                raise SpecMechError("Invalid stat for MTR reply.")

        elif values[0] == "ENV":
            env0T = float(values[2])
            env0H = float(values[4])
            env1T = float(values[6])
            env1H = float(values[8])
            env2T = float(values[10])
            env2H = float(values[12])
            specMechT = float(values[14])
            return (env0T, env0H, env1T, env1H, env2T, env2H, specMechT)

        elif values[0] == "ORI":
            accx = float(values[2])
            accy = float(values[3])
            accz = float(values[4])
            return (accx, accy, accz)

        elif values[0] == "PNU":
            # change the c/o/t and 0/1 responses of specMech
            # to something more readable
            if values[2] == "c":
                pnus = "closed"
            elif values[2] == "o":
                pnus = "open"
            else:
                pnus = "transiting"

            if values[4] == "c":
                pnul = "closed"
            elif values[4] == "o":
                pnul = "open"
            else:
                pnul = "transiting"

            if values[6] == "c":
                pnur = "closed"
            elif values[6] == "o":
                pnur = "open"
            else:
                pnur = "transiting"

            if values[8] == "0":
                pnup = "off"
            else:
                pnup = "on"

            return (pnus, pnul, pnur, pnup)

        elif values[0] == "TIM":
            tim = values[1]
            stim = values[2]
            btm = values[4]
            return (btm, tim, stim)

        elif values[0] == "VER":
            ver = values[2]
            return (ver,)

        elif values[0] == "VAC":
            red = float(values[2])
            blue = float(values[4])
            return (red, blue)

        elif values[0] == "LN2":
            valves = []
            for valve_status in values[2]:
                if valve_status.upper() == "C":
                    valves.append("closed")
                elif valve_status.upper() == "O":
                    valves.append("open")
                elif valve_status.upper() == "T":
                    valves.append("timeout")
                elif valve_status.upper() == "X":
                    valves.append("disabled")
                else:
                    valves.append("?")

            (
                buffer_dewar_supply_status,
                buffer_dewar_vent_status,
                red_dewar_vent_status,
                blue_dewar_vent_status,
            ) = valves

            time_next_fill = int(values[3])
            max_valve_open_time = int(values[5])
            fill_interval = int(values[7])
            ln2_pressure = int(values[9])

            if values[11].upper() == "C":
                buffer_dewar_thermistor_status = "cold"
            elif values[11].upper() == "H":
                buffer_dewar_thermistor_status = "warm"
            else:
                buffer_dewar_thermistor_status = "?"

            if values[13].upper() == "C":
                red_dewar_thermistor_status = "cold"
            elif values[13].upper() == "H":
                red_dewar_thermistor_status = "warm"
            else:
                red_dewar_thermistor_status = "?"

            if values[15].upper() == "C":
                blue_dewar_thermistor_status = "cold"
            elif values[15].upper() == "H":
                blue_dewar_thermistor_status = "warm"
            else:
                blue_dewar_thermistor_status = "?"

            return (
                buffer_dewar_supply_status,
                buffer_dewar_vent_status,
                red_dewar_vent_status,
                blue_dewar_vent_status,
                time_next_fill,
                max_valve_open_time,
                fill_interval,
                ln2_pressure,
                buffer_dewar_thermistor_status,
                red_dewar_thermistor_status,
                blue_dewar_thermistor_status,
            )

        elif "specmech":
            fan = "on" if int(values[2]) else "off"
            volts = float(values[4])
            return (fan, volts)

        else:
            raise SpecMechError(f"Invalid reply sentence {values[0]}.")

    async def pneumatic_move(
        self,
        mechanism: str,
        open: bool = True,
        command: YaoCommand | None = None,
    ):
        """Opens/closes a pneumatic mechanism.

        Parameters
        ----------
        mechanism
            Either ``shutter``, ``left``, or ``right``.
        open
            If `True`, opens the mechanism, otherwise closes it.
        command
            An actor command for outputs.

        """

        if mechanism == "left":
            spec_command = "ol" if open else "cl"
        elif mechanism == "right":
            spec_command = "or" if open else "cr"
        elif mechanism == "shutter":
            spec_command = "os" if open else "cs"
        else:
            raise SpecMechError(f"Invalid mechanism {mechanism!r}.")

        reply = await self.send_data(spec_command)
        check_reply(reply)

        # Check that all the mechanisms have arrived to their desired position.
        # Try twice, then fail.

        for ii in [1, 2]:
            await asyncio.sleep(config["timeouts"]["pneumatics"])

            reached = True

            status = await self.send_data("rp")
            try:
                check_reply(status)
            except SpecMechError as err:
                raise SpecMechError(
                    "Failed checking the status of the "
                    f"pneumatics after a move: {err}"
                )

            if mechanism == "shutter":
                mech_position = status.data[0][2]
            elif mechanism == "left":
                mech_position = status.data[0][4]
            elif mechanism == "right":
                mech_position = status.data[0][6]
            else:
                continue

            destination = "open" if open else "closed"
            if mech_position != destination[0]:
                reached = False

            if reached is True:
                if command:
                    mech_key = mechanism
                    if mechanism in ["left", "right"]:
                        mech_key = "hartmann_" + mech_key
                    command.info(message={mech_key: destination})
                return True

            if ii == 1:
                if command:
                    command.warning(
                        "Pneumatics did not reach the desired position. "
                        "Waiting a bit longer ..."
                    )
            else:
                if command:
                    await command.send_command("yao", "mech status pneumatics")
                raise SpecMechError("Pneumatics did not reach the desired position.")

        # We should never get here.
        raise SpecMechError

    async def pneumatic_status(self, mechanism: str) -> str:
        """Returns the open/closed status of a mechanism."""

        mechanism = mechanism.lower()
        if mechanism not in ["shutter", "left", "right"]:
            raise SpecMechError(f"Invalid mechanism {mechanism!r}.")

        status = await self.get_stat("pneumatics")

        if mechanism == "shutter":
            return status[0]
        elif mechanism == "left":
            return status[1]
        else:
            return status[2]
