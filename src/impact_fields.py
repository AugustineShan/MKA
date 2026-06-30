# -*- coding: utf-8 -*-
"""共享：带符号损益调整字段集（减值类），单一真源。

这些字段在 ``income.cost_abs.*`` 下，但引擎 ``calc.py`` 不把它们当正成本计入
``total_cogs``，而是按**带符号**的损益调整以 ``+ impact_adjustment`` 并入
``operate_profit``（见 ``calc.py`` 的 ``IMPACT_ADJUSTMENT_FIELDS`` 用法）。
因此损失必须存**负值**才能扣减利润；写成正数会被引擎当加项加回，静默虚增利润。

本模块是 calc.py（引擎）与 ``yaml1_fidelity_check.py`` / ``ka_assumption_lint.py``
（两道符号门）的共用常量，避免三处硬编码漂移。故意保持无重依赖（不 import pandas /
clean / defaults_gen），供轻量 lint 直接 import。

参考：
- ``skills/yaml1compiler_v5.md`` 附录A「减值符号结论」
- ``docs/knobs块契约.md`` §7 cost_abs 族符号列
"""

IMPACT_ADJUSTMENT_FIELDS = frozenset({
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
})
