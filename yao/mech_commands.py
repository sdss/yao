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
import numpy
import numpy.typing

from archon.actor import parser

from yao.exceptions import SpecMechError
from yao.mech_controller import STATS, ReplyCode, check_reply


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

    try:
        check_reply(reply)
    except SpecMechError as err:
        write_func(str(err))
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


# Values to output if a stat fails.
FAILED_STAT_REPLIES = {
    "nitrogen": ["?", "?", "?", "?", -999, -999, -999, -999, "?", "?", "?", "?"],
    "motor-a": ["a", "?", "?", "?"],
    "motor-b": ["b", "?", "?", "?"],
    "motor-c": ["c", "?", "?", "?"],
    "motors": [-999, -999, -999],
    "environment": [-999.0] * 6,
    "orientation": [-999.0] * 3,
    "pneumatics": ["?"] * 4,
    "time": ["?"] * 3,
    "version": ["?"],
    "vacuum": [-999.0, -999.0],
    "specmech": ["?", -999.0],
}


@mech.command()
@click.argument("STAT", type=click.Choice(list(STATS)), required=False)
async def status(command: YaoCommand, controllers, stat: str | None = None):
    """Queries specMech for all status responses."""

    if stat is None:
        process_stats = list(STATS)
    else:
        process_stats = [stat.lower()]

    for this_stat in process_stats:

        if this_stat not in STATS:
            return command.fail(f"Invalid specMech status command {this_stat!r}.")

        mech = command.actor.spec_mech

        try:
            values = await mech.get_stat(this_stat)
        except SpecMechError as err:
            command.error(str(err))
            if this_stat in FAILED_STAT_REPLIES:
                values = FAILED_STAT_REPLIES[this_stat]
            else:
                continue

        if this_stat.startswith("motor-"):
            command.info(message={this_stat.replace("-", "_"): values})

        elif this_stat == "motors":
            command.info(motor_positions=values)

        elif this_stat == "environment":
            command.info(
                temperature0=values[0],
                humidity0=values[1],
                temperature1=values[2],
                humidity1=values[3],
                temperature2=values[4],
                humidity2=values[5],
                specMech_temp=values[6],
            )

        elif this_stat == "orientation":
            command.info(accelerometer=values)

        elif this_stat == "pneumatics":
            command.info(
                shutter=values[0],
                hartmann_left=values[1],
                hartmann_right=values[2],
                air_pressure=values[3],
            )

        elif this_stat == "time":
            command.info(boot_time=values[0], clock_time=values[1], set_time=values[2])

        elif this_stat == "version":
            command.info(specMech_version=values[0])

        elif this_stat == "vacuum":
            command.info(
                vacuum_pump_red_dewar=values[0],
                vacuum_pump_blue_dewar=values[1],
            )

        elif this_stat == "specmech":
            command.info(
                fan=values[0],
                fan_volts=values[1],
            )

        elif this_stat == "nitrogen":
            command.info(
                buffer_dewar_supply_status=values[0],
                buffer_dewar_vent_status=values[1],
                red_dewar_vent_status=values[2],
                blue_dewar_vent_status=values[3],
                time_next_fill=values[4],
                max_valve_open_time=values[5],
                fill_interval=values[6],
                ln2_pressure=values[7],
                buffer_dewar_thermistor_status=values[8],
                red_dewar_thermistor_status=values[9],
                blue_dewar_thermistor_status=values[10],
            )

    return command.finish()


