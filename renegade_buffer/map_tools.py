from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import (
    QgsWkbTypes, QgsGeometry, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor


def _get_utm_crs(lon):
    """Return a UTM CRS (southern hemisphere) appropriate for the given longitude."""
    zone = int((lon + 180) / 6) + 1
    return QgsCoordinateReferenceSystem(f"EPSG:{32700 + zone}")


def buffer_in_meters(geom_4326, distance_m, segments=64):
    """
    Buffer a WGS84 geometry by distance_m metres.
    Internally reprojects to the appropriate UTM zone, buffers, then
    reprojects back to EPSG:4326. Returns a new QgsGeometry.
    """
    centroid = geom_4326.centroid().asPoint()
    crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
    crs_utm = _get_utm_crs(centroid.x())

    to_utm = QgsCoordinateTransform(crs_4326, crs_utm, QgsProject.instance())
    to_4326 = QgsCoordinateTransform(crs_utm, crs_4326, QgsProject.instance())

    geom = QgsGeometry(geom_4326)
    geom.transform(to_utm)
    buffered = geom.buffer(distance_m, segments)
    buffered.transform(to_4326)
    return buffered


class PointBufferTool(QgsMapTool):
    """
    Map tool: single left-click places a circular buffer polygon.
    Each click immediately writes a feature to the output layer.
    """

    def __init__(self, canvas, get_params_fn, add_feature_fn):
        super().__init__(canvas)
        self.canvas = canvas
        self.get_params = get_params_fn      # () -> (poi_type, distance, notes)
        self.add_feature = add_feature_fn   # (geom, poi_type, distance, notes)
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = self.toMapCoordinates(event.pos())
            poi_type, distance, notes = self.get_params()
            geom = QgsGeometry.fromPointXY(point)
            buffered = buffer_in_meters(geom, distance)
            self.add_feature(buffered, poi_type, distance, notes)


class LineBufferTool(QgsMapTool):
    """
    Map tool: left-click adds vertices to a polyline; right-click
    finishes and writes a buffered polygon around the line.
    ESC cancels the current line without writing.
    """

    def __init__(self, canvas, get_params_fn, add_feature_fn):
        super().__init__(canvas)
        self.canvas = canvas
        self.get_params = get_params_fn
        self.add_feature = add_feature_fn
        self.points = []
        self.rb_committed = None   # solid line showing committed vertices
        self.rb_preview = None     # dashed line from last vertex to cursor
        self.setCursor(Qt.CrossCursor)

    def activate(self):
        super().activate()
        self.points = []
        self._init_rubber_bands()

    def deactivate(self):
        self._reset()
        super().deactivate()

    # ------------------------------------------------------------------
    # Rubber-band helpers
    # ------------------------------------------------------------------

    def _init_rubber_bands(self):
        self.rb_committed = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb_committed.setColor(QColor(255, 80, 0, 220))
        self.rb_committed.setWidth(2)

        self.rb_preview = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rb_preview.setColor(QColor(255, 80, 0, 100))
        self.rb_preview.setWidth(1)

    def _reset(self):
        if self.rb_committed:
            self.rb_committed.reset()
            self.rb_committed = None
        if self.rb_preview:
            self.rb_preview.reset()
            self.rb_preview = None
        self.points = []

    def _clear_preview(self):
        if self.rb_preview:
            self.rb_preview.reset()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            self.rb_committed.addPoint(point)

        elif event.button() == Qt.RightButton:
            if len(self.points) >= 2:
                poi_type, distance, notes = self.get_params()
                geom = QgsGeometry.fromPolylineXY(self.points)
                buffered = buffer_in_meters(geom, distance)
                self.add_feature(buffered, poi_type, distance, notes)
            # Reset for next feature without deactivating the tool
            self.points = []
            if self.rb_committed:
                self.rb_committed.reset()
            self._clear_preview()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        cursor_pt = self.toMapCoordinates(event.pos())
        self._clear_preview()
        self.rb_preview.addPoint(self.points[-1])
        self.rb_preview.addPoint(cursor_pt)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.points = []
            if self.rb_committed:
                self.rb_committed.reset()
            self._clear_preview()
