import ast


BLOCKED_MODULES = {"os", "subprocess", "ctypes", "importlib", "shutil"}
BLOCKED_CALLS = {"eval", "exec", "__import__"}


def validate_skill_code(code: str, parameters: dict) -> list[str]:
    """Validate skill code for safety and correctness.

    Returns a list of error strings. An empty list means the code is valid.
    """
    errors = []

    # Check 1: Syntax
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]

    # Check 4: Blocked imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # alias.name may be "os.path" — block if the root module is blocked
                root = alias.name.split(".")[0]
                if root in BLOCKED_MODULES:
                    errors.append(f"Blocked import: '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in BLOCKED_MODULES:
                errors.append(f"Blocked import: 'from {module} import ...'")

    # Check 5: Blocked calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_CALLS:
                errors.append(f"Blocked call: '{func.id}'")

    # Check 2: run() function exists
    run_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run"
    ]

    if not run_nodes:
        errors.append("Code must define a function named 'run'")
        return errors

    # Check 3: Parameter match
    run_node = run_nodes[0]
    args = run_node.args

    # Collect all positional/keyword argument names (exclude *args and **kwargs)
    arg_names = [arg.arg for arg in args.args]
    # Also include keyword-only args
    arg_names += [arg.arg for arg in args.kwonlyargs]

    expected_params = set(parameters.keys())
    actual_args = set(arg_names)

    if actual_args != expected_params:
        missing = expected_params - actual_args
        extra = actual_args - expected_params
        parts = []
        if missing:
            parts.append(f"missing args: {sorted(missing)}")
        if extra:
            parts.append(f"unexpected args: {sorted(extra)}")
        errors.append(f"run() arguments do not match parameters — {', '.join(parts)}")

    return errors
