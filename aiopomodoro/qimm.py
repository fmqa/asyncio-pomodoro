"""Hierarchial/ImGui-like layout builder for PySide."""

from contextlib import contextmanager
from functools import singledispatchmethod
from PySide2.QtWidgets import QWidget, QLayout

__all__ = ["immediate"]

class immediate:
    """Stacking layout builder."""

    @singledispatchmethod
    def add(self, item):
        """Pushes a layout or a widget to the layout stack.

        Sets the active layout to the given layout
        Adds the given widget to the active layout"""
        raise ValueError(item)

    @add.register
    @contextmanager
    def _(self, item: QLayout, *args, **kwargs):
        top = getattr(self, "layout", None)
        self.layout = item
        yield self
        if top:
            top.addLayout(item, *args, **kwargs)
            self.layout = top

    @add.register
    def _(self, widget: QWidget, *args, **kwargs):
        self.layout.addWidget(widget, *args, **kwargs)
        return widget

    @classmethod
    @contextmanager
    def on(cls, widget):
        """Enters a layout builder context, sets the given widget's
        layout on exit."""
        imm = cls()
        yield imm
        widget.setLayout(imm.layout)
