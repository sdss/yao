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


if TYPE_CHECKING:
    from .actor import YaoCommand


__all__ = []


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
