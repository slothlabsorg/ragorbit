"""Codegen: Flow IR -> proyecto Python ejecutable (app/ + mocks/ + tests/).

- Compila el flujo resolviendo el tipo de cada puerto por arista (para el runtime).
- Copia el runtime mock (stdlib) dentro del artefacto para que los tests corran sin deps.
- Emite código "real" (LangChain/LangGraph) como texto + esqueleto por deployment target.
- Emite tests `unittest` que ejercitan el flujo en modo mock con asserts significativos.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import resources
from .codegen_nodes import emit_node, has_emitter
from .registry import Registry, load_registry

# Los datos del paquete se leen con importlib.resources para que el codegen
# funcione igual instalado en disco y dentro del zipapp `ragorbit.pyz`.
_RUNTIME_PARTS = ("runtime",)
_TEMPLATES_CHAT_PARTS = ("templates", "chat")


# --------------------------------------------------------------------------
# Compilación del flujo (resuelve tipos de puerto por arista)
# --------------------------------------------------------------------------
def compile_flow(flow: Dict[str, Any], reg: Optional[Registry] = None) -> Dict[str, Any]:
    reg = reg or load_registry()
    nodes_out: List[dict] = []
    for n in flow.get("nodes", []):
        m = reg.get(n["type"])
        behavior = (m.mock.get("behavior") if m and m.mock else None) or "passthrough_message"
        nodes_out.append({
            "id": n["id"],
            "type": n["type"],
            "label": n.get("label", n["id"]),
            "behavior": behavior,
            "config": n.get("config", {}),
            "inputs": (m.inputs() if m else []),
            "outputs": (m.outputs() if m else []),
        })
    edges_out: List[dict] = []
    for e in flow.get("edges", []):
        sm = reg.get(_type_of(flow, e["source"]))
        tm = reg.get(_type_of(flow, e["target"]))
        sp = sm.resolve_port("output", e["sourcePort"]) if sm else None
        tp = tm.resolve_port("input", e["targetPort"]) if tm else None
        edges_out.append({
            "source": e["source"],
            "sourcePort": e["sourcePort"],
            "sourceType": (sp or {}).get("type", e["sourcePort"]),
            "target": e["target"],
            "targetPort": e["targetPort"],
            "targetType": (tp or {}).get("type", e["targetPort"]),
            "loop": bool(e.get("loop")),
        })
    return {"flow": flow.get("flow", {}), "nodes": nodes_out, "edges": edges_out}


def _type_of(flow: Dict[str, Any], node_id: str) -> str:
    for n in flow.get("nodes", []):
        if n["id"] == node_id:
            return n["type"]
    return ""


# --------------------------------------------------------------------------
# Fixtures de muestra por nodo (para el modo mock)
# --------------------------------------------------------------------------
def generate_fixtures(flow: Dict[str, Any], reg: Optional[Registry] = None) -> Dict[str, Any]:
    reg = reg or load_registry()
    fx: Dict[str, Any] = {}
    for n in flow.get("nodes", []):
        cfg = n.get("config", {})
        t = n["type"]
        if t.startswith("loader.") or t == "io.batch":
            fx[n["id"]] = {"documents": [
                {"text": f"Documento de muestra {i+1} para {n.get('label', n['id'])}.",
                 "metadata": {"section": f"§{i+1}"}, "source": f"{n['id']}#sec{i+1}"}
                for i in range(3)]}
        elif t in ("tool.service", "tool.http", "tool.function", "tool.mcp"):
            fx[n["id"]] = {"result": _tool_result_for(n)}
        elif t == "logic.structured":
            fx[n["id"]] = {"decision": _decision_sample(cfg.get("schema", {}))}
        elif t == "logic.rules":
            fx[n["id"]] = {"decision": {"matched": True, "action": "auto-confirm"}}
        elif t == "io.event-source":
            fx[n["id"]] = {"events": [{"id": f"evt-{i+1}", "type": cfg.get("topic", "event"),
                                        "payload": {"priority": ["P1", "P2", "P3"][i % 3]}} for i in range(3)]}
        elif t == "io.stt":
            fx[n["id"]] = {"transcript": "El cliente pregunta por su caso."}
    return fx


def _tool_result_for(node: dict) -> Any:
    name = (node.get("config", {}).get("name") or node.get("label") or "").lower()
    if "pay" in name or "pago" in name or "pricing" in name or "tarif" in name:
        return {"ok": True, "amount": 130, "currency": "USD", "txn": "mock-txn-1"}
    if "inventory" in name or "alternativ" in name or "inventario" in name:
        return {"options": [{"id": "OPT-1"}, {"id": "OPT-2"}]}
    if "order" in name or "pedido" in name or "reservation" in name or "profile" in name:
        return {"id": "REC-1", "items": [{"sku": "A"}], "status": "ok"}
    return {"ok": True}


def _decision_sample(schema: dict) -> dict:
    props = (schema or {}).get("properties", {})
    out: Dict[str, Any] = {}
    for k, spec in props.items():
        spec = spec or {}
        if "default" in spec:
            out[k] = spec["default"]
        elif spec.get("type") in ("number", "integer"):
            out[k] = 72
        elif spec.get("type") == "boolean":
            out[k] = True
        elif spec.get("type") == "array":
            out[k] = []
        else:
            out[k] = "muestra"
    return out or {"decision": "aprobar", "score": 72}


# --------------------------------------------------------------------------
# Generación del proyecto
# --------------------------------------------------------------------------
def generate_project(flow: Dict[str, Any], out: Path, reg: Optional[Registry] = None) -> Path:
    reg = reg or load_registry()
    target = flow["flow"]["deploymentTarget"]
    if target == "chat-service":
        return _generate_chat_project(flow, out, reg)
    return _generate_default_project(flow, out, reg)


def _generate_default_project(flow: Dict[str, Any], out: Path, reg: Optional[Registry] = None) -> Path:
    reg = reg or load_registry()
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "app").mkdir(parents=True)
    (out / "tests").mkdir(parents=True)
    (out / "mocks").mkdir(parents=True)

    compiled = compile_flow(flow, reg)
    fixtures = generate_fixtures(flow, reg)
    fid = flow["flow"]["id"]
    target = flow["flow"]["deploymentTarget"]

    # datos para el runtime mock
    (out / "flow.compiled.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "flow.json").write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "mocks" / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")

    # runtime mock (stdlib) copiado dentro del artefacto
    rt = out / "runtime"
    rt.mkdir()
    for f in ("__init__.py", "executor.py", "behaviors.py"):
        rt.joinpath(f).write_text(resources.read_text(*_RUNTIME_PARTS, f), encoding="utf-8")

    # secretos
    secrets = [s["name"] for s in flow.get("secrets", [])]
    (out / ".env.template").write_text(
        "# Completa estos secretos para el modo real (MOCK=false). En modo mock no son necesarios.\n"
        + "MOCK=true\n"
        + "".join(f"{s}=\n" for s in secrets), encoding="utf-8")

    # app/
    nodes_code, real_requires, missing = _nodes_py(flow, compiled, reg)
    (out / "app" / "__init__.py").write_text("", encoding="utf-8")
    (out / "app" / "settings.py").write_text(_settings_py(), encoding="utf-8")
    (out / "app" / "nodes.py").write_text(nodes_code, encoding="utf-8")
    (out / "app" / "graph.py").write_text(_graph_py(flow, compiled, target), encoding="utf-8")
    (out / "app" / "mockrun.py").write_text(_mockrun_py(), encoding="utf-8")
    (out / "app" / "main.py").write_text(_main_py(target), encoding="utf-8")

    # tests/
    (out / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (out / "tests" / "test_flow.py").write_text(_test_py(flow, compiled), encoding="utf-8")

    # archivos de proyecto
    (out / "pyproject.toml").write_text(_pyproject(fid, target, real_requires), encoding="utf-8")
    (out / "Dockerfile").write_text(_dockerfile(target), encoding="utf-8")
    (out / "docker-compose.yml").write_text(_compose(fid, target), encoding="utf-8")
    (out / "README.md").write_text(_readme(flow, target, secrets, real_requires, missing), encoding="utf-8")
    return out


_DOCS_WALKTHROUGH = Path(__file__).resolve().parents[1] / "docs" / "07-airline-chat-walkthrough.md"


_RENDERED_SUFFIXES = (".py", ".html", ".yml", ".yaml", ".sh", ".md")


def _render_template(rel: str, subs: Dict[str, str]) -> str:
    text = resources.read_text(*_TEMPLATES_CHAT_PARTS, *rel.split("/"))
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _copy_template_tree(out: Path, subs: Dict[str, str]) -> None:
    for src in resources.iter_files(*_TEMPLATES_CHAT_PARTS):
        rel = resources.relative_name(src, *_TEMPLATES_CHAT_PARTS)
        if rel.split("/")[0] == "gcp":
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        name = rel.split("/")[-1]
        if name.endswith(_RENDERED_SUFFIXES) or name.startswith("Dockerfile"):
            dest.write_text(_render_template(rel, subs), encoding="utf-8")
        else:
            with src.open("rb") as fsrc, open(dest, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)


def _has_tool_services(flow: Dict[str, Any]) -> bool:
    return any(n["type"] == "tool.service" for n in flow.get("nodes", []))


def _service_map_from_flow(flow: Dict[str, Any]) -> List[tuple]:
    rules = [
        (("reservation", "pnr", "reserva"), "reservation", "lookup"),
        (("inventory", "inventario", "disponibil"), "inventory", "search"),
        (("pricing", "tarif", "precio"), "pricing", "quote"),
        (("payment", "pago", "cobro"), "payment", "charge"),
        (("policy", "rag", "fare"), "policy-rag", "search"),
    ]
    found: List[tuple] = []
    seen: set = set()
    for n in flow.get("nodes", []):
        if n["type"] != "tool.service":
            continue
        name = (str(n.get("label", "")) + " " + str(n.get("config", {}).get("name", "")) + " " + n["id"]).lower()
        for keys, service, op in rules:
            if any(k in name for k in keys) and service not in seen:
                found.append((keys, service, op))
                seen.add(service)
    return found if found else rules[:4]


def _generate_chat_project(flow: Dict[str, Any], out: Path, reg: Optional[Registry] = None) -> Path:
    reg = reg or load_registry()
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    for d in ("app", "tests", "mocks", "static", "gcp"):
        (out / d).mkdir(parents=True)

    compiled = compile_flow(flow, reg)
    fixtures = generate_fixtures(flow, reg)
    fid = flow["flow"]["id"]
    fname = flow["flow"].get("name", fid)
    secrets = [s["name"] for s in flow.get("secrets", [])]
    subs = {"FLOW_ID": fid, "FLOW_NAME": fname}
    integration = _has_tool_services(flow)

    (out / "flow.compiled.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "flow.json").write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "mocks" / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")

    rt = out / "runtime"
    rt.mkdir()
    for f in ("__init__.py", "executor.py", "behaviors.py"):
        rt.joinpath(f).write_text(resources.read_text(*_RUNTIME_PARTS, f), encoding="utf-8")

    _copy_template_tree(out, subs)
    (out / "app" / "integration.py").write_text(
        _render_template("app/integration.py", {**subs, "SERVICE_MAP_JSON": json.dumps(_service_map_from_flow(flow), ensure_ascii=False)}),
        encoding="utf-8",
    )
    # Nota: el target chat-service NO lleva app/graph.py. Su camino real es
    # app/engine.py + app/llm_agent.py (agente con tool-calling y guardrails), que
    # vienen de la plantilla. Generar además un StateGraph sin usar solo confundía:
    # parecía el punto de entrada de producción y no lo era.
    (out / "app" / "mockrun.py").write_text(_mockrun_py(), encoding="utf-8")
    (out / "app" / "__init__.py").write_text("", encoding="utf-8")
    (out / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (out / "tests" / "test_flow.py").write_text(_test_py(flow, compiled), encoding="utf-8")

    (out / "docker-compose.yml").write_text(_render_template("docker-compose.yml", subs), encoding="utf-8")
    (out / "Dockerfile").write_text(resources.read_text(*_TEMPLATES_CHAT_PARTS, "Dockerfile"), encoding="utf-8")
    if integration:
        (out / "docker-compose.integration.yml").write_text(
            _render_template("docker-compose.integration.yml", subs), encoding="utf-8"
        )
        (out / "Dockerfile.services").write_text(
            resources.read_text(*_TEMPLATES_CHAT_PARTS, "Dockerfile.services"), encoding="utf-8"
        )

    for gcp_file in ("gcp/deploy.sh", "gcp/cloudbuild.yaml"):
        (out / gcp_file).write_text(_render_template(gcp_file, subs), encoding="utf-8")
    (out / "gcp" / "deploy.sh").chmod(0o755)

    env_lines = [
        "# MOCK=true → motor en proceso (tests rápidos)",
        "# USE_LLM=true + ANTHROPIC_API_KEY → Claude real",
        "# INTEGRATION=true → tools vía HTTP (docker / Cloud Run)",
        "MOCK=true\nINTEGRATION=false\nUSE_LLM=false\n",
        f"FLOW_ID={fid}\nSERVICES_BASE=http://127.0.0.1:8900\nPORT=8000\n",
        "# Solo si pasas por un gateway propio; vacío = api.anthropic.com\n",
        "ANTHROPIC_BASE_URL=\n",
        "LLM_MODEL=claude-sonnet-4-6\n",
        "SSL_VERIFY=true\n",
        "ANTHROPIC_API_KEY=\n\n",
    ] + [f"{s}=\n" for s in secrets if s != "ANTHROPIC_API_KEY"]
    (out / ".env.template").write_text("".join(env_lines), encoding="utf-8")
    (out / "pyproject.toml").write_text(_pyproject_chat(fid), encoding="utf-8")
    (out / "README.md").write_text(_readme_chat(flow, secrets, integration), encoding="utf-8")
    if _DOCS_WALKTHROUGH.is_file():
        shutil.copy(_DOCS_WALKTHROUGH, out / "WALKTHROUGH.md")
    return out


# --------------------------------------------------------------------------
# Plantillas de archivos (texto)
# --------------------------------------------------------------------------
def _settings_py() -> str:
    return (
        "import os\n\n"
        "MOCK = os.environ.get('MOCK', 'true').lower() in ('1', 'true', 'yes')\n"
        "LLM_MODEL = os.environ.get('LLM_MODEL', 'anthropic:claude-opus-4-8')\n"
    )


def _mockrun_py() -> str:
    return (
        "\"\"\"Ejecuta el flujo en modo mock (stdlib, sin deps).\"\"\"\n"
        "import json\n"
        "from pathlib import Path\n"
        "from runtime.executor import run_flow\n\n"
        "_ROOT = Path(__file__).resolve().parent.parent\n\n"
        "def load():\n"
        "    compiled = json.loads((_ROOT / 'flow.compiled.json').read_text(encoding='utf-8'))\n"
        "    fixtures = json.loads((_ROOT / 'mocks' / 'fixtures.json').read_text(encoding='utf-8'))\n"
        "    return compiled, fixtures\n\n"
        "def run(seed_message='Hola', seed_events=None):\n"
        "    compiled, fixtures = load()\n"
        "    return run_flow(compiled, fixtures, seed_message=seed_message, seed_events=seed_events)\n\n"
        "if __name__ == '__main__':\n"
        "    import sys\n"
        "    msg = sys.argv[1] if len(sys.argv) > 1 else 'Hola'\n"
        "    res = run(msg)\n"
        "    print(json.dumps({'response': res['response'], 'escalations': res['escalations'],\n"
        "                      'audit': len(res['audit'])}, ensure_ascii=False, indent=2))\n"
    )


def _main_py(target: str) -> str:
    if target == "chat-service":
        return (
            "\"\"\"Punto de entrada. En MOCK=true usa el runtime mock; en real, LangGraph (app/graph.py).\n"
            "Para servir HTTP real: instala fastapi y descomenta. Ver README.\"\"\"\n"
            "from app.settings import MOCK\n"
            "from app.mockrun import run\n\n"
            "def handle(message: str):\n"
            "    if MOCK:\n"
            "        return run(message)['response']\n"
            "    from app.graph import build_graph  # requiere langgraph/langchain\n"
            "    return build_graph().invoke({'message': message})\n\n"
            "if __name__ == '__main__':\n"
            "    print(handle('Hola, ¿me ayudas?'))\n"
        )
    if target == "event-worker":
        return (
            "\"\"\"Worker event-driven. MOCK=true procesa eventos de fixtures.\"\"\"\n"
            "from app.settings import MOCK\n"
            "from app.mockrun import run\n\n"
            "def handle_batch(events=None):\n"
            "    if MOCK:\n"
            "        return run(seed_events=events)['outputs']\n"
            "    from app.graph import build_graph\n"
            "    return build_graph().invoke({'events': events or []})\n\n"
            "if __name__ == '__main__':\n"
            "    print(handle_batch())\n"
        )
    return (
        "\"\"\"Job batch. MOCK=true corre sobre fixtures.\"\"\"\n"
        "from app.settings import MOCK\n"
        "from app.mockrun import run\n\n"
        "def main():\n"
        "    if MOCK:\n"
        "        return run()['response']\n"
        "    from app.graph import build_graph\n"
        "    return build_graph().invoke({})\n\n"
        "if __name__ == '__main__':\n"
        "    print(main())\n"
    )


def _ident(node_id: str) -> str:
    return re.sub(r"\W", "_", str(node_id))


def _nodes_py(flow: Dict[str, Any], compiled: Dict[str, Any], reg: Registry) -> tuple:
    """Emite app/nodes.py: la implementación REAL de cada nodo.

    Devuelve (código, paquetes_pip_requeridos). Cada función recibe `inputs`
    agrupado por tipo de puerto y devuelve `{tipo_de_puerto: valor}` — la misma
    firma que los comportamientos mock de `runtime/behaviors.py`, para poder
    leerlos en paralelo.
    """
    imports: set = set()
    helpers: List[tuple] = []
    helper_names: set = set()
    requires: set = set()
    fns: List[str] = []
    missing: List[str] = []

    for n in compiled["nodes"]:
        m = reg.get(n["type"])
        emitter = (m.emitter if m else None) or n["type"]
        code = emit_node({**n, "config": n.get("config", {})}, emitter)
        if not has_emitter(emitter):
            missing.append(f"{n['id']} ({n['type']})")
        imports.update(code.imports)
        requires.update(code.requires)
        for name, block in code.helpers:
            if name not in helper_names:
                helper_names.add(name)
                helpers.append((name, block))
        fns.append(f"def node_{_ident(n['id'])}(inputs, state):\n{code.body}\n")

    out: List[str] = []
    out.append('"""Implementación REAL de cada nodo del flujo (LangChain/LangGraph).')
    out.append("")
    out.append(f'Generado por RAGorbit desde el flow «{flow["flow"]["id"]}».')
    out.append("")
    out.append("Cada función recibe `inputs` (las entradas agrupadas por tipo de puerto) y")
    out.append("devuelve `{tipo_de_puerto: valor}` — la MISMA firma que el comportamiento mock")
    out.append("equivalente en `runtime/behaviors.py`. Puedes leer los dos en paralelo: el mock")
    out.append("es lo que corre con MOCK=true, esto es lo que corre en producción.")
    out.append("")
    out.append("Es código tuyo: edítalo. RAGorbit no lo vuelve a leer.")
    out.append('"""')
    out.append("from __future__ import annotations")
    out.append("")
    # stdlib primero, luego terceros — como los ordenaría isort.
    imports.add("import logging")
    stdlib_mods = {"asyncio", "fnmatch", "json", "logging", "os", "re", "pathlib",
                   "datetime", "urllib", "urllib.request", "typing"}

    def _module_of(line: str) -> str:
        parts = line.split()
        return parts[1].split(".")[0] if len(parts) > 1 else ""

    plain = sorted(i for i in imports if i.startswith("import "))
    froms = sorted(i for i in imports if i.startswith("from "))
    for group in (
        [i for i in plain if _module_of(i) in stdlib_mods],
        [i for i in froms if _module_of(i) in stdlib_mods],
    ):
        out.extend(group)
    third = [i for i in plain if _module_of(i) not in stdlib_mods] + \
            [i for i in froms if _module_of(i) not in stdlib_mods]
    if third:
        out.append("")
        out.extend(third)
    out.append("")
    out.append("logger = logging.getLogger(__name__)")
    out.append("")
    for _name, block in helpers:
        out.append("")
        out.append(block.strip("\n"))
    out.append("")
    out.append("")
    out.append("# " + "-" * 74)
    out.append("# Un nodo del flujo = una función")
    out.append("# " + "-" * 74)
    out.append("")
    out.append("\n\n".join(fns).rstrip("\n"))
    return "\n".join(out).rstrip("\n") + "\n", sorted(requires), missing


