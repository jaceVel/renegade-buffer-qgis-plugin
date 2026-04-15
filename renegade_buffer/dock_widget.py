import os
import json
import datetime

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QLineEdit, QFileDialog, QHeaderView, QComboBox,
    QAbstractItemView, QGroupBox, QMessageBox, QSizePolicy
)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsCoordinateReferenceSystem, QgsVectorFileWriter,
    QgsWkbTypes, QgsFields
)

from .map_tools import PointBufferTool, LineBufferTool


CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_POI_TYPES = [
    {"name": "Bridge",                              "distance": 20,  "mode": "Line"},
    {"name": "Culvert",                             "distance": 5,   "mode": "Point"},
    {"name": "Floodway (Concrete)",                 "distance": 5,   "mode": "Point"},
    {"name": "Cemetery / Ancient Monuments",        "distance": 50,  "mode": "Point"},
    {"name": "Residence / Building",                "distance": 50,  "mode": "Point"},
    {"name": "Shed (Aluminium / Shelter)",          "distance": 25,  "mode": "Point"},
    {"name": "Surface flow lines (GRE & Steel)",    "distance": 20,  "mode": "Line"},
    {"name": "Oil/gas facility / Separator",        "distance": 60,  "mode": "Point"},
    {"name": "LNG Plant Hazardous Zone",            "distance": 10,  "mode": "Point"},
    {"name": "Well location",                       "distance": 50,  "mode": "Point"},
    {"name": "Water well / Bore",                   "distance": 50,  "mode": "Point"},
    {"name": "Water Reservoir / Dam",               "distance": 25,  "mode": "Point"},
    {"name": "Irrigation Head & Work",              "distance": 50,  "mode": "Point"},
    {"name": "Buried Water Poly Pipeline",          "distance": 25,  "mode": "Line"},
    {"name": "Gas pipeline (buried)",               "distance": 25,  "mode": "Line"},
    {"name": "CO2 injection pipeline (buried)",     "distance": 25,  "mode": "Line"},
    {"name": "HP Gas pipeline",                     "distance": 25,  "mode": "Line"},
    {"name": "Low Pressure Pipeline",               "distance": 30,  "mode": "Line"},
    {"name": "High Pressure Pipeline (>15 Bar)",    "distance": 30,  "mode": "Line"},
    {"name": "Surface electricity cable (1kVAC)",   "distance": 20,  "mode": "Line"},
    {"name": "Cathodic protection line (surface)",  "distance": 20,  "mode": "Line"},
    {"name": "Overhead AC power lines",             "distance": 20,  "mode": "Line"},
    {"name": "Buried Electrical / Comms Cable",     "distance": 25,  "mode": "Line"},
    {"name": "Buried Fibre Optic",                  "distance": 2,   "mode": "Line"},
    {"name": "Petrol Station",                      "distance": 80,  "mode": "Point"},
    {"name": "Gas Compressor / Flare",              "distance": 80,  "mode": "Point"},
    {"name": "Drill & Work-over rig",               "distance": 80,  "mode": "Point"},
    {"name": "Electricity Substation",              "distance": 80,  "mode": "Point"},
    {"name": "Wind Turbine",                        "distance": 80,  "mode": "Point"},
    {"name": "Communication Tower",                 "distance": 80,  "mode": "Point"},
    {"name": "Fauna Habitat / Aboriginal Heritage", "distance": 6,   "mode": "Point"},
]


