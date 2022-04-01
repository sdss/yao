# !usr/bin/env python
# -*- coding: utf-8 -*-
#
# Licensed under a 3-clause BSD license.
#
# @Author: Brian Cherinka
# @Date:   2017-12-05 12:01:21
# @Last modified by:   Brian Cherinka
# @Last Modified time: 2017-12-05 12:19:32

from __future__ import print_function, division, absolute_import


class YaoError(Exception):
    """A custom core Yao exception"""

    def __init__(self, message=None):

        message = 'There has been an error' \
            if not message else message

        super(YaoError, self).__init__(message)


class YaoNotImplemented(YaoError):
    """A custom exception for not yet implemented features."""

    def __init__(self, message=None):

        message = 'This feature is not implemented yet.' \
            if not message else message

        super(YaoNotImplemented, self).__init__(message)


class YaoAPIError(YaoError):
    """A custom exception for API errors"""

    def __init__(self, message=None):
        if not message:
            message = 'Error with Http Response from Yao API'
        else:
            message = 'Http response error from Yao API. {0}'.format(message)

        super(YaoAPIError, self).__init__(message)


class YaoApiAuthError(YaoAPIError):
    """A custom exception for API authentication errors"""
    pass


class YaoMissingDependency(YaoError):
    """A custom exception for missing dependencies."""
    pass


class YaoWarning(Warning):
    """Base warning for Yao."""


class YaoUserWarning(UserWarning, YaoWarning):
    """The primary warning class."""
    pass


class YaoSkippedTestWarning(YaoUserWarning):
    """A warning for when a test is skipped."""
    pass


class YaoDeprecationWarning(YaoUserWarning):
    """A warning for deprecated features."""
    pass
