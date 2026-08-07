from __future__ import annotations

import ast
import inspect
import textwrap

import pytest


@pytest.mark.parametrize(
    ("initial_lufs", "expected_gain_db"),
    [
        (-8.0, 0.0),
        (-13.9, 0.0),
        (-14.0, 0.0),
        (-20.0, 6.0),
        (-30.0, 8.0),
    ],
)
def test_input_pre_gain_policy_is_preserved(
    core_dsp_module,
    initial_lufs: float,
    expected_gain_db: float,
):
    gain_db = core_dsp_module.calculate_input_pre_gain_db(initial_lufs)
    assert gain_db == pytest.approx(expected_gain_db, abs=1e-9)


def test_masterize_contains_no_noise_gate_call(core_dsp_module):
    source = textwrap.dedent(inspect.getsource(core_dsp_module.masterize))
    tree = ast.parse(source)

    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "NoiseGate" not in called_names
