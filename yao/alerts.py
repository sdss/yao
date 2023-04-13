#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-10-22
# @Filename: alerts.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import abc
import asyncio
import time
from collections import deque

from typing import TYPE_CHECKING, Type

from yao import config


if TYPE_CHECKING:
    from .actor import YaoActor

__all__ = ["AlertsBot"]


class AlertsBot:
    """Handles alerts for BOSS."""

    def __init__(self, actor: YaoActor):
        __ALERTS__: list[Type[BaseAlert]] = [
            R2CCDTemperatureAlert,
            R2LN2TemperatureAlert,
            B2CCDTemperatureAlert,
            B2LN2TemperatureAlert,
            YaoHeartbeat,
        ]

        self.actor = actor

        self.alerts = [AlertClass(self.actor).start() for AlertClass in __ALERTS__]

    def stop(self):
        """Stops all the alert handlers."""

        for alert in self.alerts:
            alert.stop()


class BaseAlert(metaclass=abc.ABCMeta):
    """An alert handler."""

    name: str
    keyword: str

    def __init__(self, actor: YaoActor, interval: float = 60.0):
        self.actor = actor
        self.interval = interval

        self._value: bool = False

        if not hasattr(self, "name"):
            self.name = self.__class__.__name__

        if not hasattr(self, "keyword"):
            raise NameError(f"Alert {self.name} has no defined keyword.")

        self._task: asyncio.Task | None = None

        self.reset()

    def reset(self):
        """Resets the alarm."""

        self._value = False
        self._notify(False, force=True)

    @property
    def value(self):
        """The value of the alert."""

        return self._value

    @value.setter
    def value(self, new_value: bool):
        """Sets the new value of the alert and notifies."""

        self._notify(new_value, force=False)
        self._value = new_value

    def _notify(self, value: bool, force: bool = False):
        """Notifies if the alert is on or off."""

        # Output positive alerts every time, but false ones only if they
        # change the current value of the alert.
        if value == self.value and value is False and not force:
            return

        code = "w" if value is True else "i"
        self.actor.write(code, {self.keyword: int(value)})

    def start(self):
        """Starts the alert handler."""

        if self._task is not None:
            self.stop()

        self._task = asyncio.create_task(self._alert_handler())

        return self

    def stop(self):
        """Stops the alert handler."""

        if self._task:
            self._task.cancel()

        self._task = None

    async def _alert_handler(self):
        """Execute the alert code in a loop."""

        await asyncio.sleep(1)

        while True:
            try:
                await self.check_alert()
            except Exception as err:
                self.actor.write(
                    "w", {"error": f"Failed checking alert {self.name}: {err}"}
                )

            await asyncio.sleep(self.interval)

    @abc.abstractclassmethod
    async def check_alert(self):
        """Code that actually checks and raises an alert."""

        pass


class TemperatureAlert(BaseAlert):
    controller: str
    ccd: str
    status_param: str
    setpoint_param: str | float
    max_increase: float

    def __init__(self, actor: YaoActor, interval: float = 60):
        # Rolling log of alert values; keeps only the last two measurements.
        self._values_log = deque(maxlen=2)

        super().__init__(actor, interval)

    async def check_alert(self):
        """Checks the CCD temperature."""

        controller = self.actor.controllers[self.controller]

        status = await controller.get_device_status()

        temperature = status[self.status_param]

        if isinstance(self.setpoint_param, str):
            if not controller.acf_config:
                raise ValueError("Controller has no configuration loaded.")
            setpoint = controller.acf_config["CONFIG"].getfloat(self.setpoint_param)
        else:
            setpoint = self.setpoint_param

        if temperature > setpoint + self.max_increase:
            self._values_log.append(True)
        else:
            self._values_log.append(False)

        # We require two consecutive measurements to change the alarm.
        if len(self._values_log) < 2:
            pass
        elif self._values_log[0] is True and self._values_log[1] is True:
            self.value = True
        elif self._values_log[0] is False and self._values_log[1] is False:
            self.value = False


class R2LN2TemperatureAlert(TemperatureAlert):
    """r2 LN2 alert."""

    name = "r2_ln2_temp_alert"
    keyword = "r2_ln2_temp_alert"

    controller = "sp2"
    ccd = "r2"
    status_param = config["alerts"]["sp2"]["r2_ln2_status_param"]
    setpoint_param = config["alerts"]["sp2"]["ln2_base_temperature"]
    max_increase = config["alerts"]["sp2"]["ln2_temperature_max_increase"]


class R2CCDTemperatureAlert(TemperatureAlert):
    """r2 CCD alert."""

    name = "r2_ccd_temp_alert"
    keyword = "r2_ccd_temp_alert"

    controller = "sp2"
    ccd = "r2"
    status_param = config["alerts"]["sp2"]["r2_ccd_status_param"]
    setpoint_param = config["alerts"]["sp2"]["r2_setpoint_param"]
    max_increase = config["alerts"]["sp2"]["ccd_temperature_max_increase"]


class B2LN2TemperatureAlert(TemperatureAlert):
    """b2 LN2 alert."""

    name = "b2_ln2_temp_alert"
    keyword = "b2_ln2_temp_alert"

    controller = "sp2"
    ccd = "b2"
    status_param = config["alerts"]["sp2"]["b2_ln2_status_param"]
    setpoint_param = config["alerts"]["sp2"]["ln2_base_temperature"]
    max_increase = config["alerts"]["sp2"]["ln2_temperature_max_increase"]


class B2CCDTemperatureAlert(TemperatureAlert):
    """b2 CCD alert."""

    name = "b2_ccd_temp_alert"
    keyword = "b2_ccd_temp_alert"

    controller = "sp2"
    ccd = "b2"
    status_param = config["alerts"]["sp2"]["b2_ccd_status_param"]
    setpoint_param = config["alerts"]["sp2"]["b2_setpoint_param"]
    max_increase = config["alerts"]["sp2"]["ccd_temperature_max_increase"]


class YaoHeartbeat(BaseAlert):
    """Heartbeat alert."""

    name = "yao_heartbeat"
    keyword = "alive_at"

    reset_on_start = False

    def _notify(self, *args, **kwargs):
        """Disable normal alert notifications for this alert."""

        pass

    async def check_alert(self):
        """Reports if the actor is alive."""

        self.actor.write("d", {self.keyword: time.time()}, broadcast=True)
