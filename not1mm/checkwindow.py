#!/usr/bin/env python3
"""
not1mm Contest logger
Email: michael.bridak@gmail.com
GPL V3
Class: CheckWindow
Purpose: Onscreen widget to show possible matches to callsigns entered in the main window.
"""
# pylint: disable=no-name-in-module, unused-import, no-member, invalid-name, c-extension-no-member
# pylint: disable=logging-fstring-interpolation, line-too-long

from dataclasses import dataclass
import logging
import os
import queue
from typing import Optional
from json import loads
import Levenshtein

from PyQt6 import QtGui, uic
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QDockWidget, QApplication
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import pyqtSignal

import not1mm.fsutils as fsutils
from not1mm.lib.database import DataBase

from not1mm.lib.super_check_partial import SCP

logger = logging.getLogger(__name__)


class CheckWindow(QDockWidget):
    """The check window. Shows list or probable stations."""

    @dataclass
    class BackgroundColors:
        """Background color data for the checkpartial call signs."""

        character_remove_color: str
        character_add_color: str
        character_match_color: str

    message = pyqtSignal(dict)
    dbname = None
    pref = {}
    call = None
    masterLayout: QVBoxLayout = None
    dxcLayout: QVBoxLayout = None
    qsoLayout: QVBoxLayout = None
    background_colors_cache: Optional[BackgroundColors] = None

    masterScrollWidget: QWidget = None

    def __init__(self):
        super().__init__()
        self.active = False
        self.load_pref()
        self.dbname = fsutils.USER_DATA_PATH / self.pref.get(
            "current_database", "ham.db"
        )
        self.database = DataBase(self.dbname, fsutils.APP_DATA_PATH)
        self.database.current_contest = self.pref.get("contest", 0)

        uic.loadUi(fsutils.APP_DATA_PATH / "checkwindow.ui", self)
        self.mscp = SCP(fsutils.APP_DATA_PATH)
        self._udpwatch = None
        self.udp_fifo = queue.Queue()

        def invalidate_background_colors_cache_on_mode_change():
            self.background_colors_cache = None

        QApplication.instance().styleHints().colorSchemeChanged.connect(
            invalidate_background_colors_cache_on_mode_change
        )

    def msg_from_main(self, packet):
        """"""

        if packet.get("cmd", "") == "UPDATELOG":
            self.clear_lists()
            return

        if self.active is False:
            return
        if packet.get("cmd", "") == "CALLCHANGED":
            call = packet.get("call", "")
            self.call = call
            self.master_list(call)
            self.log_list(call)
            return
        if packet.get("cmd", "") == "CHECKSPOTS":
            self.populate_layout(self.dxcLayout, [])
            spots = packet.get("spots", [])
            self.telnet_list(spots)
            return
        if packet.get("cmd", "") == "NEWDB":
            ...
            # self.load_new_db()

    def setActive(self, mode: bool):
        self.active = bool(mode)

    def item_clicked(self, item):
        """docstring for item_clicked"""
        if item:
            cmd = {}
            cmd["cmd"] = "CHANGECALL"
            cmd["call"] = item
            self.message.emit(cmd)

    def load_pref(self) -> None:
        """
        Load preference file to get current db filename and sets the initial darkmode state.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        try:
            if os.path.exists(fsutils.CONFIG_FILE):
                with open(
                    fsutils.CONFIG_FILE, "rt", encoding="utf-8"
                ) as file_descriptor:
                    self.pref = loads(file_descriptor.read())
                    logger.info(f"loaded config file from {fsutils.CONFIG_FILE}")
            else:
                self.pref["current_database"] = "ham.db"

        except IOError as exception:
            logger.critical("Error: %s", exception)

    def clear_lists(self) -> None:
        """
        Clear match lists.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.populate_layout(self.masterLayout, [])
        self.populate_layout(self.qsoLayout, [])
        self.populate_layout(self.dxcLayout, [])

    def master_list(self, call: str) -> None:
        """
        Get MASTER.SCP matches to call and display in list.

        Parameters
        ----------
        call : str
        Call to get matches for

        Returns
        -------
        None
        """
        self.populate_layout(self.masterLayout, [])
        self.populate_layout(self.masterLayout, self.mscp.super_check(call))

    def log_list(self, call: str) -> None:
        """
        Get log matches to call and display in list.

        Parameters
        ----------
        call : str
        Call to get matches for

        Returns
        -------
        None
        """
        self.populate_layout(self.qsoLayout, [])
        if call:
            result = self.database.get_like_calls_and_bands(call)
            self.populate_layout(self.qsoLayout, result)

    def telnet_list(self, spots: list) -> None:
        """
        Get telnet matches to call and display in list.

        Parameters
        ----------
        spots : list
        List of spots to get matches for

        Returns
        -------
        None
        """
        self.populate_layout(self.dxcLayout, [])
        if spots:
            self.populate_layout(
                self.dxcLayout,
                filter(lambda x: x, [x.get("callsign", None) for x in spots]),
            )

    def populate_layout(self, layout, call_list) -> None:
        """Apply blackmagic to a layout."""
        for i in reversed(range(layout.count())):
            if layout.itemAt(i).widget():
                layout.itemAt(i).widget().setParent(None)
            else:
                layout.removeItem(layout.itemAt(i))
        background_colors = self.background_colors_for_mode()
        call_items = []
        for call in call_list:
            if call:
                if self.call:
                    label_text = ""
                    diff_score = 0
                    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(call, self.call):
                        if tag == "equal":
                            label_text += call[i1:i2]
                            continue
                        elif tag == "replace":
                            label_text += f"<span style='background-color: {background_colors.character_remove_color};'>{call[i1:i2]}</span>"
                            diff_score += max((i2 - i1), (j2 - j1)) * (
                                len(call) + 1 - i2
                            )
                        elif tag == "insert" or tag == "delete":
                            label_text += f"<span style='background-color: {background_colors.character_add_color};'>{call[i1:i2]}</span>"
                            diff_score += max((i2 - i1), (j2 - j1)) * (len(call) - i2)
                    if call == self.call:
                        label_text = f"<span style='background-color: {background_colors.character_match_color};'>{call}</span>"
                    call_items.append((diff_score, label_text, call))

        call_items = sorted(call_items, key=lambda x: x[0])
        for i in reversed(range(layout.count())):
            if layout.itemAt(i).widget():
                layout.itemAt(i).widget().setParent(None)
            else:
                layout.removeItem(layout.itemAt(i))

        for _, label_text, call in call_items:
            label = CallLabel(label_text, call=call, callback=self.item_clicked)
            layout.addWidget(label)
        layout.addStretch(0)

    def background_colors_for_mode(self) -> "CheckWindow.BackgroundColors":
        """Returns appropriate background colors depending on dark or light mode.

        These are used for the checkpartial call signs.
        """
        if self.background_colors_cache is None:
            palette = self.widget.palette()
            text_lightness = palette.windowText().color().lightness()
            background_lightness = palette.window().color().lightness()
            if background_lightness < text_lightness:
                # dark mode
                self.background_colors_cache = CheckWindow.BackgroundColors(
                    character_remove_color="#dd3333",
                    character_add_color="#3333dd",
                    character_match_color="#33bb33",
                )
            else:
                # light mode
                self.background_colors_cache = CheckWindow.BackgroundColors(
                    character_remove_color="#ffcccc",
                    character_add_color="#ccccff",
                    character_match_color="#ccffcc",
                )
        return self.background_colors_cache


class CallLabel(QLabel):
    call: str = None

    def __init__(
        self,
        *args,
        call=None,
        callback=None,
    ):
        super().__init__(*args)
        self.call = call
        self.callback = callback

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.call and self.callback:
            self.callback(self.call)
