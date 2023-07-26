#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-13
# @Filename: delegate.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Any, List

import numpy
from astropy.io import fits
from astropy.time import Time
from clu.legacy.types.pvt import PVT

from archon.actor.delegate import ExposureDelegate
from archon.controller import ArchonController
from sdsstools.time import get_sjd

from .exceptions import SpecMechError


if TYPE_CHECKING:
    from clu.command import Command

    from yao.actor import YaoActor
    from yao.controller import YaoController


# TODO: LCOTCC cards are copied from flicamera. Should reunify code.


class YaoDelegate(ExposureDelegate["YaoActor"]):
    """Exposure delegate for BOSS."""

    def __init__(self, actor: YaoActor):
        super().__init__(actor)

        self.header_data = {}
        self.shutter_failed: bool = False

    def reset(self):
        """Reset the delegate."""

        self.shutter_failed = False

        return super().reset()

    async def pre_expose(self, controllers: List[YaoController]):
        """Runs the e-purge routine before the exposure."""

        self.command.info("E-purging and flushing.")

        await asyncio.gather(*[controller.purge() for controller in controllers])

        return True

    async def shutter(self, open: bool = False) -> bool:
        """Open/close the shutter."""

        expose_data = self.expose_data
        assert expose_data

        # TODO: this should be part of the ExposureDelegate.
        if expose_data.exposure_time == 0 or expose_data.flavour in ["bias", "dark"]:
            return True

        try:
            # Time-out in five seconds.
            await asyncio.wait_for(
                self.command.actor.spec_mech.pneumatic_move(
                    "shutter",
                    open=open,
                    command=self.command,
                ),
                5,
            )
        except asyncio.TimeoutError:
            self.command.error(
                "Timed out trying to move the shutter. The SpecMech may be dead."
            )
            self.shutter_failed = True
        except SpecMechError as err:
            self.command.error(f"Failed moving shutter: {err}")
            self.shutter_failed = True

        if self.shutter_failed:
            if open is True:
                # No point in exposing if we cannot open the shutter.
                return False

            # Try to read out with shutter open.
            self.command.warning("Reading out the exposure before failing.")

        return True

    async def readout(
        self,
        command: Command[YaoActor],
        extra_header: dict[str, Any] = {},
        delay_readout: int = 0,
        write: bool = True,
    ):
        """Reads detectors."""

        if self.shutter_failed:
            self.command.warning(
                "Frame was read out but shutter failed to close. "
                "There may be contamination in the image."
            )

        # Finish exposure tasks.
        try:
            if self._expose_cotasks:
                self.command.debug(text="Awaiting for exposure cotasks to finishing.")
                await asyncio.wait_for(self._expose_cotasks, 10)
        except asyncio.TimeoutError:
            self.command.warning("Timed out running exposure cotasks.")

        read_result = await super().readout(command, extra_header, delay_readout, write)

        return False if (self.shutter_failed or not read_result) else True

    async def expose_cotasks(self):
        """Grab header information during exposure."""

        self.command.debug(text="Starting exposure cotasks.")

        self.header_data = {}

        self.header_data["fps_cards"] = [
            (
                "CONFID",
                get_keyword(
                    self.actor,
                    "jaeger",
                    "configuration_loaded",
                    idx=0,
                    cnv=int,
                ),
                "Configuration ID",
            ),
            (
                "DESIGNID",
                get_keyword(
                    self.actor,
                    "jaeger",
                    "configuration_loaded",
                    idx=1,
                    cnv=int,
                ),
                "Design ID associated with CONFIGID",
            ),
            (
                "FIELDID",
                get_keyword(
                    self.actor,
                    "jaeger",
                    "configuration_loaded",
                    idx=2,
                    cnv=int,
                ),
                "Field ID associated with CONFIGID",
            ),
        ]

        self.header_data["lcotcc_cards"] = get_lcotcc_cards(self.actor)

        cherno_cards = []
        for idx, card in enumerate(["OFFRA", "OFFDEC", "OFFPA"]):
            default = get_keyword(
                self.actor,
                "cherno",
                "default_offset",
                idx=idx,
                default=0.0,
                cnv=float,
            )
            offset = get_keyword(
                self.actor,
                "cherno",
                "offset",
                idx=idx,
                default=0.0,
                cnv=float,
            )
            cherno_cards.append(
                (
                    card,
                    default + offset,
                    "Absolute guider offset in " + card.replace("OFF", ""),
                )
            )
        cherno_cards.append(
            (
                "SEEING",
                get_keyword(
                    self.actor,
                    "cherno",
                    "astrometry_fit",
                    idx=4,
                    cnv=float,
                ),
                "Seeing from the guider [arcsec]",
            )
        )
        self.header_data["cherno_cards"] = cherno_cards

        lamp_cards = []
        for lamp in ["FF", "Ne", "HeAr"]:
            value = get_keyword(self.actor, "lcolamps", lamp, idx=0, default="?")
            if value == "ON":
                card_value = "1 1 1 1"
            elif value == "OFF":
                card_value = "0 0 0 0"
            else:
                card_value = "? ? ? ?"
            lamp_cards.append((lamp.upper(), card_value, f"{lamp} lamps 1:On 0:Off"))
        self.header_data["lamp_cards"] = lamp_cards

        specmech_cards = []

        status_left = await self.actor.spec_mech.pneumatic_status("left")
        status_right = await self.actor.spec_mech.pneumatic_status("right")
        if status_left == "closed" and status_right == "closed":
            hartmann = "Left,Right"
        elif status_left == "closed" and status_right == "open":
            hartmann = "Left"
        elif status_left == "open" and status_right == "closed":
            hartmann = "Right"
        elif status_left == "open" and status_right == "open":
            hartmann = "Out"
        else:
            hartmann = "?"
        specmech_cards.append(("HARTMANN", hartmann, "Hartmanns: Left,Right,Out"))

        for motor in ["a", "b", "c"]:
            _, pos, *_ = await self.actor.spec_mech.get_stat(f"motor-{motor}")
            specmech_cards.append(
                (
                    f"COLL{motor.upper()}",
                    int(pos),
                    f"The position of the {motor.upper()} collimator motor",
                )
            )

        # specMech data
        ori = [-999, -999, -999]
        try:
            ori = await self.actor.spec_mech.get_stat("orientation")
        except Exception as err:
            self.command.warning(f"Cannot get specMech orientation: {err}")
        finally:
            for ii, axis in enumerate(["X", "Y", "Z"]):
                specmech_cards.append(
                    (
                        f"MECHORI{axis}",
                        ori[ii],
                        f"Orientation in {axis} axis [cm/s2]",
                    )
                )

        mech_env = [-999] * 7
        try:
            mech_env = await self.actor.spec_mech.get_stat("environment")
        except Exception as err:
            self.command.warning(f"Cannot get specMech environment: {err}")
        finally:
            for ii, (label, comment) in enumerate(
                [
                    ("B2CAMT", "B2 camera temperature [degC]"),
                    ("B2CAMH", "B2 camera RH [%]"),
                    ("R2CAMT", "R2 camera temperature [degC]"),
                    ("R2CAMH", "R2 camera RH [%]"),
                    ("COLLT", "Collimator temperature [degC]"),
                    ("COLLH", "Collimator RH [%]"),
                    ("SPECMT", "specMech temperature [degC]"),
                ]
            ):
                specmech_cards.append((label, mech_env[ii], comment))

        self.header_data["specmech_cards"] = specmech_cards

        return await super().expose_cotasks()

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

            # Decide whether we want to do some callisthenics with the data to move
            # the overscan regions to the edges and to make things look exactly like
            # at APO.
            if config["controllers"]["sp2"].get("raw_mode", False) is False:
                if WIN_MODE != "hartmann":
                    OL = config["controllers"]["sp2"]["overscan_regions"][ccd]["lines"]
                    OL_END = -OL
                else:
                    OL = 0
                    OL_END = None

                OP = config["controllers"]["sp2"]["overscan_regions"][ccd]["pixels"]

                # Copy original data.
                rr = data.copy()

                # Rearrange pixel overscan.
                data[:, :OP] = rr[:, PIXELS - OP : PIXELS]
                data[:, -OP:] = rr[:, PIXELS : PIXELS + OP]

                # Rearrange line overscan.
                if OL > 0:
                    data[:OL, OP:PIXELS] = rr[LINES - OL : LINES, : PIXELS - OP]  # BL
                    data[-OL:, OP:PIXELS] = rr[LINES : LINES + OL, : PIXELS - OP]  # TL
                    data[:OL, PIXELS:-OP] = rr[LINES - OL : LINES, PIXELS + OP :]  # BL
                    data[-OL:, PIXELS:-OP] = rr[LINES : LINES + OL, PIXELS + OP :]  # BR

                # Rearrange data.
                data[OL:LINES, OP:PIXELS] = rr[: LINES - OL, : PIXELS - OP]  # BL
                data[LINES:OL_END, OP:PIXELS] = rr[LINES + OL :, : PIXELS - OP]  # TL
                data[OL:LINES, PIXELS:-OP] = rr[: LINES - OL, PIXELS + OP :]  # BR
                data[LINES:OL_END, PIXELS:-OP] = rr[LINES + OL :, PIXELS + OP :]  # TR

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

            if self.expose_data and self.expose_data.flavour == "object":
                # SoS expects science.
                header["FLAVOR"] = "science"

            header["MJD"] = get_sjd()

            isot = Time(header["DATE-OBS"], format="isot", scale="tai")
            tai_card = (
                "TAI-BEG",
                isot.mjd * 24 * 3600,
                "MJD(TAI) seconds at start of integration",
            )
            header.insert("DATE-OBS", tai_card)

            reqtime_card = ("REQTIME", header["EXPTIME"], "Requested exposure time")
            header.insert("EXPTIME", reqtime_card)

            # Instrument cards
            header.append(("CARTID", "FPS-S", "Instrument ID"))

            for card in self.header_data.get("fps_cards", []):
                header.append(card)

            # TCC Cards
            for card in self.header_data.get("lcotcc_cards", []):
                header.append(card)

            # Cherno offset cards
            for card in self.header_data.get("cherno_cards", []):
                header.append(card)

            # Lamps
            for card in self.header_data.get("lamp_cards", []):
                header.append(card)

            # Hacking FFS and FF for now.
            if self.expose_data and self.expose_data.flavour == "flat":
                header["FF"] = "1 1 1 1"
            if self.expose_data and self.expose_data.flavour in ["flat", "arc"]:
                ffs_value = "1 1 1 1 1 1 1 1"
            else:
                ffs_value = "0 0 0 0 0 0 0 0"
            header.append(("FFS", ffs_value, "FFS 0:Closed 1:Open"))

            # specMech
            for card in self.header_data.get("specmech_cards", []):
                header.append(card)

        return controller, hdus


