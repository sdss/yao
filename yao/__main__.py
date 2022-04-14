#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-01
# @Filename: __main__.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import logging
import os
import sys

import click
from click_default_group import DefaultGroup
from clu.tools import cli_coro

from sdsstools.daemonizer import DaemonGroup

from yao import __version__
from yao.actor import YaoActor


@click.group(
    cls=DefaultGroup,
    default="actor",
    default_if_no_args=True,
    invoke_without_command=True,
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Debug mode.",
)
@click.option(
    "--version",
    is_flag=True,
    help="Print version and exit.",
)
@click.pass_context
def yao(ctx: click.Context, verbose: bool = False, version: bool = False):
    """Yao actor."""

    ctx.obj = {"verbose": verbose}

    if version is True:
        click.echo(__version__)
        sys.exit(0)


@yao.group(cls=DaemonGroup, prog="yao-actor", workdir=os.getcwd())
@click.pass_context
@cli_coro
async def actor(ctx: click.Context):
    """Runs the actor."""

    yao_actor = YaoActor.from_config()

    if ctx.obj["verbose"]:
        yao_actor.log.sh.setLevel(logging.DEBUG)

    await yao_actor.start()
    await yao_actor.run_forever()  # type: ignore


if __name__ == "__main__":
    yao()