def _graph_py(flow: Dict[str, Any], compiled: Dict[str, Any], target: str) -> str:
    """Emite app/graph.py: el StateGraph que cablea los nodos de app/nodes.py."""
    nodes = compiled["nodes"]
    edges = [e for e in compiled["edges"] if not e["loop"]]
    ids = [n["id"] for n in nodes]
    has_target = {e["target"] for e in edges}
    has_source = {e["source"] for e in edges}
    roots = [i for i in ids if i not in has_target]
    leaves = [i for i in ids if i not in has_source]

    # Aristas serializadas para reconstruir las entradas por tipo de puerto,
    # igual que runtime/executor._gather_inputs.
    wiring = [
        {"source": e["source"], "sourceType": e["sourceType"],
         "target": e["target"], "targetType": e["targetType"]}
        for e in edges
    ]

    lines: List[str] = []
    lines.append('"""Grafo real con LangGraph — cablea los nodos de app/nodes.py.')
    lines.append("")
    lines.append(f'Generado por RAGorbit desde el flow «{flow["flow"]["id"]}». Target: {target}.')
    lines.append("")
    lines.append("El estado lleva `outputs[node_id][port_type]`, así que las entradas de cada")
    lines.append("nodo se reúnen por ARISTA y por TIPO DE PUERTO — la misma semántica que el")
    lines.append("ejecutor mock (`runtime/executor.py`). Por eso un flujo se comporta igual en")
    lines.append("mock y en real, y dos nodos pueden alimentar el mismo puerto sin pisarse.")
    lines.append("")
    lines.append("Con MOCK=true este archivo NO se usa (ver app/mockrun.py).")
    lines.append('"""')
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from typing import Annotated, Any, Dict, List, TypedDict")
    lines.append("")
    lines.append("from langgraph.graph import END, START, StateGraph")
    lines.append("")
    lines.append("from app import nodes as N")
    lines.append("")
    lines.append("")
    lines.append("# Cableado del flujo: (origen, tipo_salida) -> (destino, tipo_entrada)")
    lines.append("EDGES: List[Dict[str, str]] = [")
    for w in wiring:
        lines.append(f"    {w!r},")
    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("def _merge_outputs(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:")
    lines.append('    """Reducer del estado: acumula la salida de cada nodo.')
    lines.append("")
    lines.append("    Hace falta porque LangGraph ejecuta en paralelo las ramas independientes")
    lines.append("    (p. ej. dos loaders), y sin reducer las escrituras concurrentes a `outputs`")
    lines.append("    serían un conflicto.")
    lines.append('    """')
    lines.append("    return {**(left or {}), **(right or {})}")
    lines.append("")
    lines.append("")
    lines.append("class FlowState(TypedDict, total=False):")
    lines.append("    outputs: Annotated[Dict[str, Dict[str, Any]], _merge_outputs]")
    lines.append("    seed_message: str")
    lines.append("    seed_events: List[dict]")
    lines.append("    filters: Dict[str, Any]")
    lines.append("    flow_id: str")
    lines.append("")
    lines.append("")
    lines.append("def _gather(state: FlowState, node_id: str) -> Dict[str, List[Any]]:")
    lines.append('    """Entradas del nodo agrupadas por tipo de puerto (idéntico al mock)."""')
    lines.append("    outputs = state.get('outputs') or {}")
    lines.append("    inputs: Dict[str, List[Any]] = {}")
    lines.append("    for edge in EDGES:")
    lines.append("        if edge['target'] != node_id:")
    lines.append("            continue")
    lines.append("        produced = outputs.get(edge['source']) or {}")
    lines.append("        value = produced.get(edge['sourceType'])")
    lines.append("        if value is None and produced:")
    lines.append("            # El tipo exacto no está: toma la primera salida disponible.")
    lines.append("            value = next(iter(produced.values()))")
    lines.append("        inputs.setdefault(edge['targetType'], []).append(value)")
    lines.append("    return inputs")
    lines.append("")
    lines.append("")
    lines.append("def _step(node_id: str, fn):")
    lines.append('    """Envuelve la función del nodo como paso del grafo."""')
    lines.append("")
    lines.append("    def run(state: FlowState) -> Dict[str, Any]:")
    lines.append("        produced = fn(_gather(state, node_id), state) or {}")
    lines.append("        return {'outputs': {node_id: produced}}")
    lines.append("")
    lines.append("    run.__name__ = f'step_{node_id}'")
    lines.append("    return run")
    lines.append("")
    lines.append("")
    lines.append("def build_graph():")
    lines.append('    """Compila el StateGraph del flujo."""')
    lines.append("    g = StateGraph(FlowState)")
    lines.append("")
    for n in nodes:
        lines.append(f"    g.add_node({n['id']!r}, _step({n['id']!r}, N.node_{_ident(n['id'])}))  # {n['type']}")
    lines.append("")
    for r in roots:
        lines.append(f"    g.add_edge(START, {r!r})")
    for e in edges:
        lines.append(f"    g.add_edge({e['source']!r}, {e['target']!r})")
    for l in leaves:
        lines.append(f"    g.add_edge({l!r}, END)")
    lines.append("")
    lines.append("    return g.compile()")
    lines.append("")
    lines.append("")
    lines.append("_OUTPUT_NODES = " + repr([n["id"] for n in nodes if n["type"] in ("io.output", "io.panel", "io.notify")]))
    lines.append("")
    lines.append("")
    lines.append("def run(seed_message: str = '', seed_events: List[dict] | None = None,")
    lines.append("        filters: Dict[str, Any] | None = None) -> Dict[str, Any]:")
    lines.append('    """Ejecuta el flujo en modo REAL y devuelve outputs + la respuesta principal."""')
    lines.append("    final = build_graph().invoke({")
    lines.append("        'outputs': {},")
    lines.append("        'seed_message': seed_message,")
    lines.append("        'seed_events': seed_events or [],")
    lines.append("        'filters': filters or {},")
    lines.append(f"        'flow_id': {flow['flow']['id']!r},")
    lines.append("    })")
    lines.append("    outputs = final.get('outputs') or {}")
    lines.append("    return {'outputs': outputs, 'response': _primary_response(outputs)}")
    lines.append("")
    lines.append("")
    lines.append("def _primary_response(outputs: Dict[str, Dict[str, Any]]) -> Any:")
    lines.append('    """La salida a mostrar: los nodos de salida primero, luego el último valor."""')
    lines.append("    for node_id in reversed(_OUTPUT_NODES):")
    lines.append("        produced = outputs.get(node_id) or {}")
    lines.append("        for key in ('Message', 'Decision', 'Any'):")
    lines.append("            if produced.get(key) is not None:")
    lines.append("                return produced[key]")
    lines.append("    for produced in reversed(list(outputs.values())):")
    lines.append("        for key in ('Message', 'Decision', 'Any'):")
    lines.append("            if produced.get(key) is not None:")
    lines.append("                return produced[key]")
    lines.append("    return None")
    lines.append("")
    return "\n".join(lines)