def pvt2pos(tup):
    pvt = PVT(*tup)
    return pvt.getPos()


def get_keyword(
    actor: YaoActor,
    model_name: str,
    key: str,
    idx: int | None = 0,
    default: Any = "NaN",
    cnv=None,
):
    """Returns the value of a keyword."""

    if not actor.tron or not actor.tron.models:
        actor.write("w", text=f"Cannot retrive keyword {key.upper()}.")
        return default

    model = actor.tron.models[model_name]

    try:
        value = model[key].value
        if idx is not None:
            value = value[idx]
        if cnv:
            value = cnv(value)

        # Headers cannot have NaN values as floats.
        try:
            if numpy.isnan(value):
                value = "NaN"
        except TypeError:
            pass

        return value
    except BaseException:
        return default


def get_lcotcc_cards(actor: YaoActor):
    """Return a list of cards describing the LCO TCC state."""

    model = "lcotcc"

    cards: list[tuple] = []

    objSysName = get_keyword(actor, "lcotcc", "objSys", 0, default="UNKNOWN")
    cards.append(("OBJSYS", objSysName, "The TCC objSys"))

    # ObjSys
    cards += [
        (
            "RA",
            get_keyword(actor, model, "objNetPos", 0, cnv=pvt2pos),
            "RA of telescope boresight (deg)",
        ),
        (
            "DEC",
            get_keyword(actor, model, "objNetPos", 1, cnv=pvt2pos),
            "Dec of telescope boresight (deg)",
        ),
        (
            "RADEG",
            get_keyword(actor, model, "objNetPos", 0, cnv=pvt2pos),
            "RA of telescope pointing (deg)",
        ),
        (
            "DECDEG",
            get_keyword(actor, model, "objNetPos", 1, cnv=pvt2pos),
            "Dec of telescope pointing (deg)",
        ),
        (
            "Equinox",
            2000.0,
            "Equinox of celestial coordinate system",
        ),
        (
            "AZ",
            get_keyword(actor, model, "axePos", 0, cnv=float),
            "Azimuth axis pos. (approx, deg)",
        ),
        (
            "ALT",
            get_keyword(actor, model, "axePos", 1, cnv=float),
            "Altitude axis pos. (approx, deg)",
        ),
        (
            "AIRMASS",
            get_keyword(actor, model, "airmass", 0, cnv=float),
            "Airmass",
        ),
    ]

    # Rotator
    cards.append(
        (
            "HA",
            get_keyword(actor, model, "tccHA", 0, cnv=float),
            "HA axis pos. (approx, deg)",
        )
    )

    cards.append(
        (
            "ROTPOS",
            get_keyword(actor, model, "axePos", 2, cnv=float),
            "Rotator requested pos. (approx, deg)",
        )
    )

    cards.append(
        (
            "IPA",
            get_keyword(actor, model, "axePos", 2, cnv=float),
            "Rotator axis pos. (approx, deg)",
        )
    )

    # Focus / M2
    cards.append(
        (
            "FOCUS",
            get_keyword(actor, model, "secFocus", 0, cnv=float),
            "User-specified focus offset (um)",
        )
    )

    orient_names = ("piston", "xtilt", "ytilt", "xtran", "ytran", "zrot")
    for ii in range(len(orient_names)):
        cards.append(
            (
                "M2" + orient_names[ii].upper(),
                get_keyword(actor, model, "secOrient", ii, cnv=float),
                "TCC SecOrient",
            )
        )

    # Temperatures
    cards.append(
        (
            "T_OUT",
            get_keyword(actor, model, "tccTemps", 0, cnv=float),
            "Outside temperature deg C.",
        )
    )

    cards.append(
        (
            "T_IN",
            get_keyword(actor, model, "tccTemps", 1, cnv=float),
            "Inside temperature deg C.",
        )
    )

    cards.append(
        (
            "T_PRIM",
            get_keyword(actor, model, "tccTemps", 2, cnv=float),
            "Primary mirror temperature deg C.",
        )
    )

    cards.append(
        (
            "T_CELL",
            get_keyword(actor, model, "tccTemps", 3, cnv=float),
            "Cell temperature deg C.",
        )
    )

    cards.append(
        (
            "T_FLOOR",
            get_keyword(actor, model, "tccTemps", 4, cnv=float),
            "Floor temperature deg C.",
        )
    )

    cards.append(
        (
            "T_TRUSS",
            get_keyword(actor, "lcotcc", "secTrussTemp", 0, cnv=float),
            "Truss temperature deg C.",
        )
    )

    return cards
