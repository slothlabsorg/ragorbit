# 05 · Extender el catálogo (agregar una tecnología nueva)

> La promesa de escalabilidad: **agregar un bloque nuevo = un manifest + un emisor + un behavior mock. Cero cambios en el core.** El registro lo descubre y aparece en la paleta.

Las tres piezas son deliberadamente pequeñas y viven en tres sitios fijos:

| Pieza | Dónde | Para qué |
|---|---|---|
| **Manifest** | `ragorbit/catalog/nodes/<categoría>.json` | Qué es: puertos, `configSchema`, secretos |
| **Emisor** | `ragorbit/codegen_nodes.py` → `EMITTERS` | El código **real** que se genera (producción) |
| **Behavior mock** | `ragorbit/runtime/behaviors.py` → `BEHAVIORS` | Qué hace **sin red ni LLM** (demo y tests) |

El manifest las une: su campo `emitter` nombra al emisor y su `mock.behavior` al
comportamiento mock.

> **Nota sobre plantillas.** El engine es **stdlib puro, cero dependencias** — no
> hay Jinja2. Un emisor es una función Python que devuelve el código del nodo como
> texto. Es menos elegante que una plantilla, pero mantiene la promesa de que
> RAGorbit corre en cualquier Python 3.10+ sin instalar nada.

---

## Paso 1 · Escribe el manifest

Añade una entrada al array JSON de tu categoría (p. ej. `catalog/nodes/store.json`):

```json
{
  "type": "store.weaviate",
  "category": "store",
  "title": "Weaviate Store",
  "description": "Vector store Weaviate con filtros por metadata.",
  "ports": {
    "inputs": [
      { "name": "Documents",  "type": "Documents" },
      { "name": "Embeddings", "type": "Embeddings", "required": true }
    ],
    "outputs": [
      { "name": "Retriever", "type": "Retriever" }
    ]
  },
  "configSchema": {
    "type": "object",
    "required": ["className"],
    "properties": {
      "className": { "type": "string", "title": "Clase/colección" },
      "distance":  { "type": "string", "enum": ["cosine", "dot", "l2"], "default": "cosine" }
    }
  },
  "secrets": ["WEAVIATE_URL", "WEAVIATE_API_KEY"],
  "emitter": "store.weaviate",
  "mock": { "behavior": "build_store" }
}
```

