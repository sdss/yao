#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-01
# @Filename: actor.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

import os

from clu.legacy import LegacyActor

from archon import log as archon_log
from archon.actor.actor import ArchonBaseActor

from yao import config
from yao.delegate import YaoDelegate


class YaoActor(ArchonBaseActor, LegacyActor):
    """Yao actor."""

    is_legacy = True

    DELEGATE_CLASS = YaoDelegate

    def __init__(self, *args, **kwargs):

        self._message_processor = self._process_message

        root_path = os.path.dirname(__file__)

        if "schema" in kwargs:
            if kwargs["schema"] is not None and not os.path.isabs(kwargs["schema"]):
                kwargs["schema"] = os.path.join(root_path, kwargs["schema"])

        super().__init__(*args, **kwargs)

        # Add actor log handlers to the archon library to also get that logging.
        archon_log.addHandler(self.log.sh)
        if self.log.fh:
            archon_log.addHandler(self.log.fh)

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
