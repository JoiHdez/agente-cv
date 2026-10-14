"""La misma base de conocimiento expuesta por MCP, para conectarla a cualquier cliente MCP u otro agente.

Uso: python -m app.mcp_server   (transporte stdio). Solo lectura.
"""
from mcp.server.mcpserver import MCPServer

from app import conocimiento

server = MCPServer(name="cv-joel", instructions="CV profesional de Joel Hernández Contreras. Solo lectura.")


@server.tool(description=conocimiento.TOOLS[0]["description"])
def buscar_en_cv(consulta: str, k: int = 3) -> str:
    return conocimiento.buscar_en_cv(consulta, k)


@server.tool(description="Resumen del CV de Joel: perfil, competencias, idiomas y formación.")
def resumen_cv() -> str:
    return conocimiento.RESUMEN


if __name__ == "__main__":
    server.run()
