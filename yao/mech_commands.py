#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Aidan Gray (Aidan.Gray@idg.jhu.edu), José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-05-26
# @Filename: commands.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from archon.actor import parser

from yao.mech_controller import ReplyCode


if TYPE_CHECKING:
    from yao.mech_controller import SpecMechReply

    from .actor import YaoCommand


__all__ = ["mech"]


def parse_reply(command: YaoCommand, reply: SpecMechReply):
    """Parses a reply from the mech controller.

    If the reply indicates an error or that the controller has been rebooted,
    fails the command with an appropriate message and returns `False`.

    """

    if reply.code == ReplyCode.ERR_IN_REPLY:
        for reply_data in reply.data:
            if "ERR" in reply_data[0]:
                code, message = reply_data[1:]
                command.fail(f"Error {code} found in specMech reply: {message!r}.")
                break
        return False

    if reply.code == ReplyCode.CONTROLLER_REBOOTED:
        command.fail(
            "The specMech controller has rebooted. "
            "Acknowledge the reboot before continuing."
        )
        return False

    if reply.code != ReplyCode.VALID:
        command.fail(f"Failed parsing specMech reply with error {reply.code.name!r}.")
        return False

    return True


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
    required=False,
)
async def status(command: YaoCommand, _, stat: str | None = None):
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
        mech_command = "rs"

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