def _test_py(flow: Dict[str, Any], compiled: Dict[str, Any]) -> str:
    types = sorted({n["type"] for n in compiled["nodes"]})
    target = flow["flow"]["deploymentTarget"]
    return f'''"""Tests e2e en modo mock (stdlib `unittest`, sin red ni LLM real).

Generado por RAGorbit para el flow «{flow["flow"]["id"]}».
Ejecuta:  python -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path

from runtime.executor import run_flow

_ROOT = Path(__file__).resolve().parent.parent
NODE_TYPES = {json.dumps(types, ensure_ascii=False)}
TARGET = {json.dumps(target)}


def _run(seed_message="Hola, ¿me ayudas con mi caso?"):
    compiled = json.loads((_ROOT / "flow.compiled.json").read_text(encoding="utf-8"))
    fixtures = json.loads((_ROOT / "mocks" / "fixtures.json").read_text(encoding="utf-8"))
    return run_flow(compiled, fixtures, seed_message=seed_message)


class TestFlowMock(unittest.TestCase):
    def test_runs_and_produces_output(self):
        res = _run()
        self.assertIsNotNone(res["response"], "El flujo debe producir una respuesta en modo mock.")

    def test_citations_when_required(self):
        res = _run()
        needs_cit = ("logic.citations" in NODE_TYPES) or ("logic.structured" in NODE_TYPES)
        if needs_cit:
            self.assertTrue(len(res["citations"]) > 0, "Debe haber citas cuando el flujo las exige.")

    def test_idempotency_guardrail(self):
        if "guardrail.idempotency" in NODE_TYPES:
            calls = res_calls(_run())
            self.assertTrue(any("idempotency" in c.get("wrappers", []) for c in calls),
                            "El tool transaccional debe estar envuelto en idempotencia.")
            for c in calls:
                self.assertLessEqual(c.get("executions", 1), 1, "Idempotencia: sin ejecuciones duplicadas.")

    def test_confirm_guardrail(self):
        if "guardrail.confirm" in NODE_TYPES:
            agent = _run()["trace"].get("agent", {{}})
            self.assertTrue(agent.get("needs_confirm") is not None,
                            "El confirm-gate debe evaluarse.")

    def test_hitl_escalation(self):
        if "hitl.escalate" in NODE_TYPES:
            res = _run("Atención: procedimiento WARNING crítico, requiere revisión.")
            self.assertTrue(len(res["escalations"]) > 0, "Debe escalar a humano en casos críticos.")

    def test_structured_decision(self):
        if "logic.structured" in NODE_TYPES:
            res = _run()
            decisions = [o.get("Decision") for o in res["outputs"].values() if o.get("Decision")]
            self.assertTrue(decisions, "logic.structured debe producir una Decision.")
            self.assertIsInstance(decisions[0], dict)

    def test_event_worker_fanout(self):
        if TARGET == "event-worker" and "agent.fanout" in NODE_TYPES:
            res = _run()
            self.assertGreaterEqual(res["trace"].get("fanout", {{}}).get("processed", 0), 1,
                                    "El fan-out debe procesar al menos un evento.")


def res_calls(res):
    return res["trace"].get("agent", {{}}).get("tool_calls", [])


if __name__ == "__main__":
    unittest.main()
'''


