#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-13
# @Filename: delegate.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

import numpy
from astropy.io import fits
from astropy.time import Time

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

        LINES = controller.current_window["lines"]
        PIXELS = controller.current_window["pixels"]

        WIN_MODE = self.expose_data.window_mode if self.expose_data else None

        for hdu in hdus:
            data = hdu.data
            header = hdu.header
            assert isinstance(data, numpy.ndarray)

            ccd = hdu.header["CCD"]
            if ccd not in ["b2", "r2"]:
                self.command.warning(text=f"Unknown CCD {ccd}.")
                continue

            if WIN_MODE != "hartmann":
                OL = config["controllers"]["sp2"]["overscan_regions"][ccd]["lines"]
                OL_END = -OL
            else:
                OL = 0
                OL_END = None

            OP = config["controllers"]["sp2"]["overscan_regions"][ccd]["pixels"]

            # Copy original data.
            raw = data.copy()

            # Rearrange pixel overscan.
            data[:, :OP] = raw[:, PIXELS - OP : PIXELS]
            data[:, -OP:] = raw[:, PIXELS : PIXELS + OP]

            # Rearrange line overscan.
            if OL > 0:
                data[:OL, OP:PIXELS] = raw[LINES - OL : LINES, : PIXELS - OP]  # BL
                data[-OL:, OP:PIXELS] = raw[LINES : LINES + OL, : PIXELS - OP]  # TL
                data[:OL, PIXELS:-OP] = raw[LINES - OL : LINES, PIXELS + OP :]  # BL
                data[-OL:, PIXELS:-OP] = raw[LINES : LINES + OL, PIXELS + OP :]  # BR

            # Rearrange data.
            data[OL:LINES, OP:PIXELS] = raw[: LINES - OL, : PIXELS - OP]  # BL
            data[LINES:OL_END, OP:PIXELS] = raw[LINES + OL :, : PIXELS - OP]  # TL
            data[OL:LINES, PIXELS:-OP] = raw[: LINES - OL, PIXELS + OP :]  # BR
            data[LINES:OL_END, PIXELS:-OP] = raw[LINES + OL :, PIXELS + OP :]  # TR

            if WIN_MODE == "hartmann":
                DEF_LINES = controller.default_window["lines"]
                DEF_PIXELS = controller.default_window["pixels"]
                new_data = numpy.zeros((DEF_LINES * 2, DEF_PIXELS * 2), dtype="u2")

                PRELINES = controller.current_window["preskiplines"]

                new_data[PRELINES : PRELINES + LINES, :] = data[:LINES, :]
                new_data[-PRELINES - LINES : -PRELINES, :] = data[LINES:, :]

                hdu.data = new_data
            else:
                hdu.data = data

            # Rename some keywords and add others to match APO BOSS datamodel.
            header.insert("CCD", ("CAMERAS", header["CCD"]))

            header.rename_keyword("IMAGETYP", "FLAVOR")
            header.rename_keyword("OBSTIME", "DATE-OBS")

            isot = Time(header["DATE-OBS"], format="isot", scale="tai")
            tai_card = (
                "TAI-BEG",
                isot.mjd * 24 * 3600,
                "MJD(TAI) seconds at start of integration",
            )
            header.insert("DATE-OBS", tai_card)

            reqtime_card = ("REQTIME", header["EXPTIME"], "Requested exposure time")
            header.insert("EXPTIME", reqtime_card)

        return controller, hdus
