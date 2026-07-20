from __future__ import annotations

import os
from typing import Optional

from qgis.core import QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import QCompleter, QDockWidget, QWidget


class MRUDockWidget(QDockWidget):
    def __init__(self, parent: Optional[QWidget] = None, manager: Optional[object] = None) -> None:
        super().__init__("MRU Tools", parent)
        self.manager = manager
        self._load_ui()
        self._connect_signals()
        self._last_movement: dict[str, object] | None = None
        self._settings = QSettings("MRUTools", "MRUTools")
        self._cached_mru_values: list[str] = []
        self._cached_counts: dict[str, int] = {}
        self._cached_layer_id: str | None = None
        self._cached_mru_field: str | None = None
        self._iface = None
        self.refresh_summary(force_reload=True)

    def _load_ui(self) -> None:
        ui_path = os.path.join(os.path.dirname(__file__), "dialog.ui")
        self._content_widget = QWidget(self)
        uic.loadUi(ui_path, self._content_widget)
        self.setWidget(self._content_widget)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.resize(340, 360)

        self.layer_label = self._content_widget.layer_label
        self.layer_value_label = self._content_widget.layer_value_label
        self.selection_label = self._content_widget.selection_label
        self.selection_value_label = self._content_widget.selection_value_label
        self.origin_label = self._content_widget.origin_label
        self.total_label = self._content_widget.total_label
        self.mru_combo = self._content_widget.mru_combo
        self.refresh_button = self._content_widget.refresh_button
        self.apply_button = self._content_widget.apply_button
        self.repeat_button = self._content_widget.repeat_button
        self.undo_button = self._content_widget.undo_button
        self.status_label = self._content_widget.status_label
        self.last_mru_label = self._content_widget.last_mru_label
        self.destination_label = self._content_widget.destination_label
        self.destination_count_label = self._content_widget.destination_count_label
        self.result_label = self._content_widget.result_label

        self.mru_combo.setEditable(True)
        self.mru_combo.setInsertPolicy(self.mru_combo.NoInsert)

        completer = QCompleter(self.mru_combo.model(), self.mru_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.mru_combo.setCompleter(completer)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_summary)
        self.apply_button.clicked.connect(self.apply_selected_mru)
        self.repeat_button.clicked.connect(self.repeat_last_mru)
        self.undo_button.clicked.connect(self.undo_last_movement)
        self.mru_combo.currentTextChanged.connect(self.refresh_summary)
        if self.mru_combo.lineEdit() is not None:
            self.mru_combo.lineEdit().returnPressed.connect(self.apply_selected_mru)

        from qgis.utils import iface

        self._iface = iface
        if hasattr(self._iface, "currentLayerChanged"):
            self._iface.currentLayerChanged.connect(self._on_active_layer_changed)

    def _get_active_layer(self) -> Optional[QgsVectorLayer]:
        from qgis.utils import iface

        layer = iface.activeLayer()
        if isinstance(layer, QgsVectorLayer):
            return layer
        return None

    def _find_mru_field(self, layer: QgsVectorLayer) -> Optional[str]:
        for name in layer.fields().names():
            if name.strip().lower() == "mru":
                return name
        return None

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _reset_summary_state(self) -> None:
        self.layer_value_label.setText("-")
        self.selection_value_label.setText("-")
        self.origin_label.setText("MRU de origem: -")
        self.total_label.setText("Total da MRU origem: -")
        self.destination_label.setText("MRU destino: -")
        self.destination_count_label.setText("Quantidade atual da MRU destino: -")
        self.result_label.setText("Após a movimentação: -")
        self.last_mru_label.setText("Última MRU: -")
        self.mru_combo.clear()

    def _load_recent_mrus(self) -> list[str]:
        values = self._settings.value("recent_mrus", [])
        if isinstance(values, str):
            values = [values]
        return [str(value) for value in values if str(value).strip()]

    def _save_recent_mru(self, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return

        recent_mrus = self._load_recent_mrus()
        if cleaned in recent_mrus:
            recent_mrus.remove(cleaned)
        recent_mrus.insert(0, cleaned)
        recent_mrus = recent_mrus[:8]
        self._settings.setValue("recent_mrus", recent_mrus)

    def _clear_cached_mru_data(self) -> None:
        self._cached_mru_values = []
        self._cached_counts = {}
        self._cached_layer_id = None
        self._cached_mru_field = None

    def _load_cached_mru_data(self, layer: Optional[QgsVectorLayer], force_reload: bool = False) -> None:
        if layer is None:
            self._clear_cached_mru_data()
            return

        if not force_reload and self._cached_layer_id == layer.id() and self._cached_mru_field is not None:
            return

        self._cached_layer_id = layer.id()
        self._cached_mru_field = self._find_mru_field(layer)
        self._cached_mru_values = []
        self._cached_counts = {}

        if self._cached_mru_field is None:
            return

        field_index = layer.fields().indexOf(self._cached_mru_field)
        if field_index < 0:
            return

        self._cached_mru_values = sorted(
            {
                str(value).strip()
                for value in layer.uniqueValues(field_index)
                if str(value).strip()
            }
        )

        counts: dict[str, int] = {}
        for feature in layer.getFeatures():
            value = feature[self._cached_mru_field]
            text_value = "" if value is None else str(value).strip()
            if text_value:
                counts[text_value] = counts.get(text_value, 0) + 1
        self._cached_counts = counts

    def _on_active_layer_changed(self, layer: Optional[QgsVectorLayer] = None) -> None:
        self.refresh_summary(force_reload=True)

    def _populate_combo_values(self, values: list[str]) -> None:
        recent_mrus = self._load_recent_mrus()
        ordered_values: list[str] = []
        for recent in recent_mrus:
            if recent not in ordered_values:
                ordered_values.append(recent)
        for value in sorted({item for item in values if item}):
            if value not in ordered_values:
                ordered_values.append(value)

        current_text = self.mru_combo.currentText().strip()
        self.mru_combo.blockSignals(True)
        self.mru_combo.clear()
        self.mru_combo.addItems(ordered_values)
        self.mru_combo.blockSignals(False)

        if current_text:
            self.mru_combo.setCurrentText(current_text)
        elif ordered_values:
            self.mru_combo.setCurrentText(ordered_values[0])

    def refresh_summary(self, force_reload: bool = False) -> None:
        layer = self._get_active_layer()
        self.apply_button.setEnabled(False)

        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            self._clear_cached_mru_data()
            self._reset_summary_state()
            return

        self._load_cached_mru_data(layer, force_reload=force_reload)
        self.layer_value_label.setText(layer.name())

        if self._cached_mru_field is None:
            self._set_status("Campo MRU não encontrado na camada.")
            self._reset_summary_state()
            return

        selected_ids = layer.selectedFeatureIds()
        selected_count = len(selected_ids)
        self.selection_value_label.setText(str(selected_count))

        source_values: list[str] = []
        for feature_id in selected_ids:
            feature = layer.getFeature(feature_id)
            value = feature[self._cached_mru_field]
            text_value = "" if value is None else str(value).strip()
            if text_value:
                source_values.append(text_value)

        origin_values = sorted({value for value in source_values if value.strip()})
        if origin_values:
            origin_text = ", ".join(origin_values)
        else:
            origin_text = "—"
        self.origin_label.setText(f"MRU de origem: {origin_text}")

        if origin_values:
            total_text = "; ".join(f"{value} ({self._cached_counts.get(value, 0)})" for value in origin_values)
        else:
            total_text = "0"
        self.total_label.setText(f"Total da MRU origem: {total_text}")

        destination_value = self.mru_combo.currentText().strip()
        self.destination_label.setText(f"MRU destino: {destination_value or '-'}")

        destination_count = self._cached_counts.get(destination_value, 0) if destination_value else 0
        self.destination_count_label.setText(
            f"Quantidade atual da MRU destino: {destination_count}"
        )

        if selected_count and destination_value:
            result_text = f"Origem: {selected_count} instalação(ões) movida(s); Destino: {destination_count + selected_count}"
        else:
            result_text = "Selecione uma MRU destino e pelo menos uma feição."
        self.result_label.setText(f"Após a movimentação: {result_text}")

        if force_reload or self.mru_combo.count() == 0:
            self._populate_combo_values(self._cached_mru_values)

        last_mru = self._load_recent_mrus()[0] if self._load_recent_mrus() else ""
        self.last_mru_label.setText(f"Última MRU: {last_mru or '-'}")

        self.apply_button.setEnabled(selected_count > 0 and bool(destination_value))
        if selected_count > 0 and destination_value:
            self._set_status("Pronto para aplicar a nova MRU.")
        elif selected_count > 0:
            self._set_status("Escolha uma MRU destino para continuar.")
        else:
            self._set_status("Selecione pelo menos uma feição para alterar a MRU.")

    def apply_selected_mru(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        mru_field = self._find_mru_field(layer)
        if mru_field is None:
            self._set_status("Campo MRU não encontrado na camada.")
            return

        selected_ids = layer.selectedFeatureIds()
        if not selected_ids:
            self._set_status("Selecione pelo menos uma feição para alterar a MRU.")
            return

        new_mru = self.mru_combo.currentText().strip()
        if not new_mru:
            self._set_status("Informe uma MRU válida.")
            return

        field_index = layer.fields().indexOf(mru_field)
        if field_index < 0:
            self._set_status("Campo MRU não encontrado na camada.")
            return

        if not layer.isEditable():
            layer.startEditing()

        previous_values: list[tuple[int, str]] = []
        layer.beginEditCommand("Atualizar MRU")
        try:
            for feature_id in selected_ids:
                feature = layer.getFeature(feature_id)
                previous_value = feature[mru_field]
                if previous_value is None:
                    previous_value = ""
                previous_values.append((feature_id, str(previous_value)))
                layer.changeAttributeValue(feature_id, field_index, new_mru)
            if layer.commitChanges():
                self._save_recent_mru(new_mru)
                self._last_movement = {
                    "layer": layer,
                    "field": mru_field,
                    "changes": previous_values,
                    "new_mru": new_mru,
                }
                self._set_status(f"MRU atualizada para {new_mru} em {len(selected_ids)} feições.")
            else:
                self._set_status("Falha ao salvar as alterações.")
                layer.rollBack()
        finally:
            layer.endEditCommand()

        layer.triggerRepaint()
        if hasattr(layer, "updateExtents"):
            layer.updateExtents()
        from qgis.utils import iface

        iface.mapCanvas().refresh()
        self.refresh_summary(force_reload=True)

    def repeat_last_mru(self) -> None:
        recent_mrus = self._load_recent_mrus()
        if not recent_mrus:
            self._set_status("Nenhuma MRU recente para repetir.")
            return

        self.mru_combo.setCurrentText(recent_mrus[0])
        self.apply_selected_mru()

    def undo_last_movement(self) -> None:
        if self._last_movement is None:
            self._set_status("Nenhuma movimentação para desfazer.")
            return

        layer = self._last_movement.get("layer")
        if not isinstance(layer, QgsVectorLayer):
            self._set_status("Camada não disponível para desfazer.")
            return

        mru_field = self._last_movement.get("field")
        if not isinstance(mru_field, str):
            self._set_status("Campo MRU não disponível para desfazer.")
            return

        field_index = layer.fields().indexOf(mru_field)
        if field_index < 0:
            self._set_status("Campo MRU não encontrado na camada.")
            return

        changes = self._last_movement.get("changes")
        if not isinstance(changes, list):
            self._set_status("Não foi possível restaurar a movimentação.")
            return

        if not layer.isEditable():
            layer.startEditing()

        layer.beginEditCommand("Desfazer MRU")
        try:
            for feature_id, previous_value in changes:
                layer.changeAttributeValue(int(feature_id), field_index, previous_value)
            if layer.commitChanges():
                self._set_status("Última movimentação desfeita com sucesso.")
            else:
                self._set_status("Falha ao desfazer a movimentação.")
                layer.rollBack()
        finally:
            layer.endEditCommand()

        layer.triggerRepaint()
        if hasattr(layer, "updateExtents"):
            layer.updateExtents()
        from qgis.utils import iface

        iface.mapCanvas().refresh()
        self._last_movement = None
        self.refresh_summary()

