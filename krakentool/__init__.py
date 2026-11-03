# krakentool — Kraken Spot WebSocket API v2 market-data consumer.
# Copyright (C) 2026 aifintech-do
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Kraken Spot WebSocket API v2 market-data consumer."""

import argparse

__version__ = "0.1.0"
__copyright__ = "Copyright (C) 2026 aifintech-do"
__license__ = "GPL-3.0-or-later"

VERSION_BANNER = (
    f"krakentool {__version__}\n"
    f"{__copyright__}\n"
    "License GPLv3+: GNU GPL version 3 or later <https://gnu.org/licenses/gpl.html>.\n"
    "This is free software: you are free to change and redistribute it.\n"
    "There is NO WARRANTY, to the extent permitted by law."
)

LICENSE_EPILOG = (
    "This program is free software under the GNU General Public License, "
    "version 3 or any later version. It comes with ABSOLUTELY NO WARRANTY. "
    "See the LICENSE file or <https://www.gnu.org/licenses/>."
)


class VersionAction(argparse.Action):
    """Print the version and the GPL short notice, then exit."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help or "show program version and license",
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(VERSION_BANNER)
        parser.exit()
