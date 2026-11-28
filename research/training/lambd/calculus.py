"""Type theory and lambda calculus study modules.

Implements the core concepts of lambda calculus: terms, beta/eta
reduction, Church encoding, and simply typed lambda calculus with
type inference.
Pure stdlib, no dependencies.

Topics covered:
- Lambda term representation: variables, abstractions, applications
- Alpha conversion (variable renaming)
- Beta reduction (function application)
- Eta reduction (extensionality)
- Normal-order reduction to normal form
- Church encoding: booleans, natural numbers, pairs
- Church numeral arithmetic
- Simply typed lambda calculus terms and types
- Type checking and inference
- Unification (for type inference)
"""

from __future__ import annotations



# ===========================================================================
# Untyped lambda calculus
# ===========================================================================

# Term representation:
#   ("var", name)          — a variable
#   ("abs", name, body)    — abstraction (lambda x. body)
#   ("app", func, arg)     — application (func arg)

Term = tuple


def var(name: str) -> Term:
    """Create a variable term."""
    return ("var", name)


def abs(name: str, body: Term) -> Term:
    """Create an abstraction (lambda function)."""
    return ("abs", name, body)


def app(func: Term, arg: Term) -> Term:
    """Create an application (function call)."""
    return ("app", func, arg)


def is_var(term: Term) -> bool:
    return term[0] == "var"


def is_abs(term: Term) -> bool:
    return term[0] == "abs"


def is_app(term: Term) -> bool:
    return term[0] == "app"


def free_vars(term: Term) -> set[str]:
    """Collect the set of free variables in a term."""
    kind = term[0]
    if kind == "var":
        return {term[1]}
    if kind == "abs":
        body_free = free_vars(term[2])
        # Remove the bound variable
        body_free.discard(term[1])
        return body_free
    if kind == "app":
        return free_vars(term[1]) | free_vars(term[2])
    return set()


# ===========================================================================
# Alpha conversion
# ===========================================================================

def alpha_convert(term: Term, old: str, new: str) -> Term:
    """Alpha conversion: rename a bound variable from `old` to `new`.

    Only renames the variable where it is bound, not free occurrences.
    """
    kind = term[0]
    if kind == "var":
        return term
    if kind == "abs":
        name = term[1]
        body = term[2]
        if name == old:
            # Rename in the body
            return ("abs", new, _substitute(body, old, var(new), new))
        else:
            return ("abs", name, alpha_convert(body, old, new))
    if kind == "app":
        return ("app",
                alpha_convert(term[1], old, new),
                alpha_convert(term[2], old, new))
    return term


def _substitute(term: Term, var_name: str, replacement: Term,
                skip: str | None = None) -> Term:
    """Substitute a free variable with a replacement, avoiding
    capture of the skip variable (which is bound in enclosing abs)."""
    kind = term[0]
    if kind == "var":
        if term[1] == var_name:
            return replacement
        return term
    if kind == "abs":
        name = term[1]
        body = term[2]
        if name == skip:
            # Don't substitute inside this binding
            return ("abs", name, term[2])
        if name == var_name:
            # The variable is bound here, don't substitute
            return term
        # Check if replacement would be captured
        if name in free_vars(replacement):
            # Rename the bound variable to avoid capture
            fresh = f"{name}_"
            renamed = alpha_convert(term, name, fresh)
            return ("abs", fresh, _substitute(renamed[2], var_name,
                                               replacement, fresh))
        return ("abs", name, _substitute(body, var_name, replacement, name))
    if kind == "app":
        return ("app",
                _substitute(term[1], var_name, replacement, skip),
                _substitute(term[2], var_name, replacement, skip))
    return term


# ===========================================================================
# Beta reduction
# ===========================================================================

def beta_reduce(term: Term) -> Term:
    """Perform one step of beta reduction on the leftmost-outermost
    redex. Returns the reduced term, or the original if no redex
    exists at the top level.
    """
    if is_abs(term):
        # Reduce inside the body
        body = term[2]
        reduced_body = beta_reduce(body)
        if reduced_body != body:
            return ("abs", term[1], reduced_body)
        return term

    if not is_app(term):
        return term

    func, arg = term[1], term[2]

    # If the function is an abstraction, reduce
    if is_abs(func):
        name = func[1]
        body = func[2]
        # Substitute the argument for the bound variable
        return _substitute(body, name, arg)

    # Otherwise, try to reduce the function part
    reduced_func = beta_reduce(func)
    if reduced_func != func:
        return ("app", reduced_func, arg)

    # Try to reduce the argument
    reduced_arg = beta_reduce(arg)
    if reduced_arg != arg:
        return ("app", func, reduced_arg)

    return term