_PKG_PINS = {
    "langchain": '"langchain>=0.3"',
    "langchain-core": '"langchain-core>=0.3"',
    "langchain-anthropic": '"langchain-anthropic>=0.2"',
    "langchain-openai": '"langchain-openai>=0.2"',
    "langchain-huggingface": '"langchain-huggingface>=0.1"',
    "langchain-postgres": '"langchain-postgres>=0.0.12"',
    "langgraph": '"langgraph>=0.2"',
    "sentence-transformers": '"sentence-transformers>=3"',
    "psycopg[binary]": '"psycopg[binary]>=3.1"',
    "kafka-python": '"kafka-python>=2"',
    "pypdf": '"pypdf>=4"',
    "boto3": '"boto3>=1.34"',
    "unstructured[pdf]": '"unstructured[pdf]>=0.15"',
    "unstructured[all-docs]": '"unstructured[all-docs]>=0.15"',
    "opentelemetry-sdk": '"opentelemetry-sdk>=1.25"',
    "opentelemetry-exporter-otlp": '"opentelemetry-exporter-otlp>=1.25"',
}


def _real_deps(requires: Optional[List[str]] = None) -> List[str]:
    """Dependencias del modo real: las que los nodos de ESTE flujo necesitan.

    Se derivan de los emisores que participaron, así que un flujo que no usa
    pgvector no arrastra psycopg, y uno sin multimodal no pide unstructured.
    """
    base = ["langgraph", "langchain", "langchain-anthropic"]
    for pkg in requires or []:
        if pkg not in base:
            base.append(pkg)
    return [_PKG_PINS.get(p, f'"{p}"') for p in base]


