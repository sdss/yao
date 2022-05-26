#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-29
# @Filename: commands.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from typing import TYPE_CHECKING

import click
from clu.command import Command

from archon.actor import parser


if TYPE_CHECKING:
    from .actor import YaoActor


__all__ = []


YaoCommand = Command[YaoActor]


@parser.command()
@click.argument("SIDE", type=click.Choice(["left", "right"], case_sensitive=False))
@click.argument("EXPTIME", type=float)
async def hartmann(command: YaoCommand, controllers, side: str, exptime: float):
    """Takes a Hartmann image."""

    subcmd = await command.send_command(
        "yao",
        f"expose --arc --window-mode hartmann {exptime}",
    )

    # Reset default window.
    await command.send_command("yao", "set-window")

    if subcmd.status.did_fail:
        return command.fail("Failed taking Hartmann exposure.")
    return command.finish()


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
            "",
        ]
    ),
    required=False,
)
async def status(command: YaoCommand, stat: str | None = None):
    """Queries specMech for all status responses."""

    if stat == "time":
        dataTemp = "rt"
    elif stat == "version":
        dataTemp = "rV"
    elif stat == "environment":
        dataTemp = "re"
    elif stat == "vacuum":
        dataTemp = "rv"
    elif stat == "motor-a":
        dataTemp = "ra"
    elif stat == "motor-b":
        dataTemp = "rb"
    elif stat == "motor-c":
        dataTemp = "rc"
    elif stat == "orientation":
        dataTemp = "ro"
    elif stat == "pneumatics":
        dataTemp = "rp"
    else:
        dataTemp = "rs"

    mech = command.actor.spec_mech

    mech.response = ""
    await mech.send_data(dataTemp)

    if "$S1ERR" in mech.response:
        messageCode = "f"
        command.write(messageCode, text="ERR")
    elif mech.reboot:
        messageCode = "f"
        command.write(messageCode, text="SPECMECH HAS REBOOTED")
    else:
        messageCode = "i"

        # Parse the status response. Write a reply to the user for each relevant
        # status string. This may be changed later.
        statusList = mech.response.split("\r\x00\n")
        strpList = []

        for n in statusList:  # separate the individual status responses
            if "$S1" in n:
                tempStr1 = n[3:]  # remove '$S1'
                tempStr2 = tempStr1.split("*")[0]  # remove the NMEA checksum
                strpList.append(tempStr2)

        finalList = []
        for m in strpList:  # for each status response, split up the components
            finalList.append(m.split(","))

        for value in finalList:  # establish each keyword=value pair
            if value[0] == "MTR":
                mtr = value[2]
                mtrPosition = value[3]
                mtrPositionUnits = value[4]
                mtrSpeed = value[5]
                mtrSpeedUnits = value[6]
                mtrCurrent = value[7]
                mtrCurrentUnits = value[8]
                command.write(
                    messageCode,
                    motor=f"({mtr},{mtrPosition} {mtrPositionUnits},"
                    f"{mtrSpeed} {mtrSpeedUnits},"
                    f"{mtrCurrent} {mtrCurrentUnits})",
                )

            elif value[0] == "ENV":
                env0T = value[2] + " " + value[3]
                env0H = value[4] + " " + value[5]
                env1T = value[6] + " " + value[7]
                env1H = value[8] + " " + value[9]
                env2T = value[10] + " " + value[11]
                env2H = value[12] + " " + value[13]
                specMechT = value[14] + " " + value[15]
                command.write(
                    messageCode,
                    environments=f"(Temperature0={env0T}, Humidity0={env0H}, "
                    f"Temperature1={env1T}, Humidity1={env1H}, "
                    f"Temperature2={env2T}, Humidity2={env2H}, "
                    f"SpecMechTemp={specMechT})",
                )

            elif value[0] == "ORI":
                accx = value[2]
                accy = value[3]
                accz = value[4]
                command.write(
                    messageCode,
                    accelerometer=f"(xAxis={accx}, yAxis={accy}, zAxis={accz})",
                )

            elif value[0] == "PNU":
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

                command.write(
                    messageCode,
                    pneumatics=f"(shutter={pnus}, leftHartmann={pnul}, "
                    f"rightHartmann={pnur}, airPressure={pnup})",
                )

            elif value[0] == "TIM":
                tim = value[1]
                stim = value[2]
                btm = value[4]
                command.write(
                    messageCode,
                    timeInfo=f"(bootTime={btm}, clockTime={tim}, setTime={stim})",
                )

            elif value[0] == "VER":
                ver = value[2]
                command.write(messageCode, version=f"({ver})")

            elif value[0] == "VAC":
                red = value[2]
                blue = value[4]
                command.write(
                    messageCode, VacPumps=f"(redDewar={red}, blueDewar={blue})"
                )

        return command.finish()
