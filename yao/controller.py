#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-11-03
# @Filename: controller.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio

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
        await self.reset()

        self.update_status(ControllerStatus.IDLE)
