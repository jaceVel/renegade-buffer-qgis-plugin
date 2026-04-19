import os
import re
import json
import datetime

from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QLineEdit, QFileDialog, QHeaderView, QComboBox,
    QAbstractItemView, QGroupBox, QMessageBox, QListWidget,
    QListWidgetItem, QSizePolicy
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


def _sanitize_name(name):
    """Convert a POI display name into a safe filename stem."""
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"[\s/\\]+", "_", safe.strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "unknown"


def _next_shp_path(folder, poi_type):
    """
    Return a path like  <folder>/Bridge_001.shp  (next unused number).
    Scans existing files so Bridge_001 and Bridge_002 are never overwritten.
    """
    base = _sanitize_name(poi_type)
    n = 1
    while True:
        path = os.path.join(folder, f"{base}_{n:03d}.shp")
        if not os.path.exists(path):
            return path
        n += 1


class RenegadeBufferDock(QDockWidget):

    def __init__(self, canvas, parent=None):
        super().__init__("Renegade Buffer Tool", parent)
        self.canvas = canvas
        self.active_tool = None
        self.prev_tool = None
        self.active_layer = None   # layer for the current activation session
        self.config = self._load_config()
        self._build_ui()
        self._populate_table()
        QgsProject.instance().layersWillBeRemoved.connect(self._on_layers_will_be_removed)
        self._refresh_file_list()
        self.status_label.setText(
            "Loaded " + datetime.datetime.now().strftime("%H:%M:%S")
            + "  —  Select a POI type, then Activate Tool."
        )

    # ------------------------------------------------------------------
    # Layer validity helpers
    # ------------------------------------------------------------------

    def _on_layers_will_be_removed(self, layer_ids):
        """Clear active_layer reference before QGIS destroys the C++ object."""
        if self.active_layer is None:
            return
        try:
            if self.active_layer.id() in layer_ids:
                self.active_layer = None
        except RuntimeError:
            self.active_layer = None

    def _active_layer_valid(self):
        """Return True only if active_layer exists and its C++ object is alive."""
        if self.active_layer is None:
            return False
        try:
            return self.active_layer.isValid()
        except RuntimeError:
            self.active_layer = None
            return False

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
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
        self.folder_edit.setPlaceholderText("Select folder for shapefiles …")
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_folder)
        folder_lay.addWidget(self.folder_edit)
        folder_lay.addWidget(browse_btn)
        layout.addWidget(folder_grp)
        self.folder_edit.textChanged.connect(self._refresh_file_list)

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
        self.table.setMinimumHeight(300)
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

        # --- Created shapefiles list ---
        files_grp = QGroupBox("Created Shapefiles")
        files_lay = QVBoxLayout(files_grp)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.setMaximumHeight(130)
        self.file_list.setMinimumHeight(60)
        self.file_list.setAlternatingRowColors(True)
        files_lay.addWidget(self.file_list)

        file_btn_lay = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setStyleSheet(
            "QPushButton { background:#e53935; color:white; font-weight:bold; border-radius:4px; }"
            "QPushButton:disabled { background:#bdbdbd; }"
        )
        delete_btn.clicked.connect(self._delete_selected_shp)
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self._refresh_file_list)
        file_btn_lay.addWidget(delete_btn)
        file_btn_lay.addWidget(refresh_btn)
        files_lay.addLayout(file_btn_lay)
        layout.addWidget(files_grp)

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
        if self.activate_btn.isChecked():
            self._deactivate_tool()
            self.activate_btn.setChecked(False)

    # ------------------------------------------------------------------
    # File list helpers
    # ------------------------------------------------------------------

    def _refresh_file_list(self):
        """Scan the output folder and repopulate the shapefiles list."""
        self.file_list.clear()
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            return
        shp_files = sorted(
            f for f in os.listdir(folder) if f.lower().endswith(".shp")
        )
        for fname in shp_files:
            item = QListWidgetItem(fname)
            item.setData(Qt.UserRole, os.path.join(folder, fname))
            self.file_list.addItem(item)

    def _delete_selected_shp(self):
        """Delete the shapefile selected in the list from disk and QGIS."""
        item = self.file_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Nothing Selected",
                                    "Select a shapefile from the list first.")
            return

        shp_path = item.data(Qt.UserRole)
        fname = item.text()

        reply = QMessageBox.question(
            self, "Delete Shapefile",
            f"Permanently delete  {fname}  and all its sidecar files?\n\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Deactivate tool if it's writing to this file
        if self.activate_btn.isChecked():
            self._deactivate_tool()
            self.activate_btn.setChecked(False)

        # Remove from QGIS project if loaded — check active_layer first, then all layers
        norm_path = shp_path.replace("\\", "/")
        removed_active = False
        try:
            if (self.active_layer is not None
                    and self.active_layer.source().replace("\\", "/") == norm_path):
                QgsProject.instance().removeMapLayer(self.active_layer.id())
                self.active_layer = None
                removed_active = True
        except RuntimeError:
            self.active_layer = None
            removed_active = True

        if not removed_active:
            for lid, lyr in list(QgsProject.instance().mapLayers().items()):
                try:
                    if lyr.source().replace("\\", "/") == norm_path:
                        QgsProject.instance().removeMapLayer(lid)
                        break
                except RuntimeError:
                    pass

        # Delete sidecar files
        base = os.path.splitext(shp_path)[0]
        failed = []
        for ext in (".shp", ".dbf", ".shx", ".prj", ".cpg", ".qmd", ".qpj", ".sbn", ".sbx"):
            p = base + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError as e:
                    failed.append(f"{ext}: {e}")

        if failed:
            QMessageBox.warning(self, "Partial Delete",
                                "Some files could not be deleted:\n" + "\n".join(failed))
        else:
            self.status_label.setText(f"Deleted: {fname}")
            self.status_label.setStyleSheet("color:#555; font-style:italic;")

        self._refresh_file_list()

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

    def _create_new_layer(self, poi_type):
        """
        Create a brand-new numbered shapefile for poi_type and load it into QGIS.
        Bridge_001.shp, Bridge_002.shp, etc. — never overwrites an existing file.
        """
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "No Output Folder",
                                "Please select an output folder first.")
            return None
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Folder Not Found",
                                f"Folder does not exist:\n{folder}")
            return None

        shp_path = _next_shp_path(folder, poi_type)
        fname = os.path.splitext(os.path.basename(shp_path))[0]
        layer_name = f"{poi_type}  [{fname}]"

        fields = QgsFields()
        fields.append(QgsField("poi_type", QVariant.String, "String", 80))
        fields.append(QgsField("buffer_m",  QVariant.Int))
        fields.append(QgsField("notes",     QVariant.String, "String", 200))
        fields.append(QgsField("date",      QVariant.String, "String", 20))

        writer = QgsVectorFileWriter(
            shp_path, "UTF-8", fields,
            QgsWkbTypes.Polygon,
            QgsProject.instance().crs(),
            "ESRI Shapefile"
        )
        err = writer.hasError()
        msg = writer.errorMessage()
        del writer
        if err != QgsVectorFileWriter.NoError:
            QMessageBox.critical(self, "Shapefile Error",
                                 f"Could not create shapefile:\n{msg}")
            return None

        layer = QgsVectorLayer(shp_path, layer_name, "ogr")
        if not layer.isValid():
            QMessageBox.critical(self, "Layer Error",
                                 f"Could not load shapefile:\n{shp_path}")
            return None

        QgsProject.instance().addMapLayer(layer)
        self.active_layer = layer
        self._refresh_file_list()
        return layer

    # ------------------------------------------------------------------
    # Feature writing
    # ------------------------------------------------------------------

    def _add_feature(self, buffered_geom, poi_type, distance, notes):
        if not self._active_layer_valid():
            return
        layer = self.active_layer

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
            self.status_label.setStyleSheet("color:#555; font-style:italic;")
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

        layer = self._create_new_layer(name)
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
            hint = "Left-click to add vertices. Right-click to finish. ESC to cancel."

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
        self.active_layer = None
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