def _pyproject(fid: str, target: str, requires: Optional[List[str]] = None) -> str:
    chat_extra = '\nchat = ["fastapi>=0.110", "uvicorn>=0.27"]' if target == "chat-service" else ""
    deps = "\n".join(f"  {d}," for d in _real_deps(requires))
    return f'''[project]
name = "{fid}"
version = "0.1.0"
description = "Artefacto RAGorbit ({target}). Modo mock sin deps; modo real con LangChain/LangGraph."
requires-python = ">=3.10"

[project.optional-dependencies]
# Modo real (producción). Instala con: pip install -e ".[real]"
# Derivadas de los nodos de este flujo — no es una lista genérica.
real = [
{deps}
]{chat_extra}

[tool.ragorbit]
deploymentTarget = "{target}"
'''


def _pyproject_chat(fid: str) -> str:
    return f'''[project]
name = "{fid}"
version = "0.1.0"
description = "Chat generado por RAGorbit. Mock, integración HTTP y LangGraph real."
requires-python = ">=3.10"

[project.optional-dependencies]
server = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "kafka-python>=2.0",
]
real = [
  "langgraph>=0.2",
  "langchain>=0.3",
  "langchain-anthropic>=0.2",
]

[tool.ragorbit]
deploymentTarget = "chat-service"
'''