@mech.command()
@click.argument("POSITION", type=int, required=False)
@click.option(
    "--motor",
    type=click.Choice(["a", "b", "c"], case_sensitive=False),
    help="Move only this motor.",
)
@click.option(
    "--absolute",
    is_flag=True,
    help="Moves one motor to an absolute position.",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Waits until the motor has .",
)
@click.option(
    "--tolerance",
    default=2.0,
    type=float,
    help="Collimator positioning tolerance.",
)
@click.option(
    "--home",
    is_flag=True,
    help="Send the motors to their home positions.",
)
@click.option(
    "--home-position",
    default=1500.0,
    type=int,
    help="Absolute position for homing all the motors.",
)
async def move(
    command: YaoCommand,
    controllers,
    position: int | None = None,
    motor: str | None = None,
    absolute: bool = False,
    tolerance: float = 1.0,
    wait: bool = True,
    home: bool = False,
    home_position: int = 1500,
):
    """Commands the collimator motors.

    Without flags moves are relative from the current position and move all
    motors concurrently.

    """

    if home is False and position is None:
        return command.fail("POSITION is required except with --home.")

    current = numpy.array([0, 0, 0], dtype=numpy.int16)
    try:
        for ii, motor_ in enumerate(["a", "b", "c"]):
            _, pos, vel, _ = await command.actor.spec_mech.get_stat(f"motor-{motor_}")
            if vel != 0:
                return command.fail(f"Motor {motor_} is moving.")
            current[ii] = pos
    except SpecMechError as err:
        return command.fail(str(err))

    mech_commands: list[str]

    if home is True:
        position = home_position
        absolute = True

    if position is None:
        return command.fail("POSITION not defined.")

    if motor is None:
        if absolute is False:
            mech_commands = [f"md{position}"]
        else:
            mech_commands = [
                f"mA{position}",
                f"mB{position}",
                f"mC{position}",
            ]
    else:
        if absolute:
            mech_command = "m" + motor.upper()
        else:
            mech_command = "m" + motor.lower()
        mech_commands = [mech_command + str(position)]

    collimator_speed = 25  # mu/s

    final = current.copy()

    if motor is not None:
        motor_index = ord(motor) - ord("a")
        if absolute:
            final[motor_index] = position
        else:
            final[motor_index] += position
    else:
        if absolute:
            final[:] = position
        else:
            final[:] += position

    if numpy.any(final < 100) or numpy.any(final > 2900):
        return command.fail("Commanded motor position is out of range.")

    move_time = numpy.max(numpy.abs(current - final)) / collimator_speed

    for mech_command in mech_commands:
        move_command = await command.actor.spec_mech.send_data(mech_command)
        if not parse_reply(command, move_command):
            return

    if not wait:
        return command.finish()

    await asyncio.sleep(move_time + 2)

    for ntry in [1, 2]:
        new = await command.actor.spec_mech.get_stat("motors")
        if numpy.allclose(new, final, atol=tolerance):
            return command.finish(motor_positions=new)

        command.warning(motor_positions=new)
        if ntry == 1:
            command.warning("Collimator not at final position. Waiting a bit longer.")
            await asyncio.sleep(3)
        else:
            return command.fail("Collimator failed to reach commanded position.")


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

    return command.finish(mech_raw_reply=match.group(1).decode())


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
async def reboot(command: YaoCommand, controller):
    """Reboots the controller. A reconnect and acknowledge are needed afterewards."""

    dataTemp = "R"

    reply = await command.actor.spec_mech.send_data(dataTemp)

    if not parse_reply(command, reply):
        return

    return command.finish(
        "specMech has been rebooted. You need to reconnect and acknowledge."
    )


@mech.command()
async def reconnect(command: YaoCommand, controller):
    """Recreates the connection to the specMech."""

    await command.actor.spec_mech.close()

    await asyncio.sleep(2)

    try:
        await command.actor.spec_mech.start()
        if command.actor.spec_mech.writer is None:
            raise ConnectionError()
    except Exception as err:
        return command.fail(f"Failed reconnecting to the specMech: {err}")

    return command.finish("The connection to the specMech has been reestablished.")


@mech.command()
async def disconnect(command: YaoCommand, controller):
    """Closes the connection to the specMech."""

    await command.actor.spec_mech.close()

    return command.finish("The connection to the specMech has been closed.")


@mech.command()
@click.argument("MODE", type=click.Choice(["on", "off"], case_sensitive=False))
async def fan(command: YaoCommand, controller, mode: str):
    """Turns the speMech fan on/off."""

    if mode == "on":
        mech_command = "sf+"
    else:
        mech_command = "sf-"

    reply = await command.actor.spec_mech.send_data(mech_command)

    if not parse_reply(command, reply):
        return

    return command.finish(fan="on" if mode == "on" else "off")
