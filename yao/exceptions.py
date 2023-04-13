#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2022-04-01
# @Filename: exceptions.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)


class YaoError(Exception):
    """A custom core Yao exception"""

    def __init__(self, message=None):
        message = "There has been an error" if not message else message
        super(YaoError, self).__init__(message)


class YaoNotImplemented(YaoError):
    """A custom exception for not yet implemented features."""

    def __init__(self, message=None):
        message = "This feature is not implemented yet." if not message else message
        super(YaoNotImplemented, self).__init__(message)


class SpecMechError(YaoError):
    """A specMech error."""


class YaoMissingDependency(YaoError):
    """A custom exception for missing dependencies."""

    pass


class YaoWarning(Warning):
    """Base warning for Yao."""

    pass


class YaoUserWarning(UserWarning, YaoWarning):
    """The primary warning class."""

    pass
