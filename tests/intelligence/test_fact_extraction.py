from docsentry.intelligence.code_analysis.fact_extractor import facts_from_entities
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.models.code import FactType

SHA = "a" * 40


def test_function_and_parameter_facts() -> None:
    src = """
def calculate_delay_ms(base_timeout_seconds: int = 30) -> int:
    return base_timeout_seconds * 1000
"""
    parsed = parse_python("pkg/calc.py", src, SHA)
    facts = facts_from_entities(parsed.entities)
    fact_types = [f.fact_type for f in facts]
    assert FactType.FUNCTION_SIGNATURE in fact_types
    assert FactType.PARAMETER_DEFAULT in fact_types
    assert FactType.PARAMETER_TYPE in fact_types
    assert FactType.RETURN_TYPE in fact_types

    sig = next(f for f in facts if f.fact_type == FactType.FUNCTION_SIGNATURE)
    assert sig.unit_hint == "ms"

    param_def = next(f for f in facts if f.fact_type == FactType.PARAMETER_DEFAULT)
    assert param_def.property == "base_timeout_seconds"
    assert param_def.value == 30
    assert param_def.unit_hint == "s"

    param_type = next(f for f in facts if f.fact_type == FactType.PARAMETER_TYPE)
    assert param_type.value == "int"

    ret_type = next(f for f in facts if f.fact_type == FactType.RETURN_TYPE)
    assert ret_type.value == "int"


def test_constant_facts() -> None:
    src = """
MAX_BUFFER_SIZE_BYTES = 1024
TIMEOUT_MINUTES = 15
"""
    parsed = parse_python("pkg/consts.py", src, SHA)
    facts = facts_from_entities(parsed.entities)
    c_facts = [f for f in facts if f.fact_type == FactType.CONSTANT_VALUE]
    assert len(c_facts) == 2
    timeout_fact = next(f for f in c_facts if f.entity_name == "TIMEOUT_MINUTES")
    assert timeout_fact.value == 15
    assert timeout_fact.unit_hint == "min"


def test_config_default_facts() -> None:
    src = """
import os
from dataclasses import dataclass

PORT = os.getenv("PORT", "8080")

@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 8080

class AppSettings:
    debug: bool = True
"""
    parsed = parse_python("pkg/config.py", src, SHA)
    facts = facts_from_entities(parsed.entities)
    cfg_facts = [f for f in facts if f.fact_type == FactType.CONFIG_DEFAULT]
    cfg_names = [f.entity_name for f in cfg_facts]
    assert "PORT" in cfg_names
    port_fact = next(f for f in cfg_facts if f.entity_name == "PORT")
    assert port_fact.value == "8080"
    assert port_fact.details.get("numeric") == 8080

    # DataClass fields
    assert "host" in cfg_names
    assert "port" in cfg_names
    # AppSettings fields (ends with Settings)
    assert "debug" in cfg_names


def test_class_structure_facts() -> None:
    src = """
class MyService(BaseService, Interface):
    pass
"""
    parsed = parse_python("pkg/svc.py", src, SHA)
    facts = facts_from_entities(parsed.entities)
    cls_fact = next(f for f in facts if f.fact_type == FactType.CLASS_STRUCTURE)
    assert cls_fact.entity_name == "MyService"
    assert cls_fact.value == ["BaseService", "Interface"]
