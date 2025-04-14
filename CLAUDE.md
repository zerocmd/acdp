# CLAUDE.md - Agent Name Server Guidelines

## Build/Test Commands
- Start services: `docker-compose up -d`
- View service logs: `docker compose logs [service_name]`
- Test DNS resolution: `dig @localhost -p 5353 _llm-agent._tcp.agent1.agents.local SRV`
- Check agent health: `curl http://localhost:8001/health`
- View peers: `curl http://localhost:8001/peers`
- View registry dashboard: http://localhost:5001

## Code Style Guidelines
- **Imports**: Group standard library, third-party, and local imports with blank lines between groups
- **Formatting**: Use 4 spaces for indentation
- **Types**: Use type hints for function parameters and return values (PEP 484)
- **Naming**: snake_case for variables/functions, PascalCase for classes
- **Error handling**: Use try/except with specific exceptions, include detailed error messages
- **Documentation**: Use Google-style docstrings for modules, classes, and functions
- **Logging**: Use Python logging module with appropriate levels

## Environment Setup
- Set `ANTHROPIC_API_KEY` in environment before running code
- Use Docker Compose for local development environment
- Configure agent properties via environment variables or in agent/config.py