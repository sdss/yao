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


async def check_controller(command: YaoCommand) -> bool:
    """Performs sanity check in the controller.

    Outputs error messages if a problem is found. Return `False` if the controller
    is not in a valid state.

    """

    mech = command.actor.spec_mech

    if not mech.is_connected():
        command.fail(error="specMech controller not connected.")
        return False

    try:
        await mech.send_data("rt", timeout=3)
    except asyncio.TimeoutError:
        command.fail(error="specMech timed out replying.")
        return False

    return True


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


@parser.group()
def mech(*args):
    """Interface to the specMech controller."""

    pass


# Values to output if a stat fails.
FAILED_STAT_REPLIES = {
    "nitrogen": ["?", "?", "?", "?", -999, -999, -999, -999, "?", "?", "?", "?"],
    "motor-a": ["a", -999, -999, -999, -999, False],
    "motor-b": ["b", -999, -999, -999, -999, False],
    "motor-c": ["c", -999, -999, -999, -999, False],
    "motors": [-999, -999, -999],
    "environment": [-999.0] * 7,
    "orientation": [-999.0] * 3,
    "pneumatics": ["?"] * 4,
    "time": ["?"] * 3,
    "version": ["?"],
    "vacuum": [-999.0, -999.0],
    "specmech": ["?", -999.0],
}


@mech.command()
@click.argument("STAT", type=click.Choice(list(STATS)), required=False)
@click.option("-d", "--debug", is_flag=True, help="Uses debug status in outputs..")
async def status(
    command: YaoCommand,
    controllers,
    stat: str | None = None,
    debug: bool = False,
):
    """Queries specMech for all status responses."""

    if not (await check_controller(command)):
        return

    if stat is None:
        process_stats = list(STATS)
    else:
        process_stats = [stat.lower()]

    if debug:
        write_func = command.debug
    else:
        write_func = command.info

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
            pos, vel, current, _, limit = values[1:]
            write_func(
                message={this_stat.replace("-", "_"): [pos, vel, current, limit]}
            )

            if limit is True:
                motor = this_stat[-1].upper()
                command.warning(f"Motor {motor}: limit switch has been triggered!")

        elif this_stat == "motors":
            write_func(motor_positions=values)

        elif this_stat == "environment":
            write_func(
                temperature_blue=values[0],
                humidity_blue=values[1],
                temperature_red=values[2],
                humidity_red=values[3],
                temperature_collimator=values[4],
                humidity_collimator=values[5],
                specMech_temp=values[6],
            )

        elif this_stat == "orientation":
            write_func(accelerometer=values)

        elif this_stat == "pneumatics":
            write_func(
                shutter=values[0],
                hartmann_left=values[1],
                hartmann_right=values[2],
                air_pressure=values[3],
            )

        elif this_stat == "time":
            write_func(boot_time=values[0], clock_time=values[1], set_time=values[2])

        elif this_stat == "version":
            write_func(specMech_version=values[0])

        elif this_stat == "vacuum":
            write_func(
                vacuum_red_log10_pa=values[0],
                vacuum_blue_log10_pa=values[1],
            )

        elif this_stat == "specmech":
            write_func(
                fan=values[0],
                power_supply_volts=values[1],
            )

        elif this_stat == "nitrogen":
            write_func(
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
    "--center",
    is_flag=True,
    help="Send the motors to their home positions.",
)
@click.option(
    "--center-position",
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
    center: bool = False,
    center_position: int = 1500,
):
    """Commands the collimator motors.

    Without flags moves are relative from the current position and move all
    motors concurrently.

    """

    if not (await check_controller(command)):
        return

    if absolute is True and motor is None:
        return command.fail("--absolute requires specifying --motor.")

    if center is False and position is None:
        return command.fail("POSITION is required except with --center.")

    current = numpy.array([0, 0, 0], dtype=numpy.int16)

    minP_expected = command.actor.config["specMech"]["motors"]["minP"]
    maxP_expected = command.actor.config["specMech"]["motors"]["maxP"]

    try:
        for ii, motor_ in enumerate(["a", "b", "c"]):
            data = await command.actor.spec_mech.get_stat(f"motor-{motor_}")

            _, pos, vel, _, _, limit = data
            if vel != 0:
                raise SpecMechError(f"Motor {motor_} is moving.")
            if limit is True:
                raise SpecMechError(f"A limit switch was triggered for motor {motor_}.")
            current[ii] = pos

        for ii, motor_ in enumerate(["a", "b", "c"]):
            reply = await command.actor.spec_mech.send_data(f"r{motor_.upper()}")
            check_reply(reply)

            dmm = reply.data[3]
            if dmm[0] != "DMM":
                raise SpecMechError("Cannot retrieve DMM status.")

            minP = int(dmm[5])
            maxP = int(dmm[7])
            if minP != minP_expected or maxP != maxP_expected:
                raise SpecMechError("Min/max encoder positions out of range.")

    except SpecMechError as err:
        return command.fail(str(err))

    mech_commands: list[str]

    if center is True:
        position = center_position
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

    min_range = command.actor.config["specMech"]["motors"]["min_microns"]
    max_range = command.actor.config["specMech"]["motors"]["max_microns"]
    if numpy.any(final < min_range) or numpy.any(final > max_range):
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

    if not (await check_controller(command)):
        return

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

    if not (await check_controller(command)):
        return

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

    if not (await check_controller(command)):
        return

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

    if not (await check_controller(command)):
        return

    jobs = []

    for mechanism in mechanisms:
        jobs.append(
            command.actor.spec_mech.pneumatic_move(
                mechanism,
                open=True,
                command=command,
            )
        )

    results = await asyncio.gather(*jobs, return_exceptions=True)
    for result in results:
        if isinstance(result, SpecMechError):
            return command.fail(str(result))

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

    if not (await check_controller(command)):
        return

    jobs = []

    for mechanism in mechanisms:
        jobs.append(
            command.actor.spec_mech.pneumatic_move(
                mechanism,
                open=False,
                command=command,
            )
        )

    results = await asyncio.gather(*jobs, return_exceptions=True)
    for result in results:
        if isinstance(result, SpecMechError):
            return command.fail(str(result))

    return command.finish()


@mech.command()
async def reboot(command: YaoCommand, controller):
    """Reboots the controller. A reconnect and acknowledge are needed afterewards."""

    if not (await check_controller(command)):
        return

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

    try:
        await command.actor.spec_mech.close()
    except OSError:
        pass

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

    if not (await check_controller(command)):
        return

    if mode == "on":
        mech_command = "sf+"
    else:
        mech_command = "sf-"

    reply = await command.actor.spec_mech.send_data(mech_command)

    if not parse_reply(command, reply):
        return

    return command.finish(fan="on" if mode == "on" else "off")
