import pytest

from app.ranking import Formula, FormulaError

VALUES = dict(sources=3, articles=4, age_hours=8, update_hours=1, weight=1.0, max_weight=1.3, local=0)


def test_formula_evaluates():
    f = Formula("log2(1 + sources) + 2 * 0.5 ** (age_hours / hl) + weight", {"hl": 8})
    assert f.score(**VALUES) == pytest.approx(2 + 1 + 1)


def test_more_sources_rank_higher():
    f = Formula("1.2 * log2(1 + sources) + 2.0 * 0.5 ** (age_hours / 8) + 0.6 * weight")
    assert f.score(**{**VALUES, "sources": 5}) > f.score(**VALUES)
    assert f.score(**{**VALUES, "age_hours": 1}) > f.score(**VALUES)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('x')",
    "sources.__class__",
    "[x for x in range(3)]",
    "unknown_var + 1",
    "open('/etc/passwd')",
    "lambda: 1",
])
def test_formula_rejects_unsafe_expressions(expr):
    with pytest.raises(FormulaError):
        Formula(expr)


def test_formula_math_errors_are_caught():
    with pytest.raises(FormulaError):
        Formula("1 / (sources - sources)")