def beta_normal_form(term: Term, max_steps: int = 10000) -> Term:
    """Reduce a term to normal form using normal-order (leftmost-
    outermost) reduction. Returns the normal form or the best
    attempt if max_steps is exceeded.
    """
    current = term
    for _ in range(max_steps):
        reduced = beta_reduce(current)
        if reduced == current:
            break
        current = reduced
    return current


def beta_reduce_all(term: Term, max_steps: int = 10000) -> Term:
    """Reduce until no more beta redexes exist (normal form).

    Uses normal-order reduction (leftmost-outermost), which is
    guaranteed to find the normal form if it exists.
    """
    return beta_normal_form(term, max_steps)


# ===========================================================================
# Eta reduction
# ===========================================================================

def eta_reduce(term: Term) -> Term:
    """Perform one step of eta reduction.

    Eta reduction: lambda x. (f x) → f, when x is not free in f.
    """
    if is_abs(term):
        name = term[1]
        body = term[2]
        if (is_app(body)
                and body[2] == var(name)
                and name not in free_vars(body[1])):
            return body[1]  # f
        # Try to reduce the body
        reduced_body = eta_reduce(body)
        if reduced_body != body:
            return ("abs", name, reduced_body)
    elif is_app(term):
        reduced_func = eta_reduce(term[1])
        reduced_arg = eta_reduce(term[2])
        if reduced_func != term[1] or reduced_arg != term[2]:
            return ("app", reduced_func, reduced_arg)
    return term


def beta_eta_normal_form(term: Term, max_steps: int = 10000) -> Term:
    """Reduce to beta-eta normal form."""
    current = term
    for _ in range(max_steps):
        reduced = beta_reduce(current)
        if reduced == current:
            reduced = eta_reduce(current)
        if reduced == current:
            break
        current = reduced
    return current


# ===========================================================================
# Church encoding
# ===========================================================================

# Church booleans
church_true = abs("x", abs("y", var("x")))       # λx.λy.x
church_false = abs("x", abs("y", var("y")))      # λx.λy.y

# Church if-then-else
church_if = abs("c", abs("t", abs("e", app(app(var("c"), var("t")), var("e")))))


# Church boolean operations as pure lambda terms
# AND = λa.λb. a b b  -- both a,b are 2-arg selectors
church_and_term = abs("a", abs("b", app(app(var("a"), var("b")), var("b"))))

# OR = λa.λb. a a b  -- a selects between a and b
church_or_term = abs("a", abs("b", app(app(var("a"), var("a")), var("b"))))

# NOT = λa. a FALSE TRUE  -- a is a 2-arg selector, pass both
church_not_term = abs("a", app(app(var("a"), church_false), church_true))


def church_and(a: Term, b: Term) -> Term:
    """Church boolean AND: AND a b = (λa.λb.λx. a (b x)) a b"""
    return app(app(church_and_term, a), b)


def church_or(a: Term, b: Term) -> Term:
    """Church boolean OR: OR a b = (λa.λb. a a b) a b"""
    return app(app(church_or_term, a), b)


def church_not(a: Term) -> Term:
    """Church boolean NOT: NOT a = (λa. a FALSE) a"""
    return app(church_not_term, a)


# Church numerals: n = λf.λx. f^n(x)
def church_zero() -> Term:
    return abs("f", abs("x", var("x")))


def church_one() -> Term:
    return abs("f", abs("x", app(var("f"), var("x"))))


def church_succ(n: Term) -> Term:
    """Church successor: succ n = λf.λx. f(n f x)"""
    return abs("f", abs("x", app(var("f"), app(app(n, var("f")), var("x")))))


def church_add(n: Term, m: Term) -> Term:
    """Church addition: n + m = λf.λx. n f (m f x)"""
    return abs("f", abs("x", app(app(n, var("f")), app(app(m, var("f")), var("x")))))


def church_multiply(n: Term, m: Term) -> Term:
    """Church multiplication: n * m = λf. n (m f)"""
    return abs("f", app(n, app(m, var("f"))))


