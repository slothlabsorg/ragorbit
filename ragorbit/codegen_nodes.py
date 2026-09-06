"""Emisores de código real (LangChain/LangGraph) por tipo de nodo.

Cada manifest del catálogo declara un campo `emitter` (ver `registry.py`). Este
módulo es el registro de esos emisores: dado un nodo del Flow IR, devuelve el
código Python **real** de su función — el equivalente de producción del
comportamiento que `runtime/behaviors.py` implementa en modo mock.

La simetría es deliberada y es la promesa del producto: mock y real reciben lo
mismo (`inputs` agrupado por tipo de puerto) y devuelven lo mismo
(`{tipo_de_puerto: valor}`), así que se pueden leer en paralelo y el artefacto
generado se promueve de mock a real sin recablear el grafo.

Agregar una tecnología nueva = un manifest + un emisor aquí + un behavior mock.
No hay que tocar `codegen.py`.

Convenciones de los valores que viajan por los puertos (idénticas al mock, ver
la cabecera de `runtime/behaviors.py`), con los tipos reales entre paréntesis:

    Documents/Chunks : list[Document]          (langchain_core.documents)
    Retriever        : BaseRetriever
    Embeddings       : Embeddings
    Model            : BaseChatModel
    Tool             : BaseTool
    Message/Query    : str
    Decision         : dict
    Event            : list[dict]
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional


class NodeCode:
    """Código emitido para un nodo.

    - `body`: cuerpo de la función del nodo, ya indentado a 4 espacios.
    - `imports`: líneas de import que necesita (se deduplican y ordenan).
    - `helpers`: bloques a nivel de módulo, como pares (nombre, código). El
      nombre deduplica: dos nodos del mismo tipo comparten un solo helper.
    - `requires`: paquetes pip que hacen falta, para el README y el pyproject.
    """

    def __init__(self, body: str, imports: Optional[List[str]] = None,
                 helpers: Optional[List[tuple]] = None, requires: Optional[List[str]] = None):
        self.body = body.rstrip("\n")
        self.imports = list(imports or [])
        self.helpers = list(helpers or [])
        self.requires = list(requires or [])


def _cfg(node: dict, key: str, default=None):
    return (node.get("config") or {}).get(key, default)


def _lit(value) -> str:
    """Literal Python del valor de configuración (para incrustarlo en el código)."""
    return repr(value)


def _label(node: dict) -> str:
    return str(node.get("label") or node.get("id") or node.get("type"))


# --------------------------------------------------------------------------
# Helpers compartidos, emitidos una sola vez en app/nodes.py
# --------------------------------------------------------------------------
H_INPUTS = ("_inputs", '''
def _first(inputs, port_type, default=None):
    """Primer valor recibido en un puerto de entrada (o `default`)."""
    vals = inputs.get(port_type)
    return vals[0] if vals else default


def _all(inputs, port_type):
    """Todos los valores recibidos en un puerto (varias aristas al mismo puerto)."""
    return [v for v in inputs.get(port_type, []) if v is not None]
''')

H_FACTS = ("_fact", '''
def _fact(facts, path, default=None):
    """Lee `a.b.c` de un dict anidado. Usado por los motores de reglas."""
    cur = facts
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur
''')

H_DOCTEXT = ("_doc_text", '''
def _as_documents(value):
    """Normaliza a list[Document]: acepta Documents, un Document, o dicts."""
    if value is None:
        return []
    if isinstance(value, Document):
        return [value]
    out = []
    for item in (value if isinstance(value, list) else [value]):
        if isinstance(item, Document):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Document(
                page_content=item.get("text", item.get("page_content", "")),
                metadata=item.get("metadata", {}),
            ))
    return out
''')

H_HTTP = ("_http_json", '''
def _http_json(url, payload, *, method="POST", api_key_env=None, timeout=20):
    """POST/GET JSON con la stdlib — sin dependencias añadidas.

    El artefacto de chat usa el mismo enfoque (`app/llm_agent.py`), así que el
    proyecto generado no arrastra `requests`/`httpx` solo para llamar un servicio.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key_env:
        token = os.environ.get(api_key_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}
