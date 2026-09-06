"""Runtime mock de RAGorbit (stdlib, sin dependencias).

Este paquete se ejecuta tal cual en el motor (engine) Y se copia dentro de cada
artefacto generado (como `runtime/`) para que sus tests corran en modo mock sin
red ni LLM real. Determinista por diseño.

API:
    from runtime.executor import run_flow
    result = run_flow(compiled_flow, fixtures, seed_message="...")
"""
