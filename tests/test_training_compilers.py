"""Tests for the compilers training module."""

import unittest

from research.training.compilers.core import (
    Lexer, Parser, compile_and_run,
)


class TestLexer(unittest.TestCase):

    def test_numbers(self):
        tokens = Lexer("42").tokenize()
        self.assertEqual(tokens[0].type, "NUMBER")
        self.assertEqual(tokens[0].value, 42)

    def test_floats(self):
        tokens = Lexer("3.14").tokenize()
        self.assertEqual(tokens[0].type, "NUMBER")
        self.assertEqual(tokens[0].value, 3.14)

    def test_strings(self):
        tokens = Lexer('"hello"').tokenize()
        self.assertEqual(tokens[0].type, "STRING")
        self.assertEqual(tokens[0].value, "hello")

    def test_identifiers(self):
        tokens = Lexer("my_var").tokenize()
        self.assertEqual(tokens[0].type, "IDENT")
        self.assertEqual(tokens[0].value, "my_var")

    def test_keywords(self):
        tokens = Lexer("let def return").tokenize()
        self.assertEqual(tokens[0].type, "KEYWORD")
        self.assertEqual(tokens[0].value, "let")

    def test_operators(self):
        tokens = Lexer("+ - * / < > <= >= == !=").tokenize()
        ops = [t.value for t in tokens if t.type == "OP"]
        self.assertIn("<=", ops)
        self.assertIn(">=", ops)
        self.assertIn("==", ops)

    def test_comments(self):
        tokens = Lexer("42 # this is a comment").tokenize()
        self.assertEqual(tokens[0].value, 42)
        self.assertEqual(tokens[1].type, "EOF")

    def test_eof(self):
        tokens = Lexer("").tokenize()
        self.assertEqual(tokens[0].type, "EOF")


class TestParser(unittest.TestCase):

    def _parse(self, source):
        tokens = Lexer(source).tokenize()
        return Parser(tokens).parse()

    def test_number_expr(self):
        program = self._parse("42")
        self.assertIsNotNone(program)

    def test_let(self):
        program = self._parse("let x = 5")
        self.assertIsNotNone(program)

    def test_if(self):
        program = self._parse("if (1 < 2) { let y = 3 }")
        self.assertIsNotNone(program)

    def test_while(self):
        program = self._parse("while (x < 10) { x = x + 1 }")
        self.assertIsNotNone(program)

    def test_func_def(self):
        program = self._parse("def add(a, b) { return a + b }")
        self.assertIsNotNone(program)

    def test_print(self):
        program = self._parse("print(42)")
        self.assertIsNotNone(program)


class TestVM(unittest.TestCase):

    def test_arithmetic(self):
        vm, result = compile_and_run("2 + 3 * 4")
        self.assertEqual(result, 14)

    def test_arithmetic_precedence(self):
        vm, result = compile_and_run("(2 + 3) * 4")
        self.assertEqual(result, 20)

    def test_division(self):
        vm, result = compile_and_run("10 / 2")
        self.assertEqual(result, 5.0)

    def test_modulo(self):
        vm, result = compile_and_run("10 % 3")
        self.assertEqual(result, 1)

    def test_comparison(self):
        vm, result = compile_and_run("5 < 3")
        self.assertFalse(result)

    def test_equality(self):
        vm, result = compile_and_run("5 == 5")
        self.assertTrue(result)

    def test_assignment(self):
        vm, result = compile_and_run("let x = 10; x + 5")
        self.assertEqual(result, 15)

    def test_let_scope(self):
        vm, result = compile_and_run("let x = 3; x * x")
        self.assertEqual(result, 9)

    def test_print_statement(self):
        vm, result = compile_and_run("print(42)")
        self.assertIn("42", vm.output)

    def test_bool_literals(self):
        vm, result = compile_and_run("true")
        self.assertTrue(result)
        vm, result = compile_and_run("false")
        self.assertFalse(result)


class TestVMControlFlow(unittest.TestCase):

    def test_if_then(self):
        source = "if (true) { 1 } else { 2 }"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 1)

    def test_if_else(self):
        source = "if (false) { 1 } else { 2 }"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 2)

    def test_nested_if(self):
        source = "if (true) { if (true) { 42 } } else { 0 }"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 42)

    def test_while_loop(self):
        source = "let x = 0; while (x < 5) { x = x + 1 }; x"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 5)

    def test_while_with_print(self):
        source = "let x = 0; while (x < 3) { print(x); x = x + 1 }"
        vm, result = compile_and_run(source)
        self.assertEqual(vm.output, ["0", "1", "2"])


class TestVMFunctions(unittest.TestCase):

    def test_function_call(self):
        source = "def add(a, b) { return a + b }; add(3, 4)"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 7)

    def test_function_with_body(self):
        source = "def square(x) { return x * x }; square(5)"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 25)

    def test_nested_function_call(self):
        source = "def add(a, b) { return a + b }; def double(x) { return x * 2 }; add(double(3), 1)"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 7)

    def test_function_with_assignment(self):
        source = "def count(n) { let i = 0; while (i < n) { i = i + 1 }; return i }; count(10)"
        vm, result = compile_and_run(source)
        self.assertEqual(result, 10)


class TestCompilerPipeline(unittest.TestCase):

    def test_full_pipeline(self):
        source = '''
        let x = 10
        def double(a) { return a * 2 }
        let result = double(x)
        result + 5
        '''
        vm, result = compile_and_run(source)
        self.assertEqual(result, 25)

    def test_error_on_bad_char(self):
        with self.assertRaises(SyntaxError):
            Lexer("@").tokenize()


if __name__ == "__main__":
    unittest.main()