''')


# ==========================================================================
# Motor de reglas: traduce las expresiones del Flow IR a Python en codegen
# ==========================================================================
_RESERVED = {"True", "False", "None", "and", "or", "not", "in", "is"}
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_STRING_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def translate_condition(expr: str) -> str:
    """Traduce una condición del Flow IR a una expresión Python.

    El Flow IR usa una sintaxis tipo JS (`&&`, `||`, `true`, rutas con punto)
    porque es lo que un usuario del lienzo escribe. Se traduce **en tiempo de
    generación**, así que el artefacto no lleva ningún `eval` ni intérprete:

        "event.tier == 'premium' || event.connections_lost > 0"
        -> _fact(facts, "event.tier") == 'premium' or _fact(facts, "event.connections_lost") > 0
    """
    if not expr or not str(expr).strip():
        return "False"

    # 1) Aísla los literales de cadena para no tocar su contenido.
    literals: List[str] = []

    def _stash(m):
        literals.append(m.group(0))
        return f"\x00{len(literals) - 1}\x00"

    work = _STRING_RE.sub(_stash, str(expr))

    # 2) Operadores lógicos de JS -> Python.
    work = work.replace("&&", " and ").replace("||", " or ")
    #    `!=` debe sobrevivir; solo `!` suelto se vuelve `not`.
    work = re.sub(r"!(?!=)", " not ", work)

    # 3) Identificadores -> lectura de hechos. Los literales booleanos/nulos de
    #    JS se mapean a los de Python en lugar de tratarse como hechos.
    js_literals = {"true": "True", "false": "False", "null": "None", "undefined": "None"}

    def _ident(m):
        name = m.group(0)
        low = name.lower()
        if low in js_literals:
            return js_literals[low]
        if name in _RESERVED:
            return name
        return f'_fact(facts, "{name}")'

    work = _IDENT_RE.sub(_ident, work)

    # 4) Restaura los literales.
    def _pop(m):
        return literals[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", _pop, work).strip()


def _js_object_to_dict(raw: str) -> Optional[dict]:
    """Parsea `{ priority: 'P1', track: 'complex' }` (claves sin comillas, comillas simples)."""
    text = raw.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # Comillas dobles en las claves sin comillas, y comillas simples -> dobles.
    fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', text)
    fixed = re.sub(r"'([^']*)'", r'"\1"', fixed)
    try:
        parsed = json.loads(fixed)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _coerce_scalar(text: str):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def condition_facts(expr: str) -> List[str]:
    """Nombres de hechos que una condición necesita para poder evaluarse.

    Se usan para distinguir «la regla no coincidió» de «no se pudo evaluar por
    falta de datos» — que en una decisión auditable no son lo mismo.
    """
    if not expr:
        return []
    work = _STRING_RE.sub(" ", str(expr))
    js_literals = {"true", "false", "null", "undefined"}
    names: List[str] = []
    for match in _IDENT_RE.finditer(work):
        name = match.group(0)
        if name.lower() in js_literals or name in _RESERVED:
            continue
        if name not in names:
            names.append(name)
    return names


def translate_action(raw) -> dict:
    """Traduce el `then`/`else` de una regla al dict de decisión que produce.

    Acepta las tres formas que usan los templates:
      - JSON:        '{"elegible": false, "razon": "..."}'
      - objeto JS:   "{ priority: 'P1', track: 'complex' }"
      - asignación:  "decision = 'aprobar'"
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}

    obj = _js_object_to_dict(text)
    if obj is not None:
        return obj

    # Asignaciones separadas por `;` o `,`: "decision = 'x'; score = 1"
    if "=" in text and not text.startswith("{"):
        out: Dict[str, Any] = {}
        for part in re.split(r"[;,]", text):
            if "=" not in part:
                continue
            key, _, val = part.partition("=")
            key = key.strip()
            if key:
                out[key] = _coerce_scalar(val)
        if out:
            return out

    return {"action": text}


# ==========================================================================
# Emisores — io
# ==========================================================================
def _emit_io_batch(node: dict) -> NodeCode:
    source = _cfg(node, "source", "./data")
    glob_pat = _cfg(node, "glob", "**/*")
    if str(source).startswith("s3://"):
        body = f'''    """io.batch — enumera el lote desde S3 ({source}).

    Requiere `pip install boto3` y credenciales AWS en el entorno.
    """
    bucket, _, prefix = {_lit(str(source)[5:])}.partition("/")
    client = boto3.client("s3")
    docs = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not fnmatch.fnmatch(key, {_lit(glob_pat)}):
                continue
            payload = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                # Binario (PDF/imagen): lo enumeramos y que lo abra el loader.
                text = ""
            docs.append(Document(page_content=text, metadata={{"source": f"s3://{{bucket}}/{{key}}"}}))
    return {{"Documents": docs}}'''
        return NodeCode(body,
                        imports=["import fnmatch", "import boto3",
                                 "from langchain_core.documents import Document"],
                        requires=["boto3"])

    body = f'''    """io.batch — enumera el lote en {source} con el patrón {glob_pat}."""
    root = Path({_lit(source)})
    docs = []
    for path in sorted(root.glob({_lit(_normalize_glob(glob_pat))})):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Binario (PDF/imagen): se enumera aquí y lo abre el loader del flujo.
            text = ""
        docs.append(Document(page_content=text, metadata={{"source": str(path)}}))
    return {{"Documents": docs}}'''
    return NodeCode(body, imports=["from pathlib import Path",
                                   "from langchain_core.documents import Document"])


def _normalize_glob(pattern: str) -> str:
    """`pathlib.glob` no soporta llaves: `**/*.{pdf,csv}` -> `**/*`.

    Se enumera de más y el loader de cada tipo filtra por extensión, que es lo
    que hace igualmente el flujo.
    """
    return re.sub(r"\{[^}]*\}", "*", str(pattern))


def _emit_io_event_source(node: dict) -> NodeCode:
    broker = _cfg(node, "broker", "kafka")
    topic = _cfg(node, "topic", "events")
    exactly_once = bool(_cfg(node, "exactlyOnce", False))
    if broker != "kafka":
        body = f'''    """io.event-source — broker {broker}: sin cliente generado.

    RAGorbit solo emite consumidor real para Kafka. Para {broker}, conecta aquí
    tu cliente y devuelve una lista de dicts en el puerto Event.
    """
    events = state.get("seed_events") or []
    return {{"Event": list(events)}}'''
        return NodeCode(body)

    body = f'''    """io.event-source — consume {topic} de Kafka.

    `exactlyOnce={exactly_once}`: {"commit manual tras procesar, para no perder ni duplicar eventos." if exactly_once else "commit automático."}
    Si no hay KAFKA_BROKER en el entorno, usa `state['seed_events']` — así el
    mismo artefacto corre en local sin levantar Kafka.
    """
    broker = os.environ.get("KAFKA_BROKER")
    if not broker:
        return {{"Event": list(state.get("seed_events") or [])}}

    consumer = KafkaConsumer(
        {_lit(topic)},
        bootstrap_servers=broker,
        group_id=os.environ.get("KAFKA_GROUP_ID", {_lit(str(topic) + "-worker")}),
        enable_auto_commit={not exactly_once},
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=int(os.environ.get("KAFKA_POLL_MS", "5000")),
    )
    events = [msg.value for msg in consumer]
    {"consumer.commit()  # exactlyOnce: se confirma después de leer el lote" if exactly_once else ""}
    consumer.close()
    return {{"Event": events}}'''
    return NodeCode(body, imports=["import json", "import os", "from kafka import KafkaConsumer"],
                    requires=["kafka-python"])


def _emit_io_output(node: dict) -> NodeCode:
    fmt = _cfg(node, "format", "json")
    dumps = ('json.dumps(value, ensure_ascii=False, indent=2, default=str)'
             if fmt == "json" else 'str(value)')
    body = f'''    """io.output — salida final del flujo en formato {fmt}."""
    value = _first(inputs, "Any")
    if value is None:
        value = _first(inputs, "Decision") or _first(inputs, "Message")
    rendered = {dumps}
    print(rendered)
    return {{"Any": value, "Message": rendered}}'''
    imports = ["import json"] if fmt == "json" else []
    return NodeCode(body, imports=imports, helpers=[H_INPUTS])


def _emit_io_notify(node: dict) -> NodeCode:
    channels = _cfg(node, "channels", ["email"]) or ["email"]
    body = f'''    """io.notify — notifica por {", ".join(channels)}.

    Cada canal se entrega a un webhook configurado por entorno
    (`NOTIFY_EMAIL_WEBHOOK`, `NOTIFY_SMS_WEBHOOK`, …). Un webhook por canal
    mantiene el artefacto libre de SDKs de proveedor: apúntalo a tu servicio de
    mensajería, a n8n, o a una Lambda. Sin webhook, el canal se registra y se
    omite en lugar de romper el flujo.
    """
    payload = _first(inputs, "Any") or _first(inputs, "Decision") or _first(inputs, "Message")
    delivered = []
    for channel in {_lit(list(channels))}:
        endpoint = os.environ.get(f"NOTIFY_{{channel.upper()}}_WEBHOOK")
        if not endpoint:
            logger.warning("io.notify: canal %s sin NOTIFY_%s_WEBHOOK; se omite",
                           channel, channel.upper())
            continue
        try:
            _http_json(endpoint, {{"channel": channel, "payload": payload}})
            delivered.append(channel)
        except Exception as exc:
            logger.error("io.notify: fallo entregando por %s: %s", channel, exc)
    return {{"Any": {{"channels": delivered, "payload": payload}}}}'''
    return NodeCode(body,
                    imports=["import json", "import os", "import urllib.request"],
                    helpers=[H_INPUTS, H_HTTP])


# ==========================================================================
# Emisores — loaders
# ==========================================================================
def _emit_loader_pdf(node: dict) -> NodeCode:
    path = _cfg(node, "path", "./data")
    ocr = bool(_cfg(node, "ocr", False))
    if ocr:
        body = f'''    """loader.pdf — carga PDFs de {path} con OCR.

    `ocr: true` usa `UnstructuredPDFLoader` en modo hi_res, que necesita
    `pip install "unstructured[pdf]"` y tesseract instalado en el sistema.
    """
    root = Path({_lit(path)})
    paths = sorted(root.rglob("*.pdf")) if root.is_dir() else [root]
    docs = []
    for pdf in paths:
        docs.extend(UnstructuredPDFLoader(str(pdf), strategy="hi_res").load())
    return {{"Documents": docs}}'''
        return NodeCode(body,
                        imports=["from pathlib import Path",
                                 "from langchain_community.document_loaders import UnstructuredPDFLoader"],
                        requires=['unstructured[pdf]'])

    body = f'''    """loader.pdf — carga los PDFs de {path} (una página = un Document)."""
    root = Path({_lit(path)})
    paths = sorted(root.rglob("*.pdf")) if root.is_dir() else [root]
    docs = []
    for pdf in paths:
        docs.extend(PyPDFLoader(str(pdf)).load())
    return {{"Documents": docs}}'''
    return NodeCode(body,
                    imports=["from pathlib import Path",
                             "from langchain_community.document_loaders import PyPDFLoader"],
                    requires=["pypdf"])


def _emit_loader_tabular(node: dict) -> NodeCode:
    path = _cfg(node, "path", "./data")
    hint = _cfg(node, "schemaHint")
    tag = (f'\n        for doc in loaded:\n'
           f'            doc.metadata["schema_hint"] = {_lit(hint)}' if hint else "")
    body = f'''    """loader.tabular — carga los CSV de {path} (una fila = un Document).{"" if not hint else f" schemaHint={hint}."}"""
    root = Path({_lit(path)})
    paths = sorted(root.rglob("*.csv")) if root.is_dir() else [root]
    docs = []
    for csv_path in paths:
        loaded = CSVLoader(file_path=str(csv_path)).load(){tag}
        docs.extend(loaded)
    return {{"Documents": docs}}'''
    return NodeCode(body,
                    imports=["from pathlib import Path",
                             "from langchain_community.document_loaders import CSVLoader"])


def _emit_loader_multimodal(node: dict) -> NodeCode:
    extract_tables = bool(_cfg(node, "extractTables", False))
    describe_images = bool(_cfg(node, "describeImages", False))
    scheme = _cfg(node, "sectionScheme")
    path = _cfg(node, "path", "./data")
    scheme_tag = (f'\n        for doc in loaded:\n'
                  f'            doc.metadata["section_scheme"] = {_lit(scheme)}' if scheme else "")
    # Fuera de la f-string: anidar el mismo tipo de comillas dentro de `{...}`
    # solo es legal desde Python 3.12 (PEP 701), y el paquete soporta 3.10+.
    tables_note = "tablas (infer_table_structure) " if extract_tables else ""
    vision_note = ""
    if describe_images:
        vision_note = (
            "\n\n    describeImages está activo: el OCR de hi_res ya aporta el texto de las"
            "\n    imágenes. Para descripciones semánticas más ricas, pasa cada imagen por el"
            "\n    nodo model.vision del flujo y concaténalas aquí."
        )
    body = f'''    """loader.multimodal — PDFs e imágenes de {path}.

    `UnstructuredFileLoader` en modo elements con estrategia hi_res: extrae
    texto, {tables_note}y el OCR de las imágenes embebidas, cada
    elemento como su propio Document con su tipo en la metadata.
    Requiere `pip install "unstructured[all-docs]"` + tesseract y poppler.{vision_note}
    """
    root = Path({_lit(path)})
    patterns = ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.tiff")
    paths = sorted(p for pat in patterns for p in root.rglob(pat)) if root.is_dir() else [root]
    docs = []
    for item in paths:
        loaded = UnstructuredFileLoader(
            str(item),
            mode="elements",
            strategy="hi_res",
            infer_table_structure={extract_tables},
        ).load(){scheme_tag}
        docs.extend(loaded)
    return {{"Documents": docs}}'''
    return NodeCode(body,
                    imports=["from pathlib import Path",
                             "from langchain_community.document_loaders import UnstructuredFileLoader"],
                    requires=['unstructured[all-docs]'])


# ==========================================================================
# Emisores — ingest
# ==========================================================================
_SEPARATORS = {
    "by-section": ['\n# ', '\n## ', '\n### ', '\nSección ', '\nSECCIÓN ', '\n\n', '\n', ' '],
    "by-clause": ['\nCláusula ', '\nCLÁUSULA ', '\nArtículo ', '\nARTÍCULO ', '\n\n', '\n', ' '],
}


def _emit_ingest_chunker(node: dict) -> NodeCode:
    strategy = _cfg(node, "strategy", "recursive")
    size = int(_cfg(node, "chunkSize", 1000) or 1000)
    overlap = int(_cfg(node, "overlap", 150) or 150)
    seps = _SEPARATORS.get(strategy)
    sep_arg = f",\n        separators={_lit(seps)}" if seps else ""
    rationale = {
        "recursive": "Corta por párrafo y baja a frase/palabra solo si hace falta.",
        "by-section": "Prefiere los límites de sección, para que un chunk no cruce dos temas.",
        "by-clause": "Prefiere los límites de cláusula/artículo — clave en texto legal y pólizas.",
    }.get(strategy, "")
    body = f'''    """ingest.chunker — estrategia {strategy}, chunk {size} con solape {overlap}.

    {rationale}
    El solape mantiene contexto entre chunks contiguos, para que una frase
    partida por la mitad siga siendo recuperable desde ambos lados.
    """
    docs = _as_documents(_first(inputs, "Documents"))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size={size},
        chunk_overlap={overlap}{sep_arg},
    )
    return {{"Documents": splitter.split_documents(docs)}}'''
    return NodeCode(body,
                    imports=["from langchain_core.documents import Document",
                             "from langchain_text_splitters import RecursiveCharacterTextSplitter"],
                    helpers=[H_INPUTS, H_DOCTEXT])


def _emit_ingest_metadata(node: dict) -> NodeCode:
    fields = _cfg(node, "fields", []) or []
    body = f'''    """ingest.metadata — etiqueta {", ".join(fields) if fields else "los chunks"} para filtros duros.

    Los filtros duros del retriever solo sirven si la metadata está presente en
    cada chunk, así que se deriva de la ruta de origen: el tipo de documento del
    directorio o la extensión, y cualquier periodo/fecha del nombre. Lo que no se
    puede derivar queda ausente **a propósito** — un valor inventado haría que un
    filtro duro descarte silenciosamente el chunk correcto.
    """
    docs = _as_documents(_first(inputs, "Documents"))
    for doc in docs:
        source = str(doc.metadata.get("source", ""))
        for field in {_lit(list(fields))}:
            if doc.metadata.get(field):
                continue
            derived = _derive_metadata(field, source, doc)
            if derived is not None:
                doc.metadata[field] = derived
    return {{"Documents": docs}}'''
    helper = ("_derive_metadata", '''
