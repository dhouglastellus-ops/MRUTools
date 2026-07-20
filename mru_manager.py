from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from qgis.PyQt.QtCore import QSettings

from .utils import normalize_path, sanitize_name


@dataclass(slots=True)
class MRUEntry:
    name: str
    path: str
    group: str = "default"


@dataclass(slots=True)
class MRUManager:
    organization: str = "MRUTools"
    application: str = "MRUTools"
    _settings: QSettings = field(init=False)

    def __post_init__(self) -> None:
        self._settings = QSettings(self.organization, self.application)

    def _group_key(self, group: str) -> str:
        return f"mrus/{group}"

    def _groups_key(self) -> str:
        return "mrus/groups"

    def _normalize_group(self, group: str) -> str:
        return group.strip() or "default"

    def get_groups(self) -> list[str]:
        groups = self._settings.value(self._groups_key(), ["default"])
        if isinstance(groups, str):
            return [groups]
        return [str(item) for item in groups]

    def load_group(self, group: str) -> list[MRUEntry]:
        normalized_group = self._normalize_group(group)
        values = self._settings.value(self._group_key(normalized_group), [])
        if isinstance(values, str):
            values = [values]

        entries: list[MRUEntry] = []
        for raw_value in values:
            if not isinstance(raw_value, str):
                continue
            parts = raw_value.split("|", 2)
            if len(parts) != 3:
                continue
            name, path, stored_group = parts
            entries.append(MRUEntry(name=name, path=path, group=stored_group or normalized_group))
        return entries

    def save_group(self, group: str, entries: Iterable[MRUEntry]) -> None:
        normalized_group = self._normalize_group(group)
        serialized = [f"{entry.name}|{entry.path}|{entry.group}" for entry in entries]
        self._settings.setValue(self._group_key(normalized_group), serialized)

        groups = self.get_groups()
        if normalized_group not in groups:
            groups.append(normalized_group)
            self._settings.setValue(self._groups_key(), groups)

    def add_entry(self, group: str, name: str, path: str) -> None:
        normalized_group = self._normalize_group(group)
        entries = self.load_group(normalized_group)

        cleaned_path = normalize_path(path)
        if not cleaned_path:
            return

        filtered_entries = [entry for entry in entries if entry.path != cleaned_path or entry.group != normalized_group]
        filtered_entries.insert(0, MRUEntry(name=sanitize_name(name) or cleaned_path, path=cleaned_path, group=normalized_group))
        self.save_group(normalized_group, filtered_entries)

    def remove_entry(self, group: str, path: str) -> None:
        normalized_group = self._normalize_group(group)
        entries = self.load_group(normalized_group)
        filtered = [entry for entry in entries if not (entry.path == normalize_path(path) and entry.group == normalized_group)]
        self.save_group(normalized_group, filtered)

    def move_to_top(self, group: str, path: str) -> None:
        normalized_group = self._normalize_group(group)
        entries = self.load_group(normalized_group)
        matching = [entry for entry in entries if entry.path == normalize_path(path) and entry.group == normalized_group]
        if not matching:
            return

        entry = matching[0]
        filtered = [item for item in entries if not (item.path == normalize_path(path) and item.group == normalized_group)]
        filtered.insert(0, entry)
        self.save_group(normalized_group, filtered)

    def clear_group(self, group: str) -> None:
        normalized_group = self._normalize_group(group)
        self._settings.setValue(self._group_key(normalized_group), [])
