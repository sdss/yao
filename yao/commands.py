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
import yaml

from archon.actor import parser
from sdsstools import Configuration, read_yaml_file

from .exceptions import SpecMechError


if TYPE_CHECKING:
    from yao.actor import YaoActor

    from .actor import YaoCommand
    from .controller import YaoController


__all__ = ["hartmann", "erase", "cleanup", "purge", "override"]


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


@parser.group()
def override(*args):
    """Sets override configuration parameters."""

    pass


@override.command()
@click.option(
    "--full-init",
    is_flag=True,
    help="Runs a full initialization after the overrides have been reset.",
)
async def reset(
    command: YaoCommand,
    controllers: dict[str, YaoController],
    full_init: bool = False,
):
    """Resets the override configuration."""

    config_file = command.actor.config_file_path
    if config_file is None:
        return command.fail("Configuration file not available.")

    command.actor.config = read_yaml_file(
        config_file,
        return_class=Configuration,
    )
    _ensure_overrides(command.actor)

    if full_init:
        command.info("Re-initialising Archon.")
        await command.send_command("yao", "init")
    else:
        for controller in controllers:
            for override in command.actor.config[f"archon.acf_overrides.{controller}"]:
                if override.startswith("MOD"):
                    mod = int(override.split("\\")[0][3:])
                    command.info(f"Applying configuration for MOD{mod:02}.")
                    await command.send_command(
                        "yao",
                        f"init -a APPLYMOD{mod - 1:02X}",
                    )
                else:
                    command.warning(
                        f"Not applying configuration for override {override!r}. "
                        "Consider calling this command with --full-init."
                    )

    return command.finish("Overrides have been reset.")


@override.command()
def show(command, controllers: dict[str, YaoController]):
    """Shows the current override configuration."""

    _ensure_overrides(command.actor)

    for controller in controllers.values():
        if len(command.actor.config[f"archon.acf_overrides.{controller.name}"]) == 0:
            command.info(f"No overrides for {controller.name}.")
        else:
            command.info(f"Current overrides for {controller.name}:")
            overrides = command.actor.config[f"archon.acf_overrides.{controller.name}"]
            for override in overrides:
                override_value = overrides[override]
                override_name = override.replace("\\", "/")
                command.info(f"{override_name} -> {override_value}")

    return command.finish()


# TODO: This is hardcoded for BOSS at LCO.
@override.command()
@click.argument("CAMERA", type=click.Choice(["r2", "b2"], case_sensitive=True))
@click.argument("TEMPERATURE", type=click.FloatRange(-130, 25))
@click.option("--permanent", is_flag=True, help="Makes the change permanent.")
async def set_ccd_temperature(
    command: YaoCommand,
    controllers: dict[str, YaoController],
    camera: str,
    temperature: float,
    permanent: bool = False,
):
    """Sets the CCD temperature."""

    if camera == "r2":
        override = r"MOD2\HEATERATARGET"
    else:
        override = r"MOD11\HEATERATARGET"

    _ensure_overrides(command.actor)

    temperature = round(temperature, 1)
    command.actor.config["archon"]["acf_overrides"]["sp2"][override] = temperature

    if permanent:
        _save_configuration(command)

    mod = int(override.split("\\")[0][3:])
    await command.send_command("yao", f"init -a APPLYMOD{mod - 1:02X}")

    return command.finish(f"CCD temperature for {camera!r} set to {temperature:.1f}.")


@override.command()
@click.option("--permanent", is_flag=True, help="Makes the change permanent.")
async def disable_fan(
    command: YaoCommand,
    controllers: dict[str, YaoController],
    permanent: bool = False,
):
    """Disables the Archon fan."""

    _ensure_overrides(command.actor)

    command.actor.config["archon"]["acf_overrides"]["sp2"]["FANDISABLE"] = 1

    if permanent:
        _save_configuration(command)

    await command.send_command("yao", "init")

    return command.finish("Archon fan has been disabled.")


@override.command()
@click.option("--permanent", is_flag=True, help="Makes the change permanent.")
async def enable_fan(
    command: YaoCommand,
    controllers: dict[str, YaoController],
    permanent: bool = False,
):
    """Enables the Archon fan."""

    _ensure_overrides(command.actor)

    command.actor.config["archon"]["acf_overrides"]["sp2"]["FANDISABLE"] = 0

    if permanent:
        _save_configuration(command)

    await command.send_command("yao", "init")

    return command.finish("Archon fan has been enabled.")


def _ensure_overrides(actor: YaoActor):
    """Ensures that the actor has the necessary configuration overrides."""

    if "archon" not in actor.config:
        actor.config["archon"] = {}

    archon_config = actor.config["archon"]
    if "acf_overrides" not in archon_config:
        archon_config["acf_overrides"] = {}

    for controller in actor.controllers:
        if controller not in archon_config["acf_overrides"]:
            archon_config["acf_overrides"][controller] = {}

    if not isinstance(actor.config, Configuration):
        actor.config = Configuration(actor.config)


def _save_configuration(command: YaoCommand):
    """Saves the current configuration to a file."""

    actor = command.actor

    if actor.config_file_path is None:
        command.error(error="Cannot save configuration. Configuration file not found.")
        return

    if isinstance(actor.config, Configuration):
        config_dict = actor.config.to_dict()
    else:
        config_dict = dict(actor.config)

    command.info(f"Saving configuration to {actor.config_file_path!s}.")
    yaml.safe_dump(
        config_dict,
        open(actor.config_file_path, "w"),
        sort_keys=False,
        indent=2,
    )
