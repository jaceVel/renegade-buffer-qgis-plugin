from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import (
    QgsWkbTypes, QgsGeometry, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


def _get_utm_crs(geom_project_crs, project_crs):
    """
    Derive an appropriate UTM CRS by converting the geometry centroid to
    geographic coordinates, then picking the matching UTM zone.
    """
    crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
    to_4326 = QgsCoordinateTransform(project_crs, crs_4326, QgsProject.instance())
    centroid = geom_project_crs.centroid().asPoint()
    pt = to_4326.transform(centroid)
    zone = int((pt.x() + 180) / 6) + 1
    return QgsCoordinateReferenceSystem(f"EPSG:{32700 + zone}")


def buffer_in_meters(geom, distance_m, segments=64):
    """
    Buffer a geometry (in the current project CRS) by distance_m metres.
    Projects to UTM for accurate metric buffering, then returns the result
    in the original project CRS so it can be written directly to the layer.
    """
    project_crs = QgsProject.instance().crs()
    crs_utm = _get_utm_crs(geom, project_crs)

    to_utm = QgsCoordinateTransform(project_crs, crs_utm, QgsProject.instance())
    to_project = QgsCoordinateTransform(crs_utm, project_crs, QgsProject.instance())

    g = QgsGeometry(geom)
    g.transform(to_utm)
    buffered = g.buffer(distance_m, segments)
    buffered.transform(to_project)
    return buffered


class PointBufferTool(QgsMapTool):
    """Single left-click places a circular buffer polygon."""

    def __init__(self, canvas, get_params_fn, add_feature_fn):
        super().__init__(canvas)
        self.canvas = canvas
        self.get_params = get_params_fn
        self.add_feature = add_feature_fn
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            point = self.toMapCoordinates(event.pos())
            poi_type, distance, notes = self.get_params()
            geom = QgsGeometry.fromPointXY(point)
            buffered = buffer_in_meters(geom, distance)
            self.add_feature(buffered, poi_type, distance, notes)


class LineBufferTool(QgsMapTool):
    """Left-click adds vertices; right-click finishes and writes buffer. ESC cancels."""

    def __init__(self, canvas, get_params_fn, add_feature_fn):
        super().__init__(canvas)
        self.canvas = canvas
        self.get_params = get_params_fn
        self.add_feature = add_feature_fn
        self.points = []
        self.rb_committed = None
        self.rb_preview = None
        self.setCursor(Qt.CrossCursor)

    def activate(self):
        super().activate()
        self.points = []
        self._init_rubber_bands()

    def deactivate(self):
        self._reset()
        super().deactivate()

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
