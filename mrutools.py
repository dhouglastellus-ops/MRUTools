from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QDockWidget

from .dialog import MRUDockWidget


class MRUTools:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.dock_widget: QDockWidget | None = None

    def initGui(self) -> None:
        self.action = QAction("MRU Tools", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("MRU Tools", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:
        if self.action is not None:
            self.iface.removePluginMenu("MRU Tools", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    def run(self) -> None:
        if self.dock_widget is None:
            self.dock_widget = MRUDockWidget(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
        self.dock_widget.show()
        self.dock_widget.raise_()
        self.dock_widget.setFocus()
