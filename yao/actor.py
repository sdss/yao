#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-01
# @Filename: actor.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import warnings

from archon import log as archon_log
from archon.actor.actor import ArchonBaseActor
from archon.actor.tools import get_schema
from clu import Command
from clu.legacy import LegacyActor
from sdsstools.utils import cancel_task

from yao import __version__, config
from yao.alerts import AlertsBot
from yao.commands import parser
from yao.controller import YaoController
from yao.delegate import YaoDelegate
from yao.exceptions import YaoUserWarning
from yao.mech_controller import MechController


class YaoActor(ArchonBaseActor, LegacyActor):
    """Yao actor."""

    is_legacy = True

    DELEGATE_CLASS = YaoDelegate
    CONTROLLER_CLASS = YaoController

    parser = parser

    def __init__(self, *args, **kwargs):
        self._message_processor = self._process_message

        schema = self.merge_schemas(kwargs.pop("schema", None))

        # We are going to append "spX_" to every keyword that contains the
        # controller sub-keyword, so for now let's accept additionalProperties.
        schema["additionalProperties"] = True

        super().__init__(*args, schema=schema, **kwargs)

        self.version = __version__

        self.alerts_bot: AlertsBot | None = None

        # TODO: this assumes one single mech controller, not one per spectrograph,
        # but in practice for now that's fine.

        log_path = self.log.log_filename
        write_mech_log = self.config["specMech"].get("write_log", False)
        if log_path and write_mech_log:
            mech_log = pathlib.Path(log_path).parent / "spec-mech.log"
        else:
            mech_log = None

        self.spec_mech = MechController(
            self.config["specMech"]["address"],
            self.config["specMech"]["port"],
            log_path=str(mech_log),
        )
        self._mech_set_time_task: asyncio.Task | None = None

        # Add actor log handlers to the archon library to also get that logging.
        archon_log.addHandler(self.log.sh)
        if self.log.fh:
            archon_log.addHandler(self.log.fh)
            self.log.fh.setLevel(10)

    async def start(self):
        """Starts the actor and connects the specMech client."""

        try:
            await self.spec_mech.start()
        except asyncio.TimeoutError:
            warnings.warn(
                "Failed connecting to mech controller: timed out.",
                YaoUserWarning,
            )
        except Exception as err:
            warnings.warn(
                f"Failed connecting to mech controller: {err}",
                YaoUserWarning,
            )

        new_self = await super().start()

        if self.spec_mech.is_connected:
            self._mech_set_time_task = asyncio.create_task(self._set_mech_time())

        if self.alerts_bot is None:
            self.alerts_bot = AlertsBot(self)

        return new_self

    async def stop(self):
        """Stops the actor and disconnects the specMech client."""

        if self._mech_set_time_task:
            await cancel_task(self._mech_set_time_task)

        if self.alerts_bot:
            self.alerts_bot.stop()

        if self.spec_mech.writer:
            self.spec_mech.writer.close()
            await self.spec_mech.writer.wait_closed()

        return await super().stop()

    def merge_schemas(self, yao_schema_path: str | None = None):
        """Merge default schema with the one from yao."""

        schema = get_schema()  # Default archon schema.

        if yao_schema_path:
            root_path = pathlib.Path(__file__).absolute().parent
            if not os.path.isabs(yao_schema_path):
                yao_schema_path = os.path.join(str(root_path), yao_schema_path)

            yao_schema = json.loads(open(yao_schema_path, "r").read())

            schema["definitions"].update(yao_schema.get("definitions", {}))
            schema["properties"].update(yao_schema.get("properties", {}))
            schema["patternProperties"].update(yao_schema.get("patternProperties", {}))

            if "additionalProperties" in yao_schema:
                schema["additionalProperties"] = yao_schema["additionalProperties"]

        return schema

    @staticmethod
    def _process_message(message: dict):
        """Processes the messages to output to the users.

        If the message is a dictionary with a ``controller`` keyword,
        reformats it into multiple keywords that start with the controller
        name.

        """

        original_message = message.copy()
        new_message = {}

        for key, value in original_message.items():
            if not isinstance(value, dict):
                new_message[key] = value
                continue

            if "controller" in value:
                controller_prefix = value["controller"] + "_"
            else:
                controller_prefix = ""

            for subkey, subvalue in value.items():
                if subkey == "controller":
                    continue
                if isinstance(subvalue, dict):
                    subvalue = list(subvalue.values())
                subkey = subkey.replace("/", "_")
                new_message[controller_prefix + subkey] = subvalue

        return new_message

    @classmethod
    def from_config(cls, file: str | None = None):
        """Creates an actor from the internal package configuration."""

        return super().from_config(config if file is None else file)

    async def _set_mech_time(self):
        """Sets the time on the mech controller."""

        while True:
            now = datetime.datetime.now(datetime.timezone.utc)
            iso_string = now.isoformat().split(".")[0]
            cmd = await self.send_command("yao", f"mech set-time {iso_string}")
            if cmd.status.did_fail:
                self.write("e", error="Failed setting time on mech controller.")
                await asyncio.sleep(60)
                continue

            await asyncio.sleep(86400)


YaoCommand = Command[YaoActor]
