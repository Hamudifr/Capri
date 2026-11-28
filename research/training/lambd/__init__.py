"""Type theory and lambda calculus study modules."""

from research.training.lambd.calculus import (
    var, abs, app, is_var, is_abs, is_app,
    free_vars, alpha_convert, beta_reduce,
    beta_normal_form, beta_reduce_all, eta_reduce,
    beta_eta_normal_form,
    church_true, church_false, church_if,
    church_and, church_or, church_not,
    church_zero, church_one, church_succ,
    church_add, church_multiply, church_pred,
    church_to_int, int_to_church,
    base_type, arrow_type, type_equals, type_pretty,
    t_var, t_abs, t_app, infer_type, check_type,
    type_of,
)

__all__ = [
    "var", "abs", "app", "is_var", "is_abs", "is_app",
    "free_vars", "alpha_convert", "beta_reduce",
    "beta_normal_form", "beta_reduce_all", "eta_reduce",
    "beta_eta_normal_form",
    "church_true", "church_false", "church_if",
    "church_and", "church_or", "church_not",
    "church_zero", "church_one", "church_succ",
    "church_add", "church_multiply", "church_pred",
    "church_to_int", "int_to_church",
    "base_type", "arrow_type", "type_equals", "type_pretty",
    "t_var", "t_abs", "t_app", "infer_type", "check_type",
    "type_of",
]