def _readme_chat(flow: Dict[str, Any], secrets: List[str], integration: bool) -> str:
    fid = flow["flow"]["id"]
    name = flow["flow"].get("name", fid)
    docker_block = """
## Docker realista (servicios HTTP + Kafka)

```bash
docker compose -f docker-compose.integration.yml up --build
# abre http://localhost:8000
```

El bot llama **servicios HTTP reales** (mock) con contratos, idempotencia y audit a Kafka.
""" if integration else """
## Docker (modo mock)

```bash
docker compose up --build
# abre http://localhost:8000
```
"""
    gcp_block = """
## Google Cloud Run

```bash
export GCP_PROJECT_ID=tu-proyecto
export GCP_REGION=us-central1
bash gcp/deploy.sh
```
""" if integration else ""
    return f'''# {name}

Artefacto **chat-service** generado por RAGorbit (`{fid}`).

Guía paso a paso (tipo video): **[WALKTHROUGH.md](./WALKTHROUGH.md)**

## 1. Probar sin instalar nada (mock en proceso)

```bash
python -m unittest discover -s tests
python -m app.mockrun "Quiero cambiar mi vuelo SCL-BOG del 15 al 17"
```

## 2. Servidor local con UI

```bash
pip install -e ".[server]"
python -m app.main
# http://localhost:8000
```

## 3. API HTTP

```bash
curl -X POST http://localhost:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Hola", "session_id": "s1"}}'
```
{docker_block}{gcp_block}
## Producción real (LLM + LangGraph)

1. Completa `app/graph.py` con la lógica LangChain/LangGraph por nodo.
2. `pip install -e ".[real]"` · `export MOCK=false` · `export INTEGRATION=false`
3. Configura secretos en `.env` (ver `.env.template`).

## Estructura

| Archivo | Rol |
|---------|-----|
| `app/main.py` | FastAPI + UI web |
| `app/engine.py` | Conmuta mock / integración / real |
| `app/integration.py` | Tools vía HTTP |
| `app/graph.py` | LangGraph (completar para prod) |
| `runtime/` | Motor mock (stdlib) |
| `mocks/services/` | Servicios HTTP mock |
| `gcp/` | Despliegue Cloud Run |

Generado por RAGorbit
'''