_PERIOD_RE = re.compile(r"(20\\d{2})[-_/]?(?:Q([1-4])|(0[1-9]|1[0-2]))?")


def _derive_metadata(field, source, doc):
    """Deriva un valor de metadata de la ruta de origen. None = no derivable."""
    path = Path(source) if source else None
    low = field.lower()

    if "period" in low or "periodo" in low or "date" in low or "fecha" in low:
        match = _PERIOD_RE.search(source) or _PERIOD_RE.search(doc.page_content[:400])
        if match:
            year, quarter, month = match.group(1), match.group(2), match.group(3)
            if quarter:
                return f"{year}-Q{quarter}"
            return f"{year}-{month}" if month else year
        return None

    if "type" in low or "tipo" in low:
        if path and path.suffix:
            return path.suffix.lstrip(".").lower()
        return None

    # Convención: un directorio intermedio que se llame como el campo lleva el
    # valor en el segmento siguiente (…/policy_type/auto/póliza.pdf).
    if path:
        parts = [p.lower() for p in path.parts]
        if low in parts:
            idx = parts.index(low)
            if idx + 1 < len(parts):
                return path.parts[idx + 1]
    return None
''')
    return NodeCode(body,
                    imports=["import re", "from pathlib import Path",
                             "from langchain_core.documents import Document"],
                    helpers=[H_INPUTS, H_DOCTEXT, helper])


# ==========================================================================
# Emisores — model
# ==========================================================================
def _emit_model_llm(node: dict) -> NodeCode:
    model = _cfg(node, "model", "anthropic:claude-opus-4-8")
    temp = _cfg(node, "temperature", 0.2)
    key_ref = _cfg(node, "apiKeyRef", "ANTHROPIC_API_KEY")
    body = f'''    """model.llm — {model} (temperature={temp}).

    `init_chat_model` resuelve el proveedor desde el prefijo del identificador,
    así que cambiar de modelo es cambiar esta cadena — sin tocar el resto.
    Credencial: {key_ref}.
    """
    if not os.environ.get({_lit(key_ref)}):
        raise RuntimeError({_lit(f"Falta {key_ref} en el entorno (modo real). Con MOCK=true no se necesita.")})
    return {{"Model": init_chat_model({_lit(model)}, temperature={_lit(temp)})}}'''
    return NodeCode(body, imports=["import os", "from langchain.chat_models import init_chat_model"],
                    requires=["langchain", "langchain-anthropic"])


def _emit_model_vision(node: dict) -> NodeCode:
    model = _cfg(node, "model", "anthropic:claude-opus-4-8")
    key_ref = _cfg(node, "apiKeyRef", "ANTHROPIC_API_KEY")
    body = f'''    """model.vision — {model} para entrada de imagen.

    Es el mismo tipo de cliente que model.llm: los modelos multimodales aceptan
    bloques de imagen en el mensaje del usuario. Se marca como visión para que
    los nodos que envían imágenes tomen este modelo y no el de solo texto.
    """
    if not os.environ.get({_lit(key_ref)}):
        raise RuntimeError({_lit(f"Falta {key_ref} en el entorno (modo real).")})
    return {{"Model": init_chat_model({_lit(model)})}}'''
    return NodeCode(body, imports=["import os", "from langchain.chat_models import init_chat_model"],
                    requires=["langchain", "langchain-anthropic"])


def _emit_model_embedding(node: dict) -> NodeCode:
    model = _cfg(node, "model", "text-embedding-3-large")
    local = bool(_cfg(node, "local", False))
    key_ref = _cfg(node, "apiKeyRef", "OPENAI_API_KEY")
    if local:
        body = f'''    """model.embedding — {model} en local (sentence-transformers).

    En local no sale tráfico ni hay coste por token; a cambio, el modelo se
    descarga la primera vez y la calidad suele ser menor que la de un embedding
    alojado. Requiere `pip install langchain-huggingface sentence-transformers`.
    """
    return {{"Embeddings": HuggingFaceEmbeddings(model_name={_lit(model)})}}'''
        return NodeCode(body,
                        imports=["from langchain_huggingface import HuggingFaceEmbeddings"],
                        requires=["langchain-huggingface", "sentence-transformers"])

    body = f'''    """model.embedding — {model} vía API. Credencial: {key_ref}.

    El MISMO modelo debe usarse al indexar y al consultar: dos espacios
    vectoriales distintos no son comparables y el retrieval devolvería ruido.
    """
    if not os.environ.get({_lit(key_ref)}):
        raise RuntimeError({_lit(f"Falta {key_ref} en el entorno (modo real).")})
    return {{"Embeddings": OpenAIEmbeddings(model={_lit(model)})}}'''
    return NodeCode(body, imports=["import os", "from langchain_openai import OpenAIEmbeddings"],
                    requires=["langchain-openai"])


# ==========================================================================
# Emisores — store / retrieval
# ==========================================================================
def _emit_store_pgvector(node: dict) -> NodeCode:
    index = _cfg(node, "index", "documents")
    distance = _cfg(node, "distance", "cosine")
    body = f'''    """store.pgvector — colección «{index}» en Postgres, distancia {distance}.

    Indexa los Documents entrantes y devuelve un Retriever. pgvector vive en el
    Postgres que probablemente ya tienes: una base menos que operar, y los
    filtros por metadata son SQL, así que un filtro duro es realmente duro.
    Credencial: DATABASE_URL.
    """
    embeddings = _first(inputs, "Embeddings")
    if embeddings is None:
        raise RuntimeError("store.pgvector necesita un nodo model.embedding conectado.")
    connection = os.environ.get("DATABASE_URL")
    if not connection:
        raise RuntimeError("Falta DATABASE_URL en el entorno (modo real).")

    store = PGVector(
        embeddings=embeddings,
        collection_name={_lit(index)},
        connection=connection,
        distance_strategy={_lit(distance)},
        use_jsonb=True,
    )

    docs = []
    for value in _all(inputs, "Documents"):
        docs.extend(_as_documents(value))
    if docs:
        store.add_documents(docs)

    return {{"Retriever": store.as_retriever()}}'''
    return NodeCode(body,
                    imports=["import os", "from langchain_core.documents import Document",
                             "from langchain_postgres import PGVector"],
                    helpers=[H_INPUTS, H_DOCTEXT],
                    requires=["langchain-postgres", "psycopg[binary]"])


def _emit_retrieval_vector(node: dict) -> NodeCode:
    topk = int(_cfg(node, "topK", 4) or 4)
    hard = _cfg(node, "hardFilters", []) or []
    body = f'''    """retrieval.vector — top-{topk}{f", con filtros duros por {', '.join(hard)}" if hard else ""}.

    Los filtros duros se declaran en el flujo por NOMBRE de campo; el VALOR es
    del runtime y llega en `state["filters"]`. Se aplican como filtro del store
    (no como reordenamiento), así que un chunk que no cumple no puede colarse en
    el contexto — que es justo el punto en dominios regulados.
    """
    retriever = _first(inputs, "Retriever")
    if retriever is None:
        raise RuntimeError("retrieval.vector necesita un store conectado al puerto Retriever.")
    query = _first(inputs, "Query") or state.get("seed_message") or ""

    search_kwargs = {{"k": {topk}}}
    runtime_filters = state.get("filters") or {{}}
    hard_filters = {{
        field: runtime_filters[field]
        for field in {_lit(list(hard))}
        if field in runtime_filters
    }}
    if hard_filters:
        search_kwargs["filter"] = hard_filters

    chunks = retriever.vectorstore.as_retriever(search_kwargs=search_kwargs).invoke(query) \\
        if hasattr(retriever, "vectorstore") else retriever.invoke(query)
    return {{"Chunks": list(chunks)[:{topk}]}}'''
    return NodeCode(body, helpers=[H_INPUTS])


# ==========================================================================
# Emisores — logic
# ==========================================================================
def _emit_logic_structured(node: dict) -> NodeCode:
    schema = _cfg(node, "schema", {}) or {}
    require_cit = bool(_cfg(node, "requireCitations", False))
    cit_block = '''
    if not decision.get("citations"):
        decision["citations"] = [
            chunk.metadata.get("source", "desconocida") for chunk in chunks[:2]
        ]''' if require_cit else ""
    cit_instruction = ('\n        "Incluye en `citations` la fuente de cada chunk que sustente la decisión.\\n"'
                       if require_cit else "")
    body = f'''    """logic.structured — fuerza la salida del modelo a un esquema.

    `with_structured_output` usa el tool-calling del proveedor, así que el
    resultado ya viene validado contra el esquema: no hay que parsear JSON de
    texto libre ni defenderse de un modelo que decidió añadir prosa.{" Exige citas." if require_cit else ""}
    """
    model = _first(inputs, "Model")
    if model is None:
        raise RuntimeError("logic.structured necesita un nodo model.llm conectado.")
    chunks = list(_first(inputs, "Chunks") or [])
    context = _first(inputs, "Any") or _first(inputs, "Context")

    evidence = "\\n\\n".join(
        f"[{{chunk.metadata.get('source', 'desconocida')}}]\\n{{chunk.page_content}}"
        for chunk in chunks
    ) or "Sin contexto recuperado."

    prompt = (
        "Analiza la evidencia y responde EXCLUSIVAMENTE con los campos del esquema.\\n"
        "No inventes datos: si la evidencia no alcanza, dilo en los campos de texto.\\n"{cit_instruction}
        "\\nEVIDENCIA:\\n" + evidence
    )
    if context:
        prompt += f"\\n\\nCONTEXTO ADICIONAL:\\n{{context}}"

    decision = model.with_structured_output(SCHEMA_{_ident(node)}).invoke(prompt)
    if not isinstance(decision, dict):
        decision = dict(decision)
{cit_block}
    return {{"Decision": decision}}'''
    schema_block = (f"SCHEMA_{_ident(node)}", f'''