class RenegadeBufferDock(QDockWidget):

    def __init__(self, canvas, parent=None):
        super().__init__("Renegade Buffer Tool", parent)
        self.canvas = canvas
        self.active_tool = None
        self.prev_tool = None
        self.buffer_layer = None
        self.config = self._load_config()
        self._build_ui()
        self._populate_table()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                # Ensure required keys exist
                if "poi_types" not in data:
                    data["poi_types"] = DEFAULT_POI_TYPES
                if "output_folder" not in data:
                    data["output_folder"] = ""
                return data
            except Exception:
                pass
        return {"output_folder": "", "poi_types": DEFAULT_POI_TYPES}

    def _save_config(self):
        poi_types = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            dist_item = self.table.item(row, 1)
            combo = self.table.cellWidget(row, 2)
            if not (name_item and dist_item and combo):
                continue
            try:
                poi_types.append({
                    "name": name_item.text().strip(),
                    "distance": int(dist_item.text().strip()),
                    "mode": combo.currentText(),
                })
            except ValueError:
                pass

        self.config["poi_types"] = poi_types
        self.config["output_folder"] = self.folder_edit.text().strip()

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
            self.status_label.setText("Defaults saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", str(e))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        # --- Output folder ---
        folder_grp = QGroupBox("Output Folder")
        folder_lay = QHBoxLayout(folder_grp)
        self.folder_edit = QLineEdit(self.config.get("output_folder", ""))
        self.folder_edit.setPlaceholderText("Select folder for vibroseis_buffers.shp …")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_folder)
        folder_lay.addWidget(self.folder_edit)
        folder_lay.addWidget(browse_btn)
        layout.addWidget(folder_grp)

        # --- POI table ---
        table_grp = QGroupBox("POI Types & Safe Distances  (double-click to edit)")
        table_lay = QVBoxLayout(table_grp)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["POI Type", "Dist (m)", "Mode"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 72)
        self.table.setColumnWidth(2, 72)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(340)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        table_lay.addWidget(self.table)

        row_btn_lay = QHBoxLayout()
        add_btn = QPushButton("+ Add Row")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("- Remove Row")
        remove_btn.clicked.connect(self._remove_row)
        save_btn = QPushButton("Save Defaults")
        save_btn.setToolTip("Persist current distances to config.json")
        save_btn.clicked.connect(self._save_config)
        row_btn_lay.addWidget(add_btn)
        row_btn_lay.addWidget(remove_btn)
        row_btn_lay.addWidget(save_btn)
        table_lay.addLayout(row_btn_lay)
        layout.addWidget(table_grp)

        # --- Notes ---
        notes_grp = QGroupBox("Notes (written to shapefile attribute)")
        notes_lay = QVBoxLayout(notes_grp)
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes for next feature …")
        notes_lay.addWidget(self.notes_edit)
        layout.addWidget(notes_grp)

        # --- Activate button ---
        self.activate_btn = QPushButton("Activate Tool")
        self.activate_btn.setCheckable(True)
        self.activate_btn.setMinimumHeight(36)
        self.activate_btn.setStyleSheet(
            "QPushButton { background:#4CAF50; color:white; font-weight:bold; border-radius:4px; }"
            "QPushButton:checked { background:#e53935; }"
            "QPushButton:disabled { background:#bdbdbd; }"
        )
        self.activate_btn.clicked.connect(self._toggle_tool)
        layout.addWidget(self.activate_btn)

        # --- Status ---
        self.status_label = QLabel("Select a POI type, then click Activate Tool.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#555; font-style:italic;")
        layout.addWidget(self.status_label)

        layout.addStretch()
        self.setWidget(root)
        self.setMinimumWidth(360)

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _populate_table(self):
        self.table.setRowCount(0)
        for poi in self.config.get("poi_types", DEFAULT_POI_TYPES):
            self._insert_row(poi["name"], poi["distance"], poi["mode"])
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _insert_row(self, name="New POI", distance=20, mode="Point"):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        dist_item = QTableWidgetItem(str(distance))
        dist_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 1, dist_item)
        combo = QComboBox()
        combo.addItems(["Point", "Line"])
        combo.setCurrentText(mode)
        self.table.setCellWidget(row, 2, combo)

    def _add_row(self):
        self._insert_row()
        self.table.selectRow(self.table.rowCount() - 1)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _browse_folder(self):
        start = self.folder_edit.text() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", start)
        if folder:
            self.folder_edit.setText(folder)

    def _on_row_selected(self):
        # Deactivate tool when user switches POI type mid-session
        if self.activate_btn.isChecked():
            self._deactivate_tool()
            self.activate_btn.setChecked(False)

    # ------------------------------------------------------------------
    # Parameter access (called by map tools on each click)
    # ------------------------------------------------------------------

    def _get_params_for_tool(self):
        row = self.table.currentRow()
        if row < 0:
            return "Unknown", 20, ""
        name = (self.table.item(row, 0).text() if self.table.item(row, 0) else "Unknown")
        try:
            distance = int(self.table.item(row, 1).text())
        except (ValueError, AttributeError):
            distance = 20
        notes = self.notes_edit.text().strip()
        return name, distance, notes

    def _get_selected_row_info(self):
        name, distance, notes = self._get_params_for_tool()
        row = self.table.currentRow()
        combo = self.table.cellWidget(row, 2) if row >= 0 else None
        mode = combo.currentText() if combo else "Point"
        return name, distance, mode, notes

    # ------------------------------------------------------------------
    # Layer management
    # ------------------------------------------------------------------

    def _ensure_layer(self):
        """Create or retrieve the output shapefile as a QGIS layer."""
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "No Output Folder",
                                "Please select an output folder first.")
            return None
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Folder Not Found",
                                f"Folder does not exist:\n{folder}")
            return None

        shp_path = os.path.join(folder, "vibroseis_buffers.shp")

        # Already loaded in this session?
        if self.buffer_layer and self.buffer_layer.isValid():
            return self.buffer_layer

        # Already in the QGIS project?
        for lyr in QgsProject.instance().mapLayers().values():
            src = lyr.source().replace("\\", "/")
            if src == shp_path.replace("\\", "/"):
                self.buffer_layer = lyr
                return lyr

        # Create a new shapefile if it doesn't exist yet
        if not os.path.exists(shp_path):
            fields = QgsFields()
            fields.append(QgsField("poi_type", QVariant.String, "String", 80))
            fields.append(QgsField("buffer_m",  QVariant.Int))
            fields.append(QgsField("notes",     QVariant.String, "String", 200))
            fields.append(QgsField("date",      QVariant.String, "String", 20))

            writer = QgsVectorFileWriter(
                shp_path, "UTF-8", fields,
                QgsWkbTypes.Polygon,
                QgsCoordinateReferenceSystem("EPSG:4326"),
                "ESRI Shapefile"
            )
            err = writer.hasError()
            msg = writer.errorMessage()
            del writer  # must close before opening as layer
            if err != QgsVectorFileWriter.NoError:
                QMessageBox.critical(self, "Shapefile Error",
                                     f"Could not create shapefile:\n{msg}")
                return None

        # Load into QGIS
        layer = QgsVectorLayer(shp_path, "Vibroseis Buffers", "ogr")
        if not layer.isValid():
            QMessageBox.critical(self, "Layer Error",
                                 f"Could not load shapefile:\n{shp_path}")
            return None

        QgsProject.instance().addMapLayer(layer)
        self.buffer_layer = layer
        return layer

    # ------------------------------------------------------------------
    # Feature writing
    # ------------------------------------------------------------------

    def _add_feature(self, buffered_geom, poi_type, distance, notes):
        layer = self.buffer_layer
        if layer is None or not layer.isValid():
            return

        feat = QgsFeature(layer.fields())
        feat.setGeometry(buffered_geom)
        feat["poi_type"] = poi_type
        feat["buffer_m"] = distance
        feat["notes"]    = notes
        feat["date"]     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        ok, added = layer.dataProvider().addFeatures([feat])
        if ok:
            layer.updateExtents()
            layer.triggerRepaint()
            self.canvas.refresh()
            self.notes_edit.clear()
            self.status_label.setText(
                f"Added: {poi_type}  ({distance} m buffer)  "
                + ("— " + notes if notes else "")
            )
        else:
            self.status_label.setText("ERROR: feature could not be written.")

    # ------------------------------------------------------------------
    # Tool activation / deactivation
    # ------------------------------------------------------------------

    def _toggle_tool(self, checked):
        if checked:
            self._activate_tool()
        else:
            self._deactivate_tool()

    def _activate_tool(self):
        name, distance, mode, notes = self._get_selected_row_info()
        if not name or name == "Unknown":
            QMessageBox.warning(self, "No Selection",
                                "Please select a POI type from the table.")
            self.activate_btn.setChecked(False)
            return

        layer = self._ensure_layer()
        if layer is None:
            self.activate_btn.setChecked(False)
            return

        self.prev_tool = self.canvas.mapTool()

        if mode == "Point":
            self.active_tool = PointBufferTool(
                self.canvas, self._get_params_for_tool, self._add_feature
            )
            hint = "Left-click to place buffer. Click again for next feature."
        else:
            self.active_tool = LineBufferTool(
                self.canvas, self._get_params_for_tool, self._add_feature
            )
            hint = "Left-click to add vertices. Right-click to finish. ESC to cancel current line."

        self.canvas.setMapTool(self.active_tool)
        self.activate_btn.setText("Deactivate Tool")
        self.status_label.setText(
            f"ACTIVE  [{name}  |  {distance} m  |  {mode}]\n{hint}"
        )
        self.status_label.setStyleSheet("color:#1b5e20; font-weight:bold;")

    def _deactivate_tool(self):
        if self.active_tool:
            self.canvas.unsetMapTool(self.active_tool)
            self.active_tool = None
        if self.prev_tool:
            self.canvas.setMapTool(self.prev_tool)
        self.activate_btn.setText("Activate Tool")
        self.status_label.setText("Tool deactivated. Select a POI type and activate again.")
        self.status_label.setStyleSheet("color:#555; font-style:italic;")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._save_config()
        self._deactivate_tool()
        super().closeEvent(event)
