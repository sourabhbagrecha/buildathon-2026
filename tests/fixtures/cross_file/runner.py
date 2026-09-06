"""Cross-file dynamic dispatch fixture: names come from steps.yaml, resolution via getattr."""

import importlib


def run_steps(step_names, module_name="pipeline.transactions"):
    mod = importlib.import_module(module_name)
    return [getattr(mod, name) for name in step_names]