def _dockerfile(target: str) -> str:
    return (
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY . /app\n"
        "ENV MOCK=true\n"
        "# Modo real: pip install -e \".[real]\" y MOCK=false\n"
        "CMD [\"python\", \"-m\", \"app.main\"]\n"
    )


def _compose(fid: str, target: str) -> str:
    return (
        "services:\n"
        f"  {fid}:\n"
        "    build: .\n"
        "    environment:\n"
        "      - MOCK=true\n"
        + ("    ports:\n      - \"8000:8000\"\n" if target == "chat-service" else "")
    )


def _readme(flow: Dict[str, Any], target: str, secrets: List[str],
            requires: Optional[List[str]] = None, missing: Optional[List[str]] = None) -> str:
    fid = flow["flow"]["id"]
    run_real = {
        "chat-service": "uvicorn app.main:app --port 8000",
        "event-worker": "python -m app.main        # consume del broker y procesa el lote",
    }.get(target, "python -m app.main        # corre el job")
    pending = ""
    if missing:
        rows = "\n".join(f"- `{m}`" for m in missing)
        pending = f'''
> ⚠️ **Nodos sin implementación real generada** — funcionan en mock, pero en modo
> real lanzan `NotImplementedError` hasta que escribas su cuerpo en `app/nodes.py`:
>
{rows}
'''
    return f'''# {flow["flow"].get("name", fid)}

Artefacto generado por **RAGorbit** desde el flow `{fid}`. Target de despliegue: **{target}**.

Es un proyecto Python normal: corre **sin** RAGorbit y el código es tuyo para editar.
{pending}
## Correr en modo mock (sin instalar nada, sin red)

```bash
python -m unittest discover -s tests        # tests e2e contra mocks -> verde
python -m app.mockrun "Hola, ¿me ayudas?"    # ejecuta el flujo y muestra la respuesta
```

El modo mock usa `runtime/` (stdlib) + `mocks/fixtures.json`. No requiere LLM ni servicios reales.

## Pasar a modo real (producción)

```bash
pip install -e ".[real]"
export MOCK=false
{"".join(f"export {s}=...   # tu credencial\n" for s in secrets) or "# (este flujo no requiere secretos)"}
{run_real}
```

Las dependencias de `[real]` se derivan de los nodos de **este** flujo{f" ({', '.join(requires)})" if requires else ""},
no de una lista genérica.

## Estructura

- `app/nodes.py` — **implementación real de cada nodo**. Una función por nodo, con la
  misma firma que su equivalente mock en `runtime/behaviors.py`, para poder leer los
  dos en paralelo.
- `app/graph.py` — el StateGraph de LangGraph que cablea esos nodos. Las entradas se
  reúnen por arista y por tipo de puerto, igual que en el ejecutor mock.
- `app/mockrun.py` — runner en modo mock (stdlib).
- `runtime/` — ejecutor mock determinista (copiado del engine).
- `mocks/fixtures.json` — datos de muestra.
- `tests/test_flow.py` — tests e2e en modo mock.

Generado por RAGorbit · https://slothlabs.org/ragorbit
'''
