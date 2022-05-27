#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Aidan Gray (Aidan.Gray@idg.jhu.edu), José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-05-26
# @Filename: commands.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import re

from typing import TYPE_CHECKING

import click

from archon.actor import parser

from yao.mech_controller import ReplyCode


if TYPE_CHECKING:
    from yao.mech_controller import SpecMechReply

    from .actor import YaoCommand


__all__ = ["mech"]


def parse_reply(command: YaoCommand, reply: SpecMechReply, fail: bool = True):
    """Parses a reply from the mech controller.

    If the reply indicates an error or that the controller has been rebooted,
    fails the command with an appropriate message and returns `False`.

    """

    if fail:
        write_func = command.fail
    else:
        write_func = command.error

    if reply.code == ReplyCode.ERR_IN_REPLY:
        for reply_data in reply.data:
            if "ERR" in reply_data[0]:
                code, message = reply_data[1:]
                write_func(f"Error {code} found in specMech reply: {message!r}.")
                break
        return False

    if reply.code == ReplyCode.CONTROLLER_REBOOTED:
        write_func(
            "The specMech controller has rebooted. "
            "Acknowledge the reboot before continuing."
        )
        return False

    if reply.code != ReplyCode.VALID and reply.code != ReplyCode.REBOOT_ACKNOWLEDGED:
        write_func(f"Failed parsing specMech reply with error {reply.code.name!r}.")
        return False

    return True


async def check_pneumatics_transition(
    command: YaoCommand, mechanisms: tuple[str, ...], destination: str
):
    """Checks that all the mechanisms have arrived to their desired position."""

    # Try twice, then fail.
    for ii in [1, 2]:
        await asyncio.sleep(command.actor.config["timeouts"]["pneumatics"])

        reached = True

        status = await command.actor.spec_mech.send_data("rp")
        if not parse_reply(command, status, fail=False):
            command.fail("Failed checking the status of the pneumatics after a move.")
            return False

        for mech in mechanisms:
            if mech == "shutter":
                mech_position = status.data[0][2]
            elif mech == "left":
                mech_position = status.data[0][4]
            elif mech == "shutter":
                mech_position = status.data[0][6]
            else:
                continue

            if mech_position != destination[0].lower():
                reached = False

        if reached is True:
            return True

        if ii == 1:
            command.warning(
                "Pneumatics did not reach the desired position. "
                "Waiting a bit longer ..."
            )
        else:
            command.fail("Pneumatics did not reach the desired position.")

    return False


@parser.group()
def mech(*args):
    """Interface to the specMech controller."""

    pass


@mech.command()
@click.argument(
    "STAT",
    type=click.Choice(
        [
            "time",
            "version",
            "environment",
            "vacuum",
            "motor-a",
            "motor-b",
            "motor-c",
            "orientation",
            "pneumatics",
        ]
    ),
    required=True,
)
async def status(command: YaoCommand, controllers, stat: str):
    """Queries specMech for all status responses."""

    if stat == "time":
        mech_command = "rt"
    elif stat == "version":
        mech_command = "rV"
    elif stat == "environment":
        mech_command = "re"
    elif stat == "vacuum":
        mech_command = "rv"
    elif stat == "motor-a":
        mech_command = "ra"
    elif stat == "motor-b":
        mech_command = "rb"
    elif stat == "motor-c":
        mech_command = "rc"
    elif stat == "orientation":
        mech_command = "ro"
    elif stat == "pneumatics":
        mech_command = "rp"
    else:
        return command.fail(f"Invalid specMech status command {stat!r}.")

    mech = command.actor.spec_mech

    reply = await mech.send_data(mech_command)

    if not parse_reply(command, reply):
        return

    for value in reply.data:
        if reply.sentence == "MTR":
            mtr = value[2]
            mtrPosition = value[3]
            mtrPositionUnits = value[4]
            mtrSpeed = value[5]
            mtrSpeedUnits = value[6]
            mtrCurrent = value[7]
            mtrCurrentUnits = value[8]
            command.info(
                motor=[
                    mtr,
                    f"{mtrPosition} {mtrPositionUnits}",
                    f"{mtrSpeed} {mtrSpeedUnits}",
                    f"{mtrCurrent} {mtrCurrentUnits})",
                ]
            )

        elif reply.sentence == "ENV":
            env0T = float(value[2])
            env0H = float(value[4])
            env1T = float(value[6])
            env1H = float(value[8])
            env2T = float(value[10])
            env2H = float(value[12])
            specMechT = float(value[14])
            command.info(
                temperature0=env0T,
                humidity0=env0H,
                temperature1=env1T,
                humidity1=env1H,
                temperature2=env2T,
                humidity2=env2H,
                specMechTemp=specMechT,
            )

        elif reply.sentence == "ORI":
            accx = float(value[2])
            accy = float(value[3])
            accz = float(value[4])
            command.info(accelerometer=[accx, accy, accz])

        elif reply.sentence == "PNU":
            # change the c/o/t and 0/1 responses of specMech
            # to something more readable
            if value[2] == "c":
                pnus = "closed"
            elif value[2] == "o":
                pnus = "open"
            else:
                pnus = "transiting"

            if value[4] == "c":
                pnul = "closed"
            elif value[4] == "o":
                pnul = "open"
            else:
                pnul = "transiting"

            if value[6] == "c":
                pnur = "closed"
            elif value[6] == "o":
                pnur = "open"
            else:
                pnur = "transiting"

            if value[8] == "0":
                pnup = "off"
            else:
                pnup = "on"

            command.info(
                shutter=pnus,
                hartmannLeft=pnul,
                hartmannRight=pnur,
                airPressure=pnup,
            )

        elif reply.sentence == "TIM":
            tim = value[1]
            stim = value[2]
            btm = value[4]
            command.info(bootTime=btm, clockTime=tim, setTime=stim)

        elif reply.sentence == "VER":
            ver = value[2]
            command.info(specMechVersion=ver)

        elif reply.sentence == "VAC":
            red = float(value[2])
            blue = float(value[4])
            command.info(vacuumPumpRedDewar=red, vacuumPumpBlueDewar=blue)

    return command.finish()


