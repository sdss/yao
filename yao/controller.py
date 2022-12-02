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

        await self.reset(release_timing=False, autoflush=False)

        self.update_status(ControllerStatus.FLUSHING)

        await self.set_param("DoErase", 1)
        await self.send_command("RELEASETIMING")

        await asyncio.sleep(2)  # Real time should be ~0.6 seconds.

        await self.reset()

    async def cleanup(
        self,
        erase: bool = False,
        n_cycles: int = 10,
        fast: bool = False,
        notifier: Callable[[str], None] | None = None,
    ):
        """Runs a cleanup procedure for the LBNL chip.

        Executes a number of cycles of the e-purge routine followed by a chip
        flush (complete or fast). After the e-purge cycles have been completed,
        runs three full flushing cycles.

        Parameters
        ----------
        erase
            Calls the `.erase` routine before running the e-purge cycle.
        n_cycles
            Number of e-purge/flushing cycles to execute.
        fast
            If `False`, a complete flushing is executed after each e-purge (each
            line is shifted and read). If `True`, a binning factor of 10 is used.
        notifier
            A function to call to output messages (usually a command write method).

        """

        if notifier is None:
            notifier = lambda text: None  # noqa

        if erase:
            notifier("Erasing chip.")
            await self.erase()

        mode = "fast" if fast else "normal"
        purge_msg = f"Doing {n_cycles} with DoPurge=1 (mode={mode})"
        log.info(purge_msg)
        notifier(purge_msg)

        for ii in range(n_cycles):
            notifier(f"Cycle {ii+1} of {n_cycles}.")
            await self.purge(fast=fast)

        await self.set_param("DoPurge", 0)

        flush_msg = "Flushing 3x"
        log.info(flush_msg)
        notifier(flush_msg)

        await self.flush(3)

        await self.reset()

        return True

    async def purge(self, fast: bool = True):
        """Runs a single cycle of the e-purge routine.

        A cycle consists of an execution of the e-purge routine followed by a
        chip flushing.

        Parameters
        ----------
        fast
            If `False`, a complete flushing is executed after the e-purge (each
            line is shifted and read). If `True`, a binning factor of 10 is used.

        """

        log.info("Running e-purge.")

        if fast:
            await self.set_param("FLUSHBIN", 10)
            await self.set_param("SKIPLINEBINVSHIFT", 220)
        else:
            await self.set_param("FLUSHBIN", 2200)
            await self.set_param("SKIPLINEBINVSHIFT", 1)

        await self.reset(release_timing=False)

        self.update_status(ControllerStatus.FLUSHING)

        await self.set_param("DOPURGE", 1)
        await self.send_command("RELEASETIMING")

        flush_time = self.config["timeouts"]["flushing"]
        if fast:
            flush_time = self.config["timeouts"]["fast_flushing"]

        await asyncio.sleep(self.config["timeouts"]["purge"] + flush_time)

        await self.set_param("FLUSHBIN", 2200)
        await self.set_param("SKIPLINEBINVSHIFT", 1)

        await self.reset()

        return True