# Esquema de salida del nodo «{_label(node)}» (logic.structured), tal cual lo
# declara el Flow IR. `with_structured_output` acepta el JSON Schema directamente.
SCHEMA_{_ident(node)} = {json.dumps(schema, ensure_ascii=False, indent=4)}
''')
    return NodeCode(body, helpers=[H_INPUTS, schema_block])


def _emit_logic_rules(node: dict) -> NodeCode:
    rules = _cfg(node, "rules", []) or []
    else_action = _cfg(node, "else")
    lines: List[str] = []
    lines.append(f'''    """logic.rules — decisión determinista, {len(rules)} regla(s) en orden.

    Esta es la frontera del sistema donde el LLM **no** decide: las condiciones
    se tradujeron a Python en tiempo de generación (no hay `eval`) y la primera
    que coincide gana. Si un modelo propuso otra cosa, esto la sobrescribe — que
    es lo que hace auditable la decisión.
    """''')
    lines.append('    facts = _first(inputs, "Any") or _first(inputs, "Decision") or {}')
    lines.append('    if not isinstance(facts, dict):')
    lines.append('        facts = {"value": facts}')
    lines.append('    # Los eventos entran como hechos bajo `event.*`.')
    lines.append('    event = _first(inputs, "Event")')
    lines.append('    if isinstance(event, list) and event:')
    lines.append('        event = event[0]')
    lines.append('    if isinstance(event, dict):')
    lines.append('        facts = {**facts, "event": event, **event}')
    lines.append("")
    first = True
    all_facts: List[List[str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when", "")
        cond = translate_condition(when)
        needed = condition_facts(when)
        all_facts.append(needed)
        action = translate_action(rule.get("then"))
        keyword = "if" if first else "elif"
        first = False
        lines.append(f'    # {when}')
        guard = f'_ready(facts, {_lit(needed)}) and ' if needed else ''
        lines.append(f'    {keyword} {guard}{cond}:')
        lines.append(f'        decision = {_lit(action)}')
    if first:
        lines.append(f'    decision = {_lit(translate_action(else_action))}')
    else:
        lines.append('    else:')
        lines.append('        # Ninguna regla coincidió. Antes de aplicar el `else`, confirma que')
        lines.append('        # todas se pudieron evaluar: caer al `else` por falta de datos sería')
        lines.append('        # decidir sobre información ausente.')
        lines.append(f'        _assert_decidable(facts, {_lit(all_facts)}, {_lit(str(node["id"]))})')
        lines.append(f'        decision = {_lit(translate_action(else_action))}')
    lines.append("")
    lines.append('    return {"Decision": {**facts_summary(facts), **decision}}')
    helper = ("facts_summary", '''
