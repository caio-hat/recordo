# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Atomic Design — atoms layer.

Widgets básicos componíveis. NÃO contêm business logic.
Devem ser puramente apresentacionais e parametrizáveis.
"""

from .action_button import ActionButton
from .heading import Caption, Heading
from .progress import IndeterminatePulse, LinearBar, Spinner, StepProgress
from .pulse_dot import PulseDot
from .status_badge import StatusBadge

__all__ = [
    "ActionButton",
    "Caption",
    "Heading",
    "IndeterminatePulse",
    "LinearBar",
    "PulseDot",
    "Spinner",
    "StatusBadge",
    "StepProgress",
]