**Reglas:**
- `type` único, con la forma `<categoría>.<nombre>`.
- Los `port.type` deben salir de la [tabla de tipos](./01-concepts.md#42-tipos-de-dato-del-grafo-port-types) (o ser `Any`) para que las conexiones validen.
- El `configSchema` es JSON Schema estándar → la UI genera el formulario, las validaciones y la ayuda en contexto sin más trabajo.
- `emitter` suele ser igual a `type`; se separa para que dos nodos puedan compartir un emisor.
- `mock.behavior` puede reusar un behavior que ya exista (aquí, `build_store`): si tu tecnología se comporta como una que ya está, no dupliques el mock.

## Paso 2 · Escribe el emisor (código real)

Un emisor recibe el nodo y devuelve un `NodeCode` con el cuerpo de su función, sus
imports y los paquetes pip que necesita. En `ragorbit/codegen_nodes.py`:

```python
def _emit_store_weaviate(node: dict) -> NodeCode:
    class_name = _cfg(node, "className", "Documents")
    distance = _cfg(node, "distance", "cosine")
    body = f'''    """store.weaviate — colección «{class_name}», distancia {distance}."""
    embeddings = _first(inputs, "Embeddings")
    if embeddings is None:
        raise RuntimeError("store.weaviate necesita un nodo model.embedding conectado.")
    client = weaviate.connect_to_wcs(
        cluster_url=os.environ["WEAVIATE_URL"],
        auth_credentials=os.environ["WEAVIATE_API_KEY"],
    )
    store = WeaviateVectorStore(client, index_name={class_name!r}, embedding=embeddings)

    docs = []
    for value in _all(inputs, "Documents"):
        docs.extend(_as_documents(value))
    if docs:
        store.add_documents(docs)

    return {{"Retriever": store.as_retriever()}}'''
    return NodeCode(
        body,
        imports=["import os", "import weaviate",
                 "from langchain_weaviate import WeaviateVectorStore"],
        helpers=[H_INPUTS, H_DOCTEXT],
        requires=["weaviate-client", "langchain-weaviate"],
    )
```

Y regístralo:

```python
EMITTERS = {
    ...
    "store.weaviate": _emit_store_weaviate,
}
```

**El contrato del emisor** — tres reglas y ya:

1. **Firma fija.** La función generada recibe `inputs` (entradas agrupadas por
   tipo de puerto) y `state`, y devuelve `{tipo_de_puerto: valor}`. Es la misma
   firma que el behavior mock, a propósito.
2. **Respeta los tipos de puerto.** Lo que devuelvas en `"Retriever"` tiene que ser
   usable por quien consuma un `Retriever`. Los tipos concretos están en la
   cabecera de `codegen_nodes.py`.
3. **Falla en voz alta.** Si falta una entrada obligatoria o un secreto, lanza con
   un mensaje que diga qué conectar o qué exportar. Un nodo que devuelve el estado
   sin tocar es peor que un error: el flujo parece funcionar y produce basura.

`helpers` son bloques a nivel de módulo deduplicados por nombre — reusa los que ya
existen (`H_INPUTS`, `H_DOCTEXT`, `H_HTTP`, `H_FACTS`) en lugar de reimplementarlos.
`requires` alimenta el extra `[real]` del `pyproject.toml` generado, así que el
artefacto solo pide las deps que su flujo usa de verdad.

## Paso 3 · Escribe el behavior mock

En `ragorbit/runtime/behaviors.py`, con la misma firma y **determinista** (sin red,
sin reloj, sin aleatoriedad):

```python
def build_store_weaviate(node, inputs, ctx):
    docs = []
    for value in _all(inputs, "Documents"):
        if isinstance(value, list):
            docs.extend(value)
    if not docs:
        docs = _sample_docs(node, ctx)
    return {"Retriever": {"kind": "retriever", "chunks": docs, "node": node["id"]}}


BEHAVIORS = {
    ...
    "build_store_weaviate": build_store_weaviate,
}
```

Si tu tecnología se comporta igual que una existente, apunta `mock.behavior` a la
que ya está y sáltate este paso.

## Paso 4 · Listo — el registro lo descubre

`load_registry()` escanea `catalog/nodes/*.json` al arrancar. Tu nodo:

- aparece en la **paleta** bajo su `category`,
- genera su **formulario** desde el `configSchema`,
- valida sus **conexiones** por los tipos de puerto,
- participa en **codegen** (tu emisor) y en **mocks/tests** (tu behavior).

No tocaste el lienzo, ni `codegen.py`, ni el backend.

## Verifícalo

```bash
python3 -m ragorbit list-nodes | grep weaviate     # ¿aparece en el catálogo?
python3 tools/verify.py                            # los 10 casos siguen verdes
```

`tools/verify.py` audita también el **código real** generado: compila cada
`app/nodes.py` y falla si algún nodo quedó vacío, como un `return state`, o
lanzando `NotImplementedError`. Si tu emisor no está registrado, el generador emite
un stub explícito y el CI lo marca — no se cuela en silencio.

Para probar el nodo de punta a punta, mete un flujo mínimo que lo use en
`examples/` y `verify.py` lo recoge solo.

## Buenas prácticas

- **Siempre** un behavior mock: sin él, el bloque rompe el "éxito al primer intento".
- Usa tipos de puerto existentes antes de inventar uno; un tipo nuevo solo conecta consigo mismo o con `Any`.
- Pon `title`/`description` por campo: son la ayuda en contexto que ve el usuario.
- Marca como `required` solo lo imprescindible; al resto, un `default` sensato.
- En el docstring del código emitido explica **por qué** se elige esa tecnología y cuándo no — el artefacto es también material de lectura para quien lo hereda.

➡️ Siguiente: [06 · Principios de UX](./06-ux-principles.md).