def facts_summary(facts):
    """Conserva los hechos escalares junto a la decisión, para poder auditarla."""
    return {k: v for k, v in facts.items() if isinstance(v, (str, int, float, bool, type(None)))}


def _ready(facts, needed):
    """True si todos los hechos que la condición necesita están presentes.

    Sin esto, un hecho ausente haría `None >= 70` (TypeError) o, peor, dejaría
    pasar la regla al `else` como si simplemente no hubiera coincidido.
    """
    return all(_fact(facts, name) is not None for name in needed)


def _assert_decidable(facts, rule_facts, node_id):
    """Falla si alguna regla no se pudo evaluar por hechos ausentes."""
    unevaluable = sorted({
        name
        for needed in rule_facts
        for name in needed
        if _fact(facts, name) is None
    })
    if unevaluable:
        raise ValueError(
            f"logic.rules '{node_id}': no se puede decidir, faltan los hechos "
            f"{unevaluable}. Aplicar el `else` aquí sería decidir sobre datos "
            f"ausentes. Hechos recibidos: {sorted(facts)}"
        )
''')
    return NodeCode("\n".join(lines), helpers=[H_INPUTS, H_FACTS, helper])


def _emit_logic_router(node: dict) -> NodeCode:
    branches = _cfg(node, "branches", []) or []
    names = [b.get("name") for b in branches if isinstance(b, dict)]
    body = f'''    """logic.router — elige entre {", ".join(names) if names else "una rama"}.

    La rama elegida se anota en la decisión como `_branch`, y el flujo sigue por
    sus aristas normales. NO se generan aristas condicionales: el Flow IR no
    asocia una rama con una arista concreta, así que inventar la correspondencia
    podría enviar el trabajo por el camino equivocado. Para partir el grafo de
    verdad, pasa `{_route_name(node)}` a `add_conditional_edges` en app/graph.py
    con el mapa rama -> nodo que quieras.
    """
    decision = _first(inputs, "Decision") or _first(inputs, "Any") or {{}}
    if not isinstance(decision, dict):
        decision = {{"value": decision}}
    branch = {_route_name(node)}(decision)
    routed = {{**decision, "_branch": branch}}
    return {{"Any": routed, "Decision": routed}}'''
    route_lines = [f'\ndef {_route_name(node)}(decision):',
                   f'    """Rama a tomar tras «{_label(node)}» según la decisión recibida."""',
                   '    facts = {"decision": decision, **(decision if isinstance(decision, dict) else {})}']
    first = True
    for b in branches:
        if not isinstance(b, dict):
            continue
        cond = translate_condition(b.get("when", ""))
        kw = "if" if first else "elif"
        first = False
        route_lines.append(f'    # {b.get("when", "")}')
        route_lines.append(f'    {kw} {cond}:')
        route_lines.append(f'        return {_lit(b.get("name"))}')
    route_lines.append(f'    return {_lit(names[0] if names else "default")}')
    helper = (_route_name(node), "\n".join(route_lines) + "\n")
    return NodeCode(body, helpers=[H_INPUTS, H_FACTS, helper])


def _route_name(node: dict) -> str:
    return f"route_{_ident(node)}"


def _ident(node: dict) -> str:
    return re.sub(r"\W", "_", str(node["id"]))


# ==========================================================================
# Emisores — tools
# ==========================================================================
def _emit_tool_service(node: dict) -> NodeCode:
    name = _cfg(node, "name") or _label(node)
    base = _cfg(node, "baseUrl", "")
    op = _cfg(node, "operation", "invoke")
    in_schema = _cfg(node, "inputSchema", {}) or {}
    desc = _cfg(node, "description") or f"Llama a {name}.{op}"
    fn = f"call_{_ident(node)}"
    body = f'''    """tool.service — expone {name}.{op} como tool invocable por el agente.

    El esquema de entrada del Flow IR se pasa como `args_schema`, así que el
    modelo ve exactamente qué argumentos existen y de qué tipo — y una llamada
    mal formada falla en la validación antes de salir a la red.
    Credencial: SERVICE_API_KEY.
    """
    return {{"Tool": StructuredTool.from_function(
        func={fn},
        name={_lit(str(name))},
        description={_lit(str(desc))},
        args_schema=ARGS_{_ident(node)},
    )}}'''
    helper = (fn, f'''