@mech.command()
async def ack(command: YaoCommand, controllers):
    """Acknowledges the specMech has rebooted and informs the user."""

    reply = await command.actor.spec_mech.send_data("!")

    if not parse_reply(command, reply):
        return

    if reply.code != ReplyCode.REBOOT_ACKNOWLEDGED:
        return command.fail("specMech did not acknowledge.")

    return command.finish("specMech has been acknowledged.")


@mech.command()
@click.argument("DATA", type=str)
async def talk(command: YaoCommand, controllers, data: str):
    """Send data string directly as-is to the specMech."""

    reply = await command.actor.spec_mech.send_data(data)

    # Remove telnet negotiations from raw string.
    match = re.match(b"^(?:\xff.+\xf0)?(.*)$", reply.raw, re.DOTALL)
    if not match:
        return command.fail("Failed parsing reply from specMech.")

    return command.finish(mechRawReply=match.group(1).decode())


@mech.command()
@click.argument("TIME", type=str)
async def set_time(command: YaoCommand, controller, time: str):
    """Set the clock time of the specMech."""

    dataTemp = f"st{time}"
    reply = await command.actor.spec_mech.send_data(dataTemp)

    if not parse_reply(command, reply):
        return

    return command.finish()


@mech.command(name="open")
@click.argument(
    "MECHANISMS",
    type=click.Choice(["left", "right", "shutter"], case_sensitive=False),
    nargs=-1,
    required=True,
)
async def openMech(command: YaoCommand, controller, mechanisms: tuple[str, ...]):
    """Opens left or right Hartmann doors, or the shutter."""

    jobs = []

    for mechanism in mechanisms:
        if mechanism == "left":
            dataTemp = "ol"
        elif mechanism == "right":
            dataTemp = "or"
        elif mechanism == "shutter":
            dataTemp = "os"
        else:
            return command.fail(f"Invalid mechanism {mechanism!r}.")

        jobs.append(command.actor.spec_mech.send_data(dataTemp))

    replies = await asyncio.gather(*jobs)

    for reply in replies:
        if not parse_reply(command, reply):
            return

    if not (await check_pneumatics_transition(command, mechanisms, "open")):
        return

    return command.finish()


@mech.command(name="close")
@click.argument(
    "MECHANISMS",
    type=click.Choice(["left", "right", "shutter"], case_sensitive=False),
    nargs=-1,
    required=True,
)
async def closeMech(command: YaoCommand, controller, mechanisms: tuple[str, ...]):
    """Closes left or right Hartmann doors, or the shutter."""

    jobs = []

    for mechanism in mechanisms:
        if mechanism == "left":
            dataTemp = "cl"
        elif mechanism == "right":
            dataTemp = "cr"
        elif mechanism == "shutter":
            dataTemp = "cs"
        else:
            return command.fail(f"Invalid mechanism {mechanism!r}.")

        jobs.append(command.actor.spec_mech.send_data(dataTemp))

    replies = await asyncio.gather(*jobs)

    for reply in replies:
        if not parse_reply(command, reply):
            return

    if not (await check_pneumatics_transition(command, mechanisms, "close")):
        return

    return command.finish()


@mech.command()
@click.argument("OFFSET", type=int)
async def focus(command: YaoCommand, controller, offset: int):
    """Send an offset to the specMech's 3 collimator motors."""

    dataTemp = f"md{offset}"

    reply = await command.actor.spec_mech.send_data(dataTemp)

    if not parse_reply(command, reply):
        return

    return command.finish()
