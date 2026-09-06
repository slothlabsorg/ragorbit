# El curso se mudó → `slothlabsorg/rag-course`

Este directorio contenía una copia del curso de RAG e IA agéntica. Ahora el curso
vive en su propio repositorio, bilingüe:

**👉 https://github.com/slothlabsorg/rag-course**

También se lee en el navegador, con los talleres ejecutables:
**https://slothlabs.org/rag-course**

## Por qué se movió

Había **tres** copias del mismo material (aquí, en `rag-course/` y en la web) y se
desincronizaban en silencio: un arreglo en una no llegaba a las otras. Ahora
`rag-course` es la única fuente de verdad y la web se sincroniza desde ahí.

## Qué relación tiene con este repo

El curso enseña, desde cero, todo lo que RAGorbit usa: cada tema se ancla a un nodo
del catálogo y a uno de los 10 templates de `examples/`. Los talleres leen los
`flow.json` de este repo, así que si vas a hacer el curso, ten los dos clonados al
lado:

```bash
git clone https://github.com/slothlabsorg/ragorbit
git clone https://github.com/slothlabsorg/rag-course
```

Este directorio está en `.gitignore`: si tienes la copia antigua en disco, se queda
donde está pero no se publica.
