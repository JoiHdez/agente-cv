# Agente de CV de Joel Hernández Contreras

Agente conversacional que responde preguntas sobre la trayectoria profesional de Joel: experiencia, proyectos, habilidades e IA. Expone un endpoint público compatible con **[Open Responses](https://www.openresponses.org/specification)** (`POST /v1/responses`, con y sin streaming) y la misma base de conocimiento por **MCP**.

## Arquitectura

```
Cliente (plataforma del reto, curl, cualquier SDK de Responses)
   │  POST /v1/responses  (Bearer API key · límite por minuto · validación de tamaño)
   ▼
app/main.py ── traduce Open Responses ⇄ mensajes (app/openresponses.py), historial por previous_response_id
   ▼
app/guardrails.py ── filtro de salida: teléfono, RFC, CURP, CLABE, tarjetas y correos nunca salen (también en streaming)
   ▼
app/agente.py ── bucle con herramientas, streaming de texto, máximo de pasos, traza JSON por paso
   │     system = reglas + resumen del CV (siempre en contexto, en caché)
   ▼
LLM ── decide cuándo llamar a buscar_en_cv ──▶ app/conocimiento.py ── BM25 sobre data/perfil/*.md
                                                     ▲
app/mcp_server.py ── expone buscar_en_cv y resumen_cv a cualquier cliente MCP (solo lectura)
```

## Decisiones

| Decisión | Alternativas descartadas | Por qué |
|---|---|---|
| **Resumen siempre en contexto + detalle bajo demanda con una herramienta** | Meter todo el CV en el prompt; RAG puro | El resumen (~1,000 tokens) responde la mayoría de preguntas sin buscar. El detalle por empresa o proyecto se recupera solo cuando hace falta: menos tokens por pregunta, el detalle exacto de cada empresa o proyecto y la base puede crecer sin inflar el prompt. |
| **Búsqueda BM25 con raíces simples** | Embeddings + base vectorial | Determinista, sin dependencias ni costo, explicable. Con 6 secciones alcanza un hit@3 de 92%. El caso que falla ("costo de usar LLMs") es justo el que resuelve la búsqueda semántica: es el siguiente paso. |
| **Bucle de agente propio** | Frameworks (LangGraph) o el tool runner del SDK | Control total y auditable: límite de pasos, validación de los argumentos de la herramienta, traza por paso y pruebas con un cliente falso. |
| **Streaming real** | Generar todo y luego "simular" el streaming | El texto llega a la plataforma mientras el modelo escribe (`response.output_text.delta`), con los eventos de ciclo de vida que pide el spec. |
| **Reglas antes que las instrucciones del cliente** | Pasar `instructions` como system prompt | Las indicaciones del cliente se agregan después de las reglas y no pueden anularlas; lo que escribe el usuario o devuelve la herramienta se trata como datos (defensa contra prompt injection). |
| **Privacidad por diseño** | Confiar en que el modelo "no diga" datos | La base de conocimiento solo contiene información pública; el teléfono, sueldo y datos fiscales nunca están en los documentos ni en el prompt. |
| **Filtro de datos personales en la salida** | Confiar solo en el prompt | Segunda capa: aunque el modelo se equivoque, un teléfono, RFC, CURP, CLABE, tarjeta o correo distinto al público se reemplaza antes de salir. En streaming retiene los últimos 80 caracteres para detectar un dato partido entre dos fragmentos. Solo se registra el tipo de dato, nunca el valor. |
| **Caché del prompt** | Reenviar reglas y resumen completos en cada llamada | Reglas y resumen son idénticos en cada petición y en cada paso del bucle con herramientas: se marcan con `cache_control` y las lecturas de caché cuestan una fracción. Las instrucciones del cliente van en otro bloque, después del punto de caché, para no romperlo. El uso reporta `cached_tokens` como pide Open Responses. |
| **Routing por complejidad** | Un solo modelo para todo | Preguntas directas van al modelo rápido (Haiku) y las que piden análisis o detalle técnico al grande (Opus). En la evaluación, 30 de 34 preguntas se resolvieron con el modelo rápido sin perder exactitud. Si un proveedor falla (conexión, 429 o 5xx) antes de escribir, se reintenta con el otro modelo. |
| **Fallback del servidor ante rechazos** | Fallar la petición | Si el modelo declina por política, el servidor reintenta con otro modelo en la misma llamada. |
| **Capa de compatibilidad del endpoint** | Asumir un solo contrato | La plataforma no publica cómo llama: se acepta `POST /v1/responses`, `/responses` o `/`; la llave como `Bearer`, sin prefijo o `x-api-key`; CORS configurable; `GET /v1/models`; y se registra la forma de cada petición (campos, streaming, historial) sin su contenido, para verificar la integración con evidencia. |
| **Historial y límite en memoria** | Redis | Suficiente para una réplica. Con varias réplicas: Redis para historial con TTL y contadores por llave. |

## Cómo verifico que responde bien

| Comando | Qué mide | Resultado |
|---|---|---|
| `pytest -q` | Protocolo Open Responses (formato, orden de eventos SSE, `[DONE]`), historial, API key, límite de peticiones, bucle del agente con cliente falso, caché y filtro de datos personales (incluido un dato partido entre fragmentos) | 13 pruebas, sin red |
| `python -m evals.run_evals` | Recuperación: ¿la búsqueda trae la sección correcta? | hit@3 = 92% |
| `python -m evals.run_evals --e2e` | De punta a punta contra el modelo: datos clave, sin revelar fuentes internas (archivos o fragmentos), preguntas reformuladas, y **casos adversarios**: pedir teléfono o sueldo, prompt injection, preguntas fuera de tema y preguntas sin dato | 34 de 34 (100%); 79% de los tokens de entrada salieron de caché |
| `python -m evals.juez` | LLM como juez con rúbrica (exactitud, relevancia, privacidad, sin fuentes, seguridad) usando el CV completo como verdad; reporta su concordancia con la verificación por palabras clave | 33 de 34 (97%); exactitud 4.8/5, relevancia 4.9/5 |

La CI (GitHub Actions) corre las pruebas y la compuerta de recuperación en cada cambio.

## Riesgos (OWASP Top 10 para aplicaciones con LLM, 2025)

| Riesgo | Control en este agente | Cómo se prueba |
|---|---|---|
| LLM01 Prompt injection | Reglas antes que las instrucciones del cliente; lo que escribe el usuario o devuelve la herramienta se trata como datos | Casos adversarios en `evals/golden.jsonl` (`--e2e`); `test_system_prompt_...` |
| LLM02 Revelación de información sensible | La base solo tiene información pública y el filtro de salida bloquea teléfono, RFC, CURP, CLABE, tarjetas y correos | `test_redacta_...`, `test_filtro_detecta_un_dato_partido_entre_deltas`, `forbid_re` en las evals |
| LLM03 Cadena de suministro | Dependencias con versión fija; CI en cada cambio | `requirements.txt`, GitHub Actions |
| LLM04 Envenenamiento de datos | La base de conocimiento está versionada en el repo y la revisa el dueño del CV; el agente no aprende de las conversaciones | Revisión en Git |
| LLM05 Manejo inseguro de la salida | La salida es texto plano y pasa por el filtro antes de llegar al cliente | `app/guardrails.py` |
| LLM06 Agencia excesiva | Una sola herramienta, de solo lectura, con argumentos validados y máximo de pasos; el servidor MCP también es de solo lectura | `test_herramienta_valida_argumentos`, `test_agente_respeta_limite_de_pasos` |
| LLM07 Fuga del system prompt | El prompt no contiene secretos; si se filtrara, no expone nada privado | Caso adversario que pide el prompt de sistema (`kind: injection`) |
| LLM08 Debilidades de embeddings | No hay base vectorial: búsqueda léxica sobre documentos curados | N/A hoy; aplica al pasar a búsqueda híbrida |
| LLM09 Desinformación | Prohibido inventar; responde solo con lo recuperado del CV; "no tengo ese dato" cuando falta | Evals de datos clave, preguntas sin dato y preguntas sin dato |
| LLM10 Consumo sin límite | API key, límite por minuto, tamaño máximo de entrada, `max_tokens`, máximo de pasos, recorte del historial y caché | `test_sin_api_key_responde_401`, `test_limite_de_peticiones` |

## Cómo lo llevaría a producción en un banco

Este repo es una réplica única, suficiente para el reto. En un entorno regulado cambiaría:

- **Gateway de LLMs:** una sola salida hacia los proveedores con llaves por equipo, cuotas, routing entre modelos y registro centralizado de costo.
- **Secretos:** llaves en una bóveda (Key Vault, Secrets Manager o Vault) con rotación, nunca en variables de la plataforma.
- **Escala:** contenedores en Kubernetes con varias réplicas; historial y límites en Redis con TTL.
- **Observabilidad:** trazas con OpenTelemetry (latencia, tokens, costo y herramientas por paso) y alertas por error, costo o bloqueos del filtro.
- **Auditoría:** cada interacción con su id de traza, retenida según la política del banco, sin datos personales en los logs.
- **Datos:** la información sensible no sale del perímetro; clasificación de datos antes de indexar y endpoints privados hacia el proveedor.
- **Riesgo de modelos:** ficha del modelo, evals de regresión como compuerta antes de cada despliegue y revisión humana de una muestra de conversaciones.
- **Seguridad:** autenticación con el IdP del banco (OIDC) en lugar de una API key compartida, WAF delante y pruebas de red team periódicas.

## Correrlo

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # ANTHROPIC_API_KEY y AGENT_API_KEY
uvicorn app.main:app --reload
```

```bash
curl -s localhost:8000/v1/responses -H "Authorization: Bearer $AGENT_API_KEY" -H "Content-Type: application/json" -d "{\"input\": \"¿Qué experiencia tiene Joel con IA generativa?\"}"
curl -N localhost:8000/v1/responses -H "Authorization: Bearer $AGENT_API_KEY" -H "Content-Type: application/json" -d "{\"input\": \"¿Ha construido un servidor MCP?\", \"stream\": true}"
```

Con Docker: `docker build -t agente-cv . && docker run -p 8000:8000 --env-file .env agente-cv`.

Despliegue: cualquier plataforma que construya el `Dockerfile` (por ejemplo Railway), con `ANTHROPIC_API_KEY` y `AGENT_API_KEY` como variables de entorno. La URL pública del endpoint es `https://<dominio>/v1/responses`.

## Límites conocidos y siguientes pasos

- Búsqueda léxica: agregar embeddings y fusionarlos con BM25 (búsqueda híbrida).
- LLM como juez: calibrarlo con una muestra revisada a mano y correrlo en la CI como compuerta.
- Routing por heurística: cambiarlo por un clasificador con el modelo rápido, medido contra las evals; y sumar un segundo proveedor (Gemini o Azure OpenAI) para el fallback.
- Historial y límite en memoria: Redis si hay más de una réplica.
- Observabilidad: hoy hay trazas JSON en el log; siguiente paso, enviarlas a OpenTelemetry o Langfuse.
