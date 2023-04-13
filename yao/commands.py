#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-29
# @Filename: commands.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from archon.actor import parser

from .exceptions import SpecMechError


if TYPE_CHECKING:
    from .actor import YaoCommand
    from .controller import YaoController


__all__ = ["hartmann"]


async def run_subcmd(command: YaoCommand, command_string: str):
    """Runs a subcommand and checks its completion."""

    subcmd = await command.child_command(command_string)
    if subcmd.status.did_fail:
        command.fail(f"Command {command_string} failed.")
        return False

    return True


@parser.command()
@click.argument("EXPTIME", type=float)
@click.option(
    "--side",
    "-s",
    type=click.Choice(["both", "left", "right"], case_sensitive=True),
    default="both",
    help="Position of the Hartmann door. With both, takes two arcs with different "
    "doors in.",
)
@click.option(
    "--sub-frame",
    is_flag=True,
    help="Read a subregion of the frame.",
)
async def hartmann(
    command: YaoCommand,
    _,
    exptime: float,
    side: str = "both",
    sub_frame: bool = False,
):
    """Takes Hartmann image(s)."""

    spec_mech = command.actor.spec_mech

    side_list: list[str]
    if side == "both":
        side_list = ["left", "right"]
    else:
        side_list = [side]

    try:
        for ss in side_list:
            other_side = "left" if ss == "right" else "right"

            command.debug(text=f"Taking {ss} Hartmann.")

            # Check that the side door is open or open it.
            status_side = await spec_mech.pneumatic_status(ss)
            if status_side == "transitioning":
                raise SpecMechError(f"Hartmann {ss} door is transitioning.")
            elif status_side == "open":
                if not (await run_subcmd(command, f"mech close {ss}")):
                    return

            # Check that the side door is closed or close it.
            status_other_side = await spec_mech.pneumatic_status(other_side)
            if status_other_side == "transitioning":
                raise SpecMechError(f"Hartmann {other_side} door is transitioning.")
            elif status_other_side == "closed":
                if not (await run_subcmd(command, f"mech open {other_side}")):
                    return

            expose_cmd: str = "expose --arc"
            if sub_frame:
                expose_cmd += " --window-mode hartmann"
            expose_cmd += f" {exptime}"

            if not (await run_subcmd(command, expose_cmd)):
                return

        # Open closed door.
        if not (await run_subcmd(command, "mech open right")):
            return

    except SpecMechError as err:
        return command.fail(error=f"SpecMech error: {err}")

    except Exception as err:
        return command.fail(error=f"Unexpected exception: {err}")

    finally:
        # Reset default window.
        await command.send_command("yao", "set-window")

    return command.finish()


@parser.command()
async def erase(command: YaoCommand, controllers: dict[str, YaoController]):
    """Runs the r2 erase routine."""

    for controller in controllers.values():
        command.info(f"Running erase routine on spectrograph {controller.name}.")
        await controller.erase()

    return command.finish("All done.")


@parser.command()
@click.option("--erase", is_flag=True, help="Run the erase procedure too.")
@click.option("--cycles", type=int, default=5, help="Number of purge cycles.")
@click.option("--slow", is_flag=True, help="Does full flushing for each cycle.")
async def cleanup(
    command: YaoCommand,
    controllers: dict[str, YaoController],
    erase: bool = False,
    cycles: int = 5,
    slow: bool = False,
):
    """Runs the r2 cleanup routine."""

    for controller in controllers.values():
        command.info(f"Running cleanup routine on spectrograph {controller.name}.")
        await controller.cleanup(
            erase=erase,
            notifier=command.info,
            n_cycles=cycles,
            fast=not slow,
        )

    return command.finish("All done.")


@parser.group()
def purge(*args):
    """Sets the purge routine on/off."""

    pass


@purge.command()
async def on(command: YaoCommand, controllers: dict[str, YaoController]):
    """Sets DoPurge=1."""

    for controller in controllers.values():
        await controller.set_param("DoPurge", 1)

    return command.finish("All done.")


@purge.command()
async def off(command: YaoCommand, controllers: dict[str, YaoController]):
    """Sets DoPurge=0."""

    for controller in controllers.values():
        await controller.set_param("DoPurge", 0)

    return command.finish("All done.")
