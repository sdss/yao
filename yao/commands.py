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


__all__ = ["hartmann"]


async def run_subcmd(command: YaoCommand, command_string: str):
    """Runs a subcommand and checks its completion."""

    subcmd = await command.send_command("yao", command_string)
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
                if await run_subcmd(command, f"mech close {ss}"):
                    return

            # Check that the side door is closed or close it.
            status_other_side = await spec_mech.pneumatic_status(other_side)
            if status_other_side == "transitioning":
                raise SpecMechError(f"Hartmann {other_side} door is transitioning.")
            elif status_other_side == "open":
                if await run_subcmd(command, f"mech open {other_side}"):
                    return

            expose_cmd: str = "expose --arc"
            if sub_frame:
                expose_cmd += " --window-mode hartmann"
            expose_cmd += f" {exptime}"

            if await run_subcmd(command, expose_cmd):
                return

    except SpecMechError as err:
        return command.fail(error=f"SpecMech error: {err}")

    except Exception as err:
        return command.fail(error=f"Unexpected exception: {err}")

    finally:
        # Reset default window.
        await command.send_command("yao", "set-window")

    return command.finish()
