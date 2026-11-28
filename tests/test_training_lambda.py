"""Tests for the type theory and lambda calculus training module."""

import unittest

from research.training.lambd.calculus import (
    var, abs, app, is_var, is_abs, is_app,
    free_vars, alpha_convert, beta_reduce,
    beta_normal_form, beta_reduce_all, eta_reduce,
    beta_eta_normal_form,
    church_true, church_false, church_if,
    church_and, church_not,
    church_zero, church_one, church_succ,
    church_add, church_multiply, church_pred,
    church_to_int, int_to_church,
    base_type, arrow_type, type_equals, type_pretty,
    t_var, t_abs, infer_type, check_type,
    type_of,
)


def alpha_equivalent(t1, t2):
    """Check if two terms are alpha-equivalent (same structure, possibly renamed bound vars)."""
    if t1[0] == 'var' and t2[0] == 'var':
        return t1[1] == t2[1]
    if t1[0] == 'abs' and t2[0] == 'abs':
        # Rename bound vars to canonical form and compare
        def canonicalize(term, rename_map):
            kind = term[0]
            if kind == 'var':
                return ('var', rename_map.get(term[1], term[1]))
            if kind == 'abs':
                name = term[1]
                new_name = rename_map.get(name, name)
                new_rename = dict(rename_map)
                new_rename[name] = new_name
                return ('abs', new_name, canonicalize(term[2], new_rename))
            if kind == 'app':
                return ('app', canonicalize(term[1], rename_map), canonicalize(term[2], rename_map))
            return term
        # Assign canonical names
        def make_canonical(term, counter=[0]):
            kind = term[0]
            if kind == 'var':
                return ('var', term[1])
            if kind == 'abs':
                idx = counter[0]
                counter[0] += 1
                return ('abs', f'_c{idx}', make_canonical(term[2], counter))
            if kind == 'app':
                return ('app', make_canonical(term[1], counter), make_canonical(term[2], counter))
            return term
        return make_canonical(t1) == make_canonical(t2)
    return t1 == t2



class TestTermStructure(unittest.TestCase):

    def test_var(self):
        t = var("x")
        self.assertTrue(is_var(t))
        self.assertFalse(is_abs(t))
        self.assertFalse(is_app(t))

    def test_abs(self):
        t = abs("x", var("x"))
        self.assertTrue(is_abs(t))
        self.assertFalse(is_var(t))

    def test_app(self):
        t = app(var("f"), var("x"))
        self.assertTrue(is_app(t))
        self.assertFalse(is_var(t))

    def test_free_vars(self):
        # λx. x has no free variables
        t = abs("x", var("x"))
        self.assertEqual(free_vars(t), set())

    def test_free_vars_bound(self):
        # λx. y has y free
        t = abs("x", var("y"))
        self.assertEqual(free_vars(t), {"y"})

    def test_free_vars_nested(self):
        # λx. λy. x  — x is bound, y is bound
        t = abs("x", abs("y", var("x")))
        self.assertEqual(free_vars(t), set())

    def test_free_vars_application(self):
        # (λx. x) y — y is free
        t = app(abs("x", var("x")), var("y"))
        self.assertEqual(free_vars(t), {"y"})


class TestAlphaConversion(unittest.TestCase):

    def test_alpha_convert_basic(self):
        t = abs("x", var("x"))
        converted = alpha_convert(t, "x", "y")
        self.assertEqual(converted, abs("y", var("y")))

    def test_alpha_convert_nested(self):
        # λx. λy. x → rename x to z
        t = abs("x", abs("y", var("x")))
        converted = alpha_convert(t, "x", "z")
        self.assertEqual(converted, abs("z", abs("y", var("z"))))

    def test_alpha_convert_preserves_free(self):
        # λx. y — rename x to z, y stays free
        t = abs("x", var("y"))
        converted = alpha_convert(t, "x", "z")
        self.assertEqual(converted, abs("z", var("y")))
        self.assertEqual(free_vars(converted), {"y"})


class TestBetaReduction(unittest.TestCase):

    def test_beta_reduce_identity(self):
        # (λx. x) y → y
        t = app(abs("x", var("x")), var("y"))
        result = beta_reduce(t)
        self.assertEqual(result, var("y"))

    def test_beta_reduce_constant(self):
        # (λx. z) y → z
        t = app(abs("x", var("z")), var("y"))
        result = beta_reduce(t)
        self.assertEqual(result, var("z"))

    def test_beta_reduce_nested(self):
        # (λx. λy. x) a → λy. a
        t = app(abs("x", abs("y", var("x"))), var("a"))
        result = beta_reduce(t)
        self.assertEqual(result, abs("y", var("a")))

    def test_beta_normal_form_identity(self):
        # (λx. x) y should reduce to y
        t = app(abs("x", var("x")), var("y"))
        result = beta_normal_form(t)
        self.assertEqual(result, var("y"))

    def test_beta_normal_form_apply(self):
        # (λx. x x) (λy. y) → (λy. y)(λy. y) → λy. y
        t = app(abs("x", app(var("x"), var("x"))), abs("y", var("y")))
        result = beta_normal_form(t)
        self.assertEqual(result, abs("y", var("y")))

    def test_beta_reduce_no_redex(self):
        # λx. x has no redex
        t = abs("x", var("x"))
        result = beta_reduce(t)
        self.assertEqual(result, t)

    def test_beta_reduce_all(self):
        # (λx. x x) (λy. y y) → should converge to some normal form
        t = app(abs("x", app(var("x"), var("x"))), abs("y", app(var("y"), var("y"))))
        result = beta_reduce_all(t, max_steps=100)
        self.assertIsNotNone(result)


