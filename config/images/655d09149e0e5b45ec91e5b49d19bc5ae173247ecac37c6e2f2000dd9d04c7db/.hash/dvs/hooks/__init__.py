import pkgutil
import importlib


for _, module_name, _ in pkgutil.iter_modules(__path__):
    # print(f"{__name__}.{module_name}")
    importlib.import_module(f"{__name__}.{module_name}")

    # print(hooks.engine.cmd_hook("ls", 0))
