"""Exercise the public builder API in fresh processes, independent of suite imports."""
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PREAMBLE = '''
import sys, socket, importlib, json
sys.path.insert(0, sys.argv[1])
def no_network(*a, **k): raise AssertionError("network during builder import")
socket.socket.connect = no_network
socket.getaddrinfo = no_network
'''


def fresh(code):
    result = subprocess.run([sys.executable, "-I", "-c", PREAMBLE + code, str(ROOT)],
                            capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def test_direct_air_quality_import_does_not_load_other_hazards_or_credentials():
    result = fresh('''
from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
from src.two_bot import intern
assert intern.build_pm25_hazard_bundle is build_pm25_hazard_bundle
assert intern.build_pm25_hazard_bundle is intern.build_pm25_hazard_bundle
print(json.dumps([name for name in sys.modules if name.startswith("src.")]))
''')
    assert "src.data.air_quality" in result
    assert not set(result) & {"src.credentials", "src.data.firms", "src.data.nhc",
                              "src.data.gpm_imerg", "src.two_bot.intern.temperature",
                              "src.two_bot.intern.marine"}


def test_package_import_is_lazy_and_existing_public_import_styles_are_compatible():
    result = fresh('''
from src.two_bot import intern
assert not any(name.startswith("src.two_bot.intern.") for name in sys.modules)
assert len(intern.__all__) == 45
assert len(set(intern.__all__)) == 45
assert all(name in dir(intern) for name in intern.__all__)
try: intern.not_a_builder
except AttributeError: pass
else: raise AssertionError("unknown attribute accepted")
namespace = {}
exec("from src.two_bot.intern import *", namespace)
assert set(namespace) - {"__builtins__"} == set(intern.__all__)
for name in intern.__all__:
    value = getattr(intern, name)
    assert callable(value)
    assert value is namespace[name]
    assert value is getattr(importlib.import_module(value.__module__), name)
    assert value.__module__.startswith("src.two_bot.intern.")
from src.two_bot.intern import _c_to_f, build_fire_bundle, build_pm25_hazard_bundle
assert _c_to_f(0) == 32
assert build_fire_bundle is intern.build_fire_bundle
assert build_pm25_hazard_bundle is intern.build_pm25_hazard_bundle
print(json.dumps({"exports": len(intern.__all__), "unknown_rejected": True}))
''')
    assert result == {"exports": 45, "unknown_rejected": True}
