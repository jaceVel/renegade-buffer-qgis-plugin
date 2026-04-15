from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt
from .dock_widget import RenegadeBufferDock


class RenegadeBuffer:
    """Main QGIS plugin class."""

    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        self.action = QAction("Renegade Buffer Tool", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Open/close the Renegade vibroseis buffer tool")
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Renegade", self.action)

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.close()
            self.dock = None
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("Renegade", self.action)

    def toggle_dock(self):
        if self.dock is None:
            self.dock = RenegadeBufferDock(
                self.iface.mapCanvas(),
                self.iface.mainWindow()
            )
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            # Keep toolbar button in sync with dock visibility
            self.dock.visibilityChanged.connect(self.action.setChecked)
        else:
            self.dock.setVisible(not self.dock.isVisible())
