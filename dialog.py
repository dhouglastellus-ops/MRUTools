from __future__ import annotations

import os
from typing import Optional

from qgis.core import QgsField, QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtWidgets import QCompleter, QDockWidget, QFileDialog, QMessageBox, QWidget

try:
    from qgis.PyQt.QtCore import QVariant
except ImportError:  # pragma: no cover - compatibilidade com versões sem QVariant
    QVariant = None

try:
    from qgis.core import QgsNullVariant
except ImportError:  # pragma: no cover - compatibilidade com versões sem QgsNullVariant
    QgsNullVariant = None


def excel_value(value):
    if value is None:
        return None

    if QgsNullVariant is not None and isinstance(value, QgsNullVariant):
        return None

    if QVariant is not None and isinstance(value, QVariant):
        if value.isNull():
            return None
        return excel_value(value.value())

    if hasattr(value, "isNull") and callable(getattr(value, "isNull")):
        try:
            if value.isNull():
                return None
        except Exception:
            pass

    if hasattr(value, "value") and callable(getattr(value, "value")):
        try:
            return excel_value(value.value())
        except Exception:
            pass

    if str(value) == "NULL":
        return None

    return value


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
        self._cached_feature_values: dict[int, str] = {}
        self._cached_layer_id: str | None = None
        self._cached_mru_field: str | None = None
        self._cached_result_field: str | None = None
        self._cached_selected_count: int = 0
        self._iface = None
        self.refresh_summary(force_reload=True)

    def _load_ui(self) -> None:
        ui_path = os.path.join(os.path.dirname(__file__), "dialog.ui")
        self._content_widget = QWidget(self)
        uic.loadUi(ui_path, self._content_widget)
        self.setWidget(self._content_widget)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.resize(340, 420)

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
        self.start_project_button = self._content_widget.start_project_button
        self.restore_project_button = self._content_widget.restore_project_button
        self.cancel_project_button = self._content_widget.cancel_project_button
        self.export_project_button = self._content_widget.export_project_button

        self.mru_combo.setEditable(True)
        self.mru_combo.setInsertPolicy(self.mru_combo.NoInsert)

        completer = QCompleter(self.mru_combo.model(), self.mru_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.mru_combo.setCompleter(completer)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(lambda: self.refresh_summary(force_reload=True))
        self.apply_button.clicked.connect(self.apply_selected_mru)
        self.repeat_button.clicked.connect(self.repeat_last_mru)
        self.undo_button.clicked.connect(self.undo_last_movement)
        self.start_project_button.clicked.connect(self.start_project)
        self.restore_project_button.clicked.connect(self.restore_project)
        self.cancel_project_button.clicked.connect(self.cancel_project)
        self.export_project_button.clicked.connect(self.export_project)
        self.mru_combo.currentTextChanged.connect(self._update_text_input_state)
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

    def _find_field(self, layer: QgsVectorLayer, field_name: str) -> Optional[str]:
        for name in layer.fields().names():
            if name.strip().lower() == field_name.lower():
                return name
        return None

    def _find_mru_field(self, layer: QgsVectorLayer) -> Optional[str]:
        return self._find_field(layer, "mru")

    def _find_result_field(self, layer: QgsVectorLayer) -> Optional[str]:
        return self._find_field(layer, "mru_resultado")

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _reset_summary_state(self) -> None:
        self.layer_value_label.setText("-")
        self.selection_value_label.setText("-")
        self.origin_label.setText("MRU original: -")
        self.total_label.setText("MRU resultado: -")
        self.destination_label.setText("MRU destino: -")
        self.destination_count_label.setText("Quantidade atual: -")
        self.result_label.setText("Quantidade prevista: -")
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
        self._cached_feature_values = {}
        self._cached_layer_id = None
        self._cached_mru_field = None
        self._cached_result_field = None
        self._cached_selected_count = 0

    def _update_text_input_state(self) -> None:
        destination_value = self.mru_combo.currentText().strip()
        self.destination_label.setText(f"MRU destino: {destination_value or '-'}")

        destination_count = self._cached_counts.get(destination_value, 0) if destination_value else 0
        self.destination_count_label.setText(f"Quantidade atual: {destination_count}")

        if self._cached_selected_count and destination_value:
            result_text = (
                f"Origem: {self._cached_selected_count} instalação(ões) movida(s); "
                f"Destino: {destination_count + self._cached_selected_count}"
            )
            self.apply_button.setEnabled(True)
            self._set_status("Pronto para aplicar a nova MRU.")
        elif self._cached_selected_count:
            result_text = "Selecione uma MRU destino e pelo menos uma feição."
            self.apply_button.setEnabled(False)
            self._set_status("Escolha uma MRU destino para continuar.")
        else:
            result_text = "Selecione uma MRU destino e pelo menos uma feição."
            self.apply_button.setEnabled(False)
            self._set_status("Selecione pelo menos uma feição para alterar a MRU.")

        self.result_label.setText(f"Quantidade prevista: {result_text}")

    def _load_cached_mru_data(self, layer: Optional[QgsVectorLayer], force_reload: bool = False) -> None:
        if layer is None:
            self._clear_cached_mru_data()
            return

        if not force_reload and self._cached_layer_id == layer.id() and self._cached_result_field is not None:
            return

        self._cached_layer_id = layer.id()
        self._cached_mru_field = self._find_mru_field(layer)
        self._cached_result_field = self._find_result_field(layer)
        self._cached_mru_values = []
        self._cached_counts = {}
        self._cached_feature_values = {}

        source_field = self._cached_result_field or self._cached_mru_field
        if source_field is None:
            return

        field_index = layer.fields().indexOf(source_field)
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
        feature_values: dict[int, str] = {}
        for feature in layer.getFeatures():
            value = feature[source_field]
            text_value = "" if value is None else str(value).strip()
            feature_values[feature.id()] = text_value
            if text_value:
                counts[text_value] = counts.get(text_value, 0) + 1

        self._cached_counts = counts
        self._cached_feature_values = feature_values

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

    def _copy_field_values(self, layer: QgsVectorLayer, source_field: str, target_field: str) -> bool:
        if not layer.isEditable():
            layer.startEditing()

        field_index = layer.fields().indexOf(target_field)
        source_index = layer.fields().indexOf(source_field)
        if field_index < 0 or source_index < 0:
            return False

        layer.beginEditCommand("Copiar valores de MRU")
        try:
            for feature in layer.getFeatures():
                value = feature[source_field]
                layer.changeAttributeValue(feature.id(), field_index, value)
            return layer.commitChanges()
        except Exception:
            layer.rollBack()
            return False
        finally:
            layer.endEditCommand()

    def _create_result_field(self, layer: QgsVectorLayer) -> Optional[str]:
        mru_field = self._find_mru_field(layer)
        if mru_field is None:
            return None

        mru_index = layer.fields().indexOf(mru_field)
        if mru_index < 0:
            return None

        original_field = layer.fields()[mru_index]
        result_field = QgsField(
            "MRU_RESULTADO",
            original_field.type(),
            original_field.typeName(),
            original_field.length(),
            original_field.precision(),
        )

        provider = layer.dataProvider()
        provider.addAttributes([result_field])
        layer.updateFields()
        return "MRU_RESULTADO"

    def start_project(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        if self._find_mru_field(layer) is None:
            self._set_status("A camada não possui o campo MRU.")
            return

        result_field = self._find_result_field(layer)
        if result_field is None:
            self._set_status("Criando MRU_RESULTADO e copiando os valores da coluna MRU...")
            result_field = self._create_result_field(layer)
            if result_field is None:
                self._set_status("Não foi possível criar a coluna MRU_RESULTADO.")
                return
            if not self._copy_field_values(layer, self._find_mru_field(layer), result_field):
                self._set_status("Falha ao copiar os valores para MRU_RESULTADO.")
                return
            self._set_status("Projeto iniciado com sucesso.")
        else:
            reply = QMessageBox.question(
                self,
                "Projeto de reorganização",
                "MRU_RESULTADO já existe. Deseja continuar o projeto existente ou reiniciar?",
                QMessageBox.StandardButton.Continue | QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Continue,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self._set_status("Operação cancelada.")
                return
            if reply == QMessageBox.StandardButton.Reset:
                self._set_status("Reiniciando o projeto e copiando os valores da coluna MRU...")
                if not self._copy_field_values(layer, self._find_mru_field(layer), result_field):
                    self._set_status("Falha ao reiniciar o projeto.")
                    return
            else:
                self._set_status("Projeto existente continuado.")

        self.refresh_summary(force_reload=True)

    def restore_project(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        reply = QMessageBox.question(
            self,
            "Restaurar projeto",
            "Deseja copiar novamente MRU para MRU_RESULTADO?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._set_status("Restauração cancelada.")
            return

        result_field = self._find_result_field(layer)
        if result_field is None:
            self._set_status("Nenhum projeto ativo para restaurar.")
            return

        mru_field = self._find_mru_field(layer)
        if mru_field is None:
            self._set_status("A camada não possui o campo MRU.")
            return

        if self._copy_field_values(layer, mru_field, result_field):
            self._set_status("Projeto restaurado com sucesso.")
        else:
            self._set_status("Falha ao restaurar o projeto.")
        self.refresh_summary(force_reload=True)

    def cancel_project(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        reply = QMessageBox.question(
            self,
            "Cancelar projeto",
            "Deseja remover completamente MRU_RESULTADO e descartar as alterações do projeto?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._set_status("Cancelamento do projeto abortado.")
            return

        result_field = self._find_result_field(layer)
        if result_field is None:
            self._set_status("Nenhum projeto ativo para cancelar.")
            return

        if not layer.isEditable():
            layer.startEditing()

        layer.beginEditCommand("Remover campo MRU_RESULTADO")
        try:
            field_index = layer.fields().indexOf(result_field)
            if field_index >= 0:
                provider = layer.dataProvider()
                provider.deleteAttributes([field_index])
                layer.updateFields()
            if layer.commitChanges():
                self._set_status("Projeto cancelado com sucesso.")
            else:
                self._set_status("Falha ao cancelar o projeto.")
        except Exception:
            layer.rollBack()
            self._set_status("Falha ao cancelar o projeto.")
        finally:
            layer.endEditCommand()

        self.refresh_summary(force_reload=True)

    def export_project(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        result_field = self._find_result_field(layer)
        if result_field is None:
            self._set_status("Inicie o projeto antes de exportar.")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar projeto", "", "Excel files (*.xlsx)")
        if not file_path:
            self._set_status("Exportação cancelada.")
            return

        try:
            from openpyxl import Workbook
        except ImportError:
            self._set_status("A biblioteca openpyxl não está disponível.")
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "dados"

        fields = list(layer.fields())
        headers = [field.name() for field in fields]
        ws.append([excel_value(value) for value in headers])

        for feature in layer.getFeatures():
            row = []
            for field in fields:
                value = feature[field.name()]
                row.append(value)
            ws.append([excel_value(value) for value in row])

        if not file_path.lower().endswith(".xlsx"):
            file_path = f"{file_path}.xlsx"

        wb.save(file_path)
        self._set_status(f"Projeto exportado para {file_path}.")

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
        self._cached_selected_count = selected_count
        self.selection_value_label.setText(str(selected_count))

        selected_original_values: list[str] = []
        selected_result_values: list[str] = []
        for feature_id in selected_ids:
            feature = layer.getFeature(feature_id)
            original_value = feature[self._cached_mru_field]
            result_value = self._cached_feature_values.get(feature_id, "")
            original_text = "" if original_value is None else str(original_value).strip()
            if original_text:
                selected_original_values.append(original_text)
            if result_value:
                selected_result_values.append(result_value)

        origin_values = sorted({value for value in selected_original_values if value.strip()})
        if origin_values:
            origin_text = ", ".join(origin_values)
        else:
            origin_text = "—"
        self.origin_label.setText(f"MRU original: {origin_text}")

        result_values = sorted({value for value in selected_result_values if value.strip()})
        if result_values:
            result_text = ", ".join(result_values)
        else:
            result_text = "—"
        self.total_label.setText(f"MRU resultado: {result_text}")

        if force_reload or self.mru_combo.count() == 0:
            self._populate_combo_values(self._cached_mru_values)

        last_mru = self._load_recent_mrus()[0] if self._load_recent_mrus() else ""
        self.last_mru_label.setText(f"Última MRU: {last_mru or '-'}")

        if self._cached_result_field is None:
            self._set_status("Projeto não iniciado. Clique em Iniciar Projeto para criar MRU_RESULTADO.")
            self.destination_label.setText("MRU destino: -")
            self.destination_count_label.setText("Quantidade atual: -")
            self.result_label.setText("Quantidade prevista: -")
            return

        self._update_text_input_state()

    def apply_selected_mru(self) -> None:
        layer = self._get_active_layer()
        if layer is None:
            self._set_status("Selecione uma camada vetorial.")
            return

        result_field = self._find_result_field(layer)
        if result_field is None:
            self._set_status("Inicie o projeto antes de aplicar alterações.")
            return

        selected_ids = layer.selectedFeatureIds()
        if not selected_ids:
            self._set_status("Selecione pelo menos uma feição para alterar a MRU.")
            return

        new_mru = self.mru_combo.currentText().strip()
        if not new_mru:
            self._set_status("Informe uma MRU válida.")
            return

        field_index = layer.fields().indexOf(result_field)
        if field_index < 0:
            self._set_status("Campo MRU_RESULTADO não encontrado na camada.")
            return

        if not layer.isEditable():
            layer.startEditing()

        previous_values: list[tuple[int, str]] = []
        layer.beginEditCommand("Atualizar MRU_RESULTADO")
        try:
            for feature_id in selected_ids:
                previous_value = self._cached_feature_values.get(feature_id, "")
                previous_values.append((feature_id, str(previous_value)))
                self._cached_feature_values[feature_id] = new_mru
                layer.changeAttributeValue(feature_id, field_index, new_mru)

            if layer.commitChanges():
                self._save_recent_mru(new_mru)
                self._last_movement = {
                    "layer": layer,
                    "field": result_field,
                    "changes": previous_values,
                    "new_mru": new_mru,
                }
                self._update_cached_counts_after_change(previous_values, new_mru)
                self._set_status(f"MRU_RESULTADO atualizada para {new_mru} em {len(selected_ids)} feições.")
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
        self.refresh_summary(force_reload=False)

    def _update_cached_counts_after_change(self, changes: list[tuple[int, str]], new_mru: str) -> None:
        for feature_id, previous_value in changes:
            previous_value = str(previous_value or "").strip()
            if previous_value:
                self._cached_counts[previous_value] = max(0, self._cached_counts.get(previous_value, 0) - 1)
                if self._cached_counts[previous_value] == 0:
                    self._cached_counts.pop(previous_value, None)
            if new_mru:
                self._cached_counts[new_mru] = self._cached_counts.get(new_mru, 0) + 1
            self._cached_feature_values[feature_id] = new_mru

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
            self._set_status("Campo MRU_RESULTADO não disponível para desfazer.")
            return

        field_index = layer.fields().indexOf(mru_field)
        if field_index < 0:
            self._set_status("Campo MRU_RESULTADO não encontrado na camada.")
            return

        changes = self._last_movement.get("changes")
        if not isinstance(changes, list):
            self._set_status("Não foi possível restaurar a movimentação.")
            return

        if not layer.isEditable():
            layer.startEditing()

        layer.beginEditCommand("Desfazer MRU_RESULTADO")
        try:
            for feature_id, previous_value in changes:
                self._cached_feature_values[int(feature_id)] = previous_value
                layer.changeAttributeValue(int(feature_id), field_index, previous_value)
            if layer.commitChanges():
                self._set_status("Última movimentação desfeita com sucesso.")
                self._rebuild_cached_counts_from_features(layer)
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
        self.refresh_summary(force_reload=False)

    def _rebuild_cached_counts_from_features(self, layer: QgsVectorLayer) -> None:
        result_field = self._find_result_field(layer)
        if result_field is None:
            return

        counts: dict[str, int] = {}
        feature_values: dict[int, str] = {}
        field_index = layer.fields().indexOf(result_field)
        if field_index < 0:
            return

        for feature in layer.getFeatures():
            value = feature[result_field]
            text_value = "" if value is None else str(value).strip()
            feature_values[feature.id()] = text_value
            if text_value:
                counts[text_value] = counts.get(text_value, 0) + 1

        self._cached_counts = counts
        self._cached_feature_values = feature_values