ARGS_{_ident(node)} = {json.dumps(in_schema, ensure_ascii=False, indent=4)}


def {fn}(**kwargs):
    """{name}.{op} -> {base}/{op}"""
    url = {_lit(str(base).rstrip("/"))} + "/" + {_lit(str(op))}
    return _http_json(url, kwargs, api_key_env="SERVICE_API_KEY")
''')
    return NodeCode(body,
                    imports=["import json", "import os", "import urllib.request",
                             "from langchain_core.tools import StructuredTool"],
                    helpers=[H_HTTP, helper],
                    requires=["langchain-core"])


def _emit_tool_retriever(node: dict) -> NodeCode:
    name = _cfg(node, "name", "search")
    desc = _cfg(node, "description") or f"Busca en el índice para {name}."
    body = f'''    """tool.retriever — expone el retriever como tool «{name}».

    Un retriever envuelto en tool deja que el agente DECIDA cuándo buscar (y con
    qué consulta), en lugar de recuperar siempre antes de razonar. La descripción
    es lo único que el modelo lee para elegirla, así que dice cuándo usarla.
    """
    retriever = _first(inputs, "Retriever")
    if retriever is None:
        chunks = list(_first(inputs, "Chunks") or [])
        if not chunks:
            raise RuntimeError("tool.retriever necesita un Retriever o Chunks conectados.")
        # Sin store conectado: un retriever mínimo sobre los chunks recibidos.
        retriever = InMemoryVectorStore.from_documents(chunks, _first(inputs, "Embeddings")).as_retriever()
    return {{"Tool": create_retriever_tool(
        retriever,
        {_lit(str(name))},
        {_lit(str(desc))},
    )}}'''
    return NodeCode(body,
                    imports=["from langchain.tools.retriever import create_retriever_tool",
                             "from langchain_core.vectorstores import InMemoryVectorStore"],
                    helpers=[H_INPUTS],
                    requires=["langchain"])


# ==========================================================================
# Emisores — agentes
# ==========================================================================
def _emit_agent_fanout(node: dict) -> NodeCode:
    concurrency = int(_cfg(node, "concurrency", 16) or 16)
    system = _cfg(node, "subAgentSystem") or "Procesa el evento con las tools disponibles."
    body = f'''    """agent.fanout — un sub-agente por evento, hasta {concurrency} en paralelo.

    Stateless a propósito: cada evento se procesa de forma independiente, así que
    el worker escala horizontalmente y un evento que falla no arrastra al lote.
    El semáforo acota la concurrencia para no saturar ni el proveedor del modelo
    ni los servicios que las tools llaman.
    """
    events = _first(inputs, "Event") or state.get("seed_events") or []
    if isinstance(events, dict):
        events = [events]
    tools = _all(inputs, "Tool")
    model = _first(inputs, "Model")
    if model is None:
        model = init_chat_model(os.environ.get("LLM_MODEL", "anthropic:claude-opus-4-8"))

    agent = create_react_agent(model, tools, prompt=SUBAGENT_SYSTEM_{_ident(node)})

    async def _run_all():
        semaphore = asyncio.Semaphore({concurrency})

        async def _one(event):
            async with semaphore:
                try:
                    result = await agent.ainvoke(
                        {{"messages": [("user", json.dumps(event, ensure_ascii=False, default=str))]}}
                    )
                    return {{
                        "event": event.get("id", "evt"),
                        "status": "procesado",
                        "response": result["messages"][-1].content,
                    }}
                except Exception as exc:
                    # Un evento que falla se reporta y no tumba el lote.
                    return {{"event": event.get("id", "evt"), "status": "error",
                             "error": f"{{type(exc).__name__}}: {{exc}}"}}

        return await asyncio.gather(*(_one(event) for event in events))

    results = asyncio.run(_run_all())
    return {{"Any": results}}'''
    helper = (f"SUBAGENT_SYSTEM_{_ident(node)}", f'''