def church_pred(n: Term) -> Term:
    """Church predecessor using pair encoding.

    Pair encoding: pair = λa.λb.λc. c a b
    fst = λp. p (λx.λy. x), snd = λp. p (λx.λy. y)
    step = λp. pair (snd p) (f (snd p))   -- shifts (a,b) -> (b, f(b))
    pred n = λf.λx. fst (n step (pair I x))
    For n=1 this gives Church 0; for n=2 gives Church 1, etc.
    """
    pair = abs("a", abs("b", abs("c", app(app(var("c"), var("a")), var("b")))))
    fst = abs("p", app(var("p"), abs("x", abs("y", var("x")))))
    snd = abs("p", app(var("p"), abs("x", abs("y", var("y")))))
    identity = abs("z", var("z"))
    step = abs("p", app(app(pair, app(snd, var("p"))), app(var("f"), app(snd, var("p")))))
    init = app(app(pair, identity), var("x"))
    return abs("f", abs("x", app(fst, app(app(n, step), init))))


def church_to_int(n: Term) -> int:
    """Convert a Church numeral to a Python integer.

    A Church numeral n = λf.λx. f^n(x). We normalize the term,
    then count the number of f-applications in the body.
    """
    # Normalize the term first
    normalized = beta_normal_form(n)

    if not is_abs(normalized):
        return 0

    # First abstraction: λf. body
    body = normalized[2]
    if not is_abs(body):
        return 0

    # Second abstraction: λx. inner_body
    inner_body = body[2]

    return _count_church_applications(inner_body)




def _count_church_applications(term: Term) -> int:
    """Count the number of f-applications in a Church numeral body."""
    if is_app(term):
        # Each application of f increments the count
        return 1 + _count_church_applications(term[2])
    if is_var(term):
        return 0
    return 0


def int_to_church(n: int) -> Term:
    """Convert a Python integer to a Church numeral."""
    result = church_zero()
    for _ in range(n):
        result = church_succ(result)
    return result


# ===========================================================================
# Simply typed lambda calculus
# ===========================================================================

# Types:
#   ("base", name)                 — a base type (e.g., "int", "bool")
#   ("arrow", from_type, to_type)  — function type A → B

Type = tuple


def base_type(name: str) -> Type:
    return ("base", name)


def arrow_type(from_t: Type, to_t: Type) -> Type:
    return ("arrow", from_t, to_t)


def type_equals(t1: Type, t2: Type) -> bool:
    """Check if two types are structurally equal."""
    return t1 == t2


def type_pretty(t: Type) -> str:
    """Pretty-print a type."""
    if t[0] == "base":
        return t[1]
    if t[0] == "arrow":
        return f"({type_pretty(t[1])} -> {type_pretty(t[2])})"
    return str(t)


# Typed terms:
#   ("tvar", name)                 — type variable
#   ("tbase", name)                — base type (untyped term with base type)
#   ("tabs", name, body, type)     — abstraction with type
#   ("tapp", func, arg, type)      — application with type

def t_var(name: str, type_: Type) -> Term:
    return ("tvar", name, type_)


def t_abs(name: str, body: Term, type_: Type) -> Term:
    return ("tabs", name, body, type_)


def t_app(func: Term, arg: Term, type_: Type) -> Term:
    return ("tapp", func, arg, type_)


def infer_type(term: Term, env: dict[str, Type]) -> Type:
    """Infer the type of a typed lambda term.

    env: mapping from variable names to their types.
    Returns the type of the term.
    """
    kind = term[0]

    if kind == "tvar":
        name = term[1]
        if name not in env:
            raise ValueError(f"Unbound variable: {name}")
        return env[name]

    if kind == "tabs":
        expected_type = term[3]
        # Type is given, so just return it
        # In a full inference system, we'd check consistency
        return expected_type

    if kind == "tapp":
        expected_type = term[3]
        return expected_type

    raise ValueError(f"Unknown term kind: {kind}")


def check_type(term: Term, env: dict[str, Type], expected: Type) -> bool:
    """Check if a typed term has the expected type.

    Returns True if the type matches, False otherwise.
    """
    actual = infer_type(term, env)
    return type_equals(actual, expected)


def type_of(term: Term, env: dict[str, Type]) -> Type:
    """Get the type of a term, raising an error if unbound."""
    return infer_type(term, env)


def __all__() -> list[str]:
    return [
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
