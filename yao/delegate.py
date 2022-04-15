#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-13
# @Filename: delegate.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

import numpy
from astropy.io import fits

from archon.actor.delegate import ExposureDelegate
from archon.controller import ArchonController


class YaoDelegate(ExposureDelegate):
    """Exposure delegate for BOSS."""

    async def post_process(
        self,
        controller: ArchonController,
        hdus: list[fits.PrimaryHDU],
    ) -> tuple[ArchonController, list[fits.PrimaryHDU]]:
        """Post-process images and rearrange overscan regions."""

        config = self.actor.config

        LINES = config["controllers"]["sp2"]["parameters"]["lines"]
        PIXELS = config["controllers"]["sp2"]["parameters"]["pixels"]

        for hdu in hdus:
            data = hdu.data
            assert isinstance(data, numpy.ndarray)

            ccd = hdu.header["CCD"]
            if ccd not in ["b2", "r2"]:
                self.command.warning(text=f"Unknown CCD {ccd}.")
                continue

            OL = config["controllers"]["sp2"]["overscan_regions"][ccd]["lines"]
            OP = config["controllers"]["sp2"]["overscan_regions"][ccd]["pixels"]

            # Copy original data.
            raw = data.copy()

            # Rearrange pixel overscan.
            data[:, :OP] = raw[:, PIXELS - OP : PIXELS]
            data[:, -OP:] = raw[:, PIXELS : PIXELS + OP]

            # Rearrange line overscan.
            data[:OL, OP:PIXELS] = raw[LINES - OL : LINES, : PIXELS - OP]  # BL
            data[-OL:, OP:PIXELS] = raw[LINES : LINES + OL, : PIXELS - OP]  # TL
            data[:OL, PIXELS:-OP] = raw[LINES - OL : LINES, PIXELS + OP :]  # BL
            data[-OL:, PIXELS:-OP] = raw[LINES : LINES + OL, PIXELS + OP :]  # BR

            # Rearrange data.
            data[OL:LINES, OP:PIXELS] = raw[: LINES - OL, : PIXELS - OP]  # BL
            data[LINES:-OL, OP:PIXELS] = raw[LINES + OL :, : PIXELS - OP]  # TL
            data[OL:LINES, PIXELS:-OP] = raw[: LINES - OL, PIXELS + OP :]  # BR
            data[LINES:-OL, PIXELS:-OP] = raw[LINES + OL :, PIXELS + OP :]  # TR

            hdu.data = data

        return controller, hdus
