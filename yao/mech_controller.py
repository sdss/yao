#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Aidan Gray (Aidan.Gray@idg.jhu.edu), José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-05-26
# @Filename: mech_controller.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio

import telnetlib3

from sdsstools.logger import SDSSLogger


__all__ = ["MechController"]


class MechController:
    def __init__(self, address: str, port: int = 23, log: SDSSLogger | None = None):

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        self.response: str = ">"
        self.reboot: bool = False
        self.commandNumber: int = 0
        self.commandQueue: list[dict] = []

        self.log = log or SDSSLogger("boss-spech-mech-client")

        self.spechMechAddress = address
        self.specMechPort = port

    async def start(self):
        """Opens a connection with the given IP and port."""

        self.log.info(
            f"Opening connection with {self.spechMechAddress} "
            f"on port {self.specMechPort}"
        )

        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self.log.asyncio_exception_handler)

        telTask = asyncio.create_task(
            telnetlib3.open_connection(self.spechMechAddress, self.specMechPort)
        )
        self.reader, self.writer = await telTask

    async def send_data(self, message: str):
        """Sends the given string to the specMech and then awaits a response.

        Parameters
        ----------
        message
            A string that is sent to specMech

        """

        # Only send '!\r' to acknowledge a reboot
        if message == "!":
            messageFinal = message + "\r"
        else:
            # Increment commandNumber, add the command + id to the queue
            self.commandNumber += 1
            self.commandQueue.append({"id": self.commandNumber, "command": message})

            # Add command identifier to the message
            messageFinal = message + ";" + str(self.commandNumber) + "\r"

        # Send the message
        self.log.debug(f"Sent to specMech: {messageFinal!r}")

        if self.writer is None:
            raise RuntimeError("SpecMech client not connected.")

        self.writer.write(messageFinal.encode())
        await self.read_data()

    async def read_data(self):
        """Awaits responses from specMech until the EOM character '>' is seen.

        The data received from specMech is added to the response variable.

        """

        if self.reader is None:
            raise RuntimeError("SpecMech client not connected.")

        dataRaw = (await self.reader.read(1024)).decode()

        # Continue accepting responses until '>' is received
        while ">" not in dataRaw and "!" not in dataRaw:
            dataRawTmp = (await self.reader.read(1024)).decode()
            dataRaw = dataRaw + dataRawTmp

        if dataRaw == "!":
            self.reboot = True
        else:
            self.reboot = False

        self.response = dataRaw

        self.log.debug(f"Received from specMech: {self.response!r}")

        self.pop_from_queue()

    def pop_from_queue(self):
        """Removes done commands from the queue."""

        statusList = self.response.split("\r\x00\n")

        strpList = []
        for n in statusList:  # separate the individual status responses
            if "$S1" in n:
                tempStr1 = n[3:]  # remove '$S1'
                tempStr2 = tempStr1.split("*")[0]  # remove the NMEA checksum
                strpList.append(tempStr2)

        finalList = []
        for m in strpList:  # for each status response, split up the components
            finalList.append(m.split(","))

        if len(finalList) != 0:
            try:
                # get last part of response
                tmpCMDid = int(finalList[0][len(finalList[0]) - 1])
            except ValueError:
                raise ValueError("Internal Command Queue Error")

            n = 0
            for cmd in self.commandQueue:
                if cmd["id"] == tmpCMDid:
                    self.commandQueue.pop(n)
                n += 1

    async def close(self):
        """Closes the connection with specMech."""

        self.log.info("Closing the connection to the specMech.")

        if self.writer is not None:
            await self.send_data("q\r\n")

            self.writer.close()
            await self.writer.wait_closed()
