"""Ranking-Formel aus der Konfiguration – sicher ausgewertet (nur Arithmetik, kein eval)."""
from __future__ import annotations

import ast
import math
import operator

VARIABLES = ("sources", "articles", "age_hours", "update_hours", "weight", "max_weight", "local")
FUNCTIONS = {"log": math.log, "log2": math.log2, "log10": math.log10, "exp": math.exp,
             "sqrt": math.sqrt, "min": min, "max": max, "abs": abs}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


class FormulaError(ValueError):
    pass


class Formula:
    def __init__(self, expr: str, constants: dict | None = None):
        self.expr = expr
        self.constants = {k: float(v) for k, v in (constants or {}).items()}
        try:
            self.tree = ast.parse(expr, mode="eval").body
        except SyntaxError as e:
            raise FormulaError(f"Ranking-Formel ungültig: {e.msg}") from e
        self._check(self.tree)
        # Probelauf mit typischen Werten, damit Fehler beim Laden auffallen
        self.score(sources=2, articles=3, age_hours=5, update_hours=1, weight=1, max_weight=1.2, local=0)

    def _check(self, node):
        allowed = set(VARIABLES) | set(self.constants)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return
        if isinstance(node, ast.Name):
            if node.id not in allowed:
                raise FormulaError(f"Ranking-Formel: unbekannte Variable '{node.id}'")
            return
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            self._check(node.left)
            self._check(node.right)
            return
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
            self._check(node.operand)
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in FUNCTIONS and not node.keywords):
            for a in node.args:
                self._check(a)
            return
        raise FormulaError(f"Ranking-Formel: nicht erlaubter Ausdruck '{ast.unparse(node)}'")

    def score(self, **values) -> float:
        env = {**self.constants, **values}

        def ev(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return env[node.id]
            if isinstance(node, ast.BinOp):
                return BINOPS[type(node.op)](ev(node.left), ev(node.right))
            if isinstance(node, ast.UnaryOp):
                return UNARY[type(node.op)](ev(node.operand))
            return FUNCTIONS[node.func.id](*(ev(a) for a in node.args))

        try:
            result = float(ev(self.tree))
        except (ArithmeticError, ValueError, TypeError) as e:
            raise FormulaError(f"Ranking-Formel: Rechenfehler ({e})") from e
        return result if math.isfinite(result) else 0.0