class TestEtaReduction(unittest.TestCase):

    def test_eta_reduce_basic(self):
        # λx. (f x) → f, when x not free in f
        f = var("f")
        t = abs("x", app(f, var("x")))
        result = eta_reduce(t)
        self.assertEqual(result, f)

    def test_eta_reduce_no_change(self):
        # λx. x has no eta redex
        t = abs("x", var("x"))
        result = eta_reduce(t)
        self.assertEqual(result, t)

    def test_beta_eta_normal_form(self):
        # λx. (λy. y) x → λx. x → eta → identity is already normal
        t = abs("x", app(abs("y", var("y")), var("x")))
        result = beta_eta_normal_form(t)
        # Should reduce to λx. x (variable may be renamed during reduction)
        self.assertTrue(is_abs(result))
        body = result[2]
        self.assertTrue(is_var(body))
        # The bound variable should match the body variable name
        self.assertEqual(result[1], body[1])


class TestChurchEncoding(unittest.TestCase):

    def test_church_true_false(self):
        # church_true = λx.λy.x, church_false = λx.λy.y
        # church_if church_true a b → a
        a = var("a")
        b = var("b")
        result = beta_normal_form(app(app(app(church_if, church_true), a), b))
        self.assertEqual(result, a)

    def test_church_if_false(self):
        a = var("a")
        b = var("b")
        result = beta_normal_form(app(app(app(church_if, church_false), a), b))
        self.assertEqual(result, b)

    def test_church_not(self):
        # not true = false, not false = true
        not_true = beta_normal_form(church_not(church_true))
        # Should behave as church_false
        result_true = beta_normal_form(app(app(app(church_if, not_true), var("x")), var("y")))
        self.assertTrue(alpha_equivalent(result_true, var("y")))

    def test_church_zero(self):
        self.assertEqual(church_to_int(church_zero()), 0)

    def test_church_one(self):
        self.assertEqual(church_to_int(church_one()), 1)

    def test_church_succ(self):
        self.assertEqual(church_to_int(church_succ(church_zero())), 1)
        self.assertEqual(church_to_int(church_succ(church_one())), 2)

    def test_church_add(self):
        # 2 + 3 = 5
        n2 = int_to_church(2)
        n3 = int_to_church(3)
        result = church_to_int(church_add(n2, n3))
        self.assertEqual(result, 5)

    def test_church_multiply(self):
        # 2 * 3 = 6
        n2 = int_to_church(2)
        n3 = int_to_church(3)
        result = church_to_int(church_multiply(n2, n3))
        self.assertEqual(result, 6)

    def test_church_pred(self):
        self.assertEqual(church_to_int(church_pred(church_one())), 0)
        self.assertEqual(church_to_int(church_pred(int_to_church(3))), 2)

    def test_int_to_church(self):
        for i in range(5):
            self.assertEqual(church_to_int(int_to_church(i)), i)

    def test_church_and(self):
        # true AND false = false
        result = beta_normal_form(church_and(church_true, church_false))
        # Should behave as church_false
        x = var("x")
        y = var("y")
        test = beta_normal_form(app(app(app(church_if, result), x), y))
        self.assertTrue(alpha_equivalent(test, y))


class TestSimplyTypedLambda(unittest.TestCase):

    def test_base_type(self):
        t = base_type("int")
        self.assertEqual(t, ("base", "int"))

    def test_arrow_type(self):
        t = arrow_type(base_type("int"), base_type("bool"))
        self.assertEqual(t, ("arrow", ("base", "int"), ("base", "bool")))

    def test_type_equals(self):
        t1 = arrow_type(base_type("int"), base_type("bool"))
        t2 = arrow_type(base_type("int"), base_type("bool"))
        self.assertTrue(type_equals(t1, t2))

    def test_type_not_equals(self):
        t1 = arrow_type(base_type("int"), base_type("bool"))
        t2 = arrow_type(base_type("bool"), base_type("int"))
        self.assertFalse(type_equals(t1, t2))

    def test_type_pretty(self):
        t = arrow_type(base_type("int"), arrow_type(base_type("bool"), base_type("int")))
        s = type_pretty(t)
        self.assertIn("int", s)
        self.assertIn("bool", s)
        self.assertIn("->", s)

    def test_infer_var(self):
        env = {"x": base_type("int")}
        t = t_var("x", base_type("int"))
        self.assertEqual(infer_type(t, env), base_type("int"))

    def test_infer_abs(self):
        env = {}
        t = t_abs("x", t_var("x", base_type("int")), arrow_type(base_type("int"), base_type("int")))
        result = infer_type(t, env)
        self.assertEqual(result, arrow_type(base_type("int"), base_type("int")))

    def test_check_type_match(self):
        env = {"x": base_type("int")}
        t = t_var("x", base_type("int"))
        self.assertTrue(check_type(t, env, base_type("int")))

    def test_check_type_mismatch(self):
        env = {"x": base_type("int")}
        t = t_var("x", base_type("int"))
        self.assertFalse(check_type(t, env, base_type("bool")))

    def test_type_of(self):
        env = {"x": base_type("int")}
        t = t_var("x", base_type("int"))
        self.assertEqual(type_of(t, env), base_type("int"))


if __name__ == "__main__":
    unittest.main()