SUBAGENT_SYSTEM_{_ident(node)} = {_lit(str(system))}
''')
    return NodeCode(body,
                    imports=["import asyncio", "import json", "import os",
                             "from langchain.chat_models import init_chat_model",
                             "from langgraph.prebuilt import create_react_agent"],
                    helpers=[H_INPUTS, helper],
                    requires=["langgraph"])


# ==========================================================================
# Emisores — observability
# ==========================================================================
def _emit_observability_audit(node: dict) -> NodeCode:
    sink = _cfg(node, "sink", "log")
    topic = _cfg(node, "topic", "audit")
    if sink == "kafka":
        body = f'''    """observability.audit — publica el rastro en Kafka ({topic}).

    El rastro va a un topic, no a un log de la instancia: sobrevive al reinicio
    del pod y es consumible por quien audite. Sin KAFKA_BROKER cae a log
    estructurado en lugar de perder el evento en silencio.
    """
    payload = _first(inputs, "Any") or _first(inputs, "Decision") or _first(inputs, "Message")
    event = {{
        "node": {_lit(node["id"])},
        "flow": state.get("flow_id"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }}
    producer = _audit_producer()
    if producer is not None:
        producer.send({_lit(topic)}, event)
        producer.flush()
    else:
        logger.info("[audit] %s", json.dumps(event, ensure_ascii=False, default=str))
    return {{"Any": payload}}'''
        helper = ("_audit_producer", '''
_PRODUCER = None


def _audit_producer():
    """Productor Kafka perezoso y reutilizado. None si no hay broker configurado."""
    global _PRODUCER
    if _PRODUCER is not None:
        return _PRODUCER
    broker = os.environ.get("KAFKA_BROKER")
    if not broker:
        return None
    try:
        from kafka import KafkaProducer

        _PRODUCER = KafkaProducer(
            bootstrap_servers=broker,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False, default=str).encode("utf-8"),
        )
        return _PRODUCER
    except Exception as exc:
        logger.warning("[audit] Kafka no disponible (%s); se registra en log.", exc)
        return None
