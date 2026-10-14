# Experiencia: StrideCode (febrero de 2022 a la fecha)

Fundador e Ingeniero de IA y Software. StrideCode (stridecode.com.mx) hace desarrollo de software y ciberseguridad, y productos digitales propios con IA.

## Ochavo: finanzas personales con IA en producción

Ochavo (ochavo.com.mx) es su producto principal, con más de 900 commits. Usa React, Node.js/Express, MySQL, Capacitor (Android), Docker y Railway, con CI en GitHub Actions y pruebas automatizadas. Su IA:

- Asistente de análisis con Claude: arma un resumen de la cuenta del usuario y responde preguntas con detalle. Tiene cuota por quincena, un tope diario por usuario contra abusos, registro de tokens y costo de cada llamada, y si la API falla la consulta no se le cobra al usuario.
- Privacidad por diseño: al modelo solo se le manda lo que el usuario ya ve en la app; nunca números de tarjeta, CLABE ni correo.
- Lector de notificaciones bancarias: Gemini convierte un texto como "Cargo de $250 en OXXO" en datos estructurados (monto, comercio, categoría, fecha) y, si no hay IA disponible, usa reglas.
- Fallback y routing entre modelos: los usuarios Premium usan Claude; el resto, Groq (Mixtral) y Gemini; si todo falla, reglas.
- Lectura de tickets con OCR y captura de gastos por voz.
- Servidor MCP (Model Context Protocol): permite que el asistente de IA de cada usuario consulte su propia cuenta (gastos, ingresos, cuentas, tarjetas, suscripciones y presupuestos). Es de solo lectura por defecto, la escritura se habilita a propósito y solo para registrar un gasto, nunca expone CLABE ni números de cuenta, y el token del usuario nunca se imprime.
- Cada interacción con la IA queda registrada (pregunta, respuesta y modelo) para trazabilidad.

## Otros productos propios

- Tlacuilo: gestión de negocios (ventas, compras, inventario, citas, cocina y delivery) con el mismo motor de análisis con IA y captura por voz.
- La plataforma StrideCode: portal de clientes, gestión de proyectos con SLA y cotizador.
- J-Pay (hackathon, octubre de 2026): prototipo de pagos con agentes de IA usando el SDK de Anthropic con salida estructurada y un libro contable de partida doble con controles de seguridad.

## Colaboraciones

- Full stack, project manager y líder técnico de un configurador y cotizador industrial (MongoDB, Node.js/Express, React/TypeScript, Three.js, SSO con Microsoft Entra ID y exportación al ERP).
- Integración de Uber Eats y Uber Direct en un sistema de pedidos multicanal para un restaurante (Next.js, TypeScript, Supabase): webhooks firmados, idempotencia y auditoría.

## Proyectos para clientes (más de 10 desde 2022)

App para clubes de running con GPS en vivo (en producción), control de combustible con telemetría GPS, gestión documental para un fabricante de dispositivos médicos, sistema de reservas para barberías con cobros (PostgreSQL, Mercado Pago y PayPal) y plataformas de recursos humanos y de pipeline comercial. Despliega con Docker y Railway.
