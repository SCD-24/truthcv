# Global Guidelines & Standards

Define general standards, style guides, and testing rules for your AI agents to follow across the entire project codebase.

## Coding Standards
- **Functions should aim to be less than** `25` lines
- **Require clear docstrings explaining the 'why' rather than 'what' for all public APIs**
- **Avoid deep nesting of code; limit to maximum** `3` levels

### Custom Guidelines
- **Function Size**: Prefer short, modular functions (under 25 lines). Refactor long blocks into shared utilities.
- **Naming Conventions**: Use clean, descriptive names (camelCase for JavaScript, snake_case for Python, PascalCase for classes).
- **Comments**: Write clear docstrings for all exported functions and API routes. Explain the *why*, not just the *what*.

## Testing & Validation
- **Target a minimum unit test coverage of** `80` %

### Custom Guidelines
- **Coverage Goal**: Target at least 80% unit test coverage for all custom business logic.
- **Frameworks**: Use Jest for Frontend assets, Vitest/Jest for Node, and testing package for Go.
- **Integration Tests**: Ensure each component has happy-path integration tests for its REST or gRPC endpoints.

## AI Agent Execution Rules
*No specific guidelines active for this category.*