''')
        return NodeCode(body,
                        imports=["import json", "import os",
                                 "from datetime import datetime, timezone"],
                        helpers=[H_INPUTS, helper],
                        requires=["kafka-python"])

    body = f'''    """observability.audit — rastro a log estructurado (sink={sink})."""
    payload = _first(inputs, "Any") or _first(inputs, "Decision") or _first(inputs, "Message")
    logger.info("[audit] %s", json.dumps(
        {{"node": {_lit(node["id"])}, "ts": datetime.now(timezone.utc).isoformat(), "payload": payload}},
        ensure_ascii=False, default=str,
    ))
    return {{"Any": payload}}'''
    return NodeCode(body, imports=["import json", "from datetime import datetime, timezone"],
                    helpers=[H_INPUTS])


def _emit_observability_metrics(node: dict) -> NodeCode:
    exporter = _cfg(node, "exporter", "otlp")
    body = f'''    """observability.metrics — cuenta ejecuciones vía {exporter} (OpenTelemetry).

    OTLP es el protocolo estándar, así que estas métricas llegan a Prometheus,
    Datadog, Grafana o el colector que uses sin cambiar el código — solo
    `OTEL_EXPORTER_OTLP_ENDPOINT`.
    """
    payload = _first(inputs, "Any") or _first(inputs, "Message")
    _flow_counter().add(1, {{"node": {_lit(node["id"])}, "flow": str(state.get("flow_id"))}})
    return {{"Any": payload}}'''
    helper = ("_flow_counter", '''
_COUNTER = None


def _flow_counter():
    """Contador OTel perezoso; si el SDK no está instalado, no-op."""
    global _COUNTER
    if _COUNTER is not None:
        return _COUNTER
    try:
        from opentelemetry import metrics

        _COUNTER = metrics.get_meter("ragorbit.flow").create_counter(
            "flow_node_executions", description="Ejecuciones por nodo del flujo",
        )
    except Exception:
        class _NoOp:
            def add(self, *_args, **_kwargs):
                pass

        _COUNTER = _NoOp()
    return _COUNTER
''')
    return NodeCode(body, helpers=[H_INPUTS, helper],
                    requires=["opentelemetry-sdk", "opentelemetry-exporter-otlp"])


# ==========================================================================
# Registro de emisores (clave = campo `emitter` del manifest)
# ==========================================================================
EMITTERS: Dict[str, Callable[[dict], NodeCode]] = {
    "io.batch": _emit_io_batch,
    "io.event-source": _emit_io_event_source,
    "io.output": _emit_io_output,
    "io.notify": _emit_io_notify,
    "loader.pdf": _emit_loader_pdf,
    "loader.tabular": _emit_loader_tabular,
    "loader.multimodal": _emit_loader_multimodal,
    "ingest.chunker": _emit_ingest_chunker,
    "ingest.metadata": _emit_ingest_metadata,
    "model.llm": _emit_model_llm,
    "model.vision": _emit_model_vision,
    "model.embedding": _emit_model_embedding,
    "store.pgvector": _emit_store_pgvector,
    "retrieval.vector": _emit_retrieval_vector,
    "logic.structured": _emit_logic_structured,
    "logic.rules": _emit_logic_rules,
    "logic.router": _emit_logic_router,
    "tool.service": _emit_tool_service,
    "tool.retriever": _emit_tool_retriever,
    "agent.fanout": _emit_agent_fanout,
    "observability.audit": _emit_observability_audit,
    "observability.metrics": _emit_observability_metrics,
}


def has_emitter(emitter: str) -> bool:
    return emitter in EMITTERS


def emit_node(node: dict, emitter: Optional[str] = None) -> NodeCode:
    """Código real del nodo. Si su tipo aún no tiene emisor, devuelve un stub
    explícito — nunca un `return state` silencioso que parezca implementado."""
    key = emitter or node.get("type", "")
    fn = EMITTERS.get(key)
    if fn is None:
        return _emit_stub(node, key)
    return fn(node)


def _emit_stub(node: dict, key: str) -> NodeCode:
    """Stub para un tipo de nodo sin emisor todavía.

    Falla en voz alta en modo real en lugar de devolver el estado sin tocar: un
    paso silencioso es peor que un error, porque el flujo parece funcionar
    mientras produce basura.
    """
    ports = node.get("outputs") or []
    port = (ports[0].get("type") if ports and isinstance(ports[0], dict) else None) or "Any"
    body = f'''    """{key} — sin emisor de código real todavía.

    Este tipo de nodo funciona en modo mock (ver runtime/behaviors.py) pero aún
    no tiene implementación de producción generada. Escribe la tuya aquí y
    devuelve {{"{port}": <valor>}}.
    """
    raise NotImplementedError(
        {_lit(f"El nodo '{node.get('id')}' ({key}) no tiene implementación real generada. "
              f"Impleméntalo en app/nodes.py o corre con MOCK=true.")}
    )'''
    return NodeCode(body)
