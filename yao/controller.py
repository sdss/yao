#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-11-03
# @Filename: controller.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio

from typing import Callable

from archon import log
from archon.controller import ArchonController, ControllerStatus


__all__ = ["YaoController"]


class YaoController(ArchonController):
    """Extension of `.ArchonController` for Yao."""

    async def erase(self):
        """Run the LBNL erase procedure."""

        log.info(f"{self.name}: erasing.")

        await self.reset(restart_timing=False, autoflush=False)

        await self.set_param("DoErase", 1)
        await self.send_command("RESETTIMING")
        await self.send_command("RELEASETIMING")

        await asyncio.sleep(2)  # Real time should be ~0.6 seconds.

        await self.set_param("DoErase", 0)

        self.update_status(ControllerStatus.IDLE)

    async def cleanup(
        self,
        erase: bool = False,
        notifier: Callable[[str], None] | None = None,
    ):
        """Runs a cleanup procedure."""

        if notifier is None:
            notifier = lambda text: None  # noqa

        if erase:
            notifier("Erasing chip.")
            await self.erase()

        purge_msg = "Taking 10 exposures with DoPurge=1"
        log.info(purge_msg)
        notifier(purge_msg)

        await self.set_param("DoPurge", 1)
        for ii in range(10):
            notifier(f"Taking image {ii+1} of 10 (not saving).")

            await self.expose(0, readout=False)
            await asyncio.sleep(0.5)
            await self.readout()

        await self.set_param("DoPurge", 0)

        flush_msg = "Flushing 50x"
        log.info(flush_msg)
        notifier(flush_msg)

        await self.flush(50)

        return True
