```markdown
# walkermind-os Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `walkermind-os` Python codebase. You'll learn how to structure files, write and organize code, follow commit message conventions, and implement and run tests. This guide ensures consistency and maintainability across contributions.

## Coding Conventions

### File Naming
- Use **snake_case** for all filenames.
  - Example: `user_manager.py`, `data_processor.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import helper_function
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    def important_function():
        pass

    __all__ = ['important_function']
    ```

### Commit Messages
- Use **conventional commits** with the `fix` prefix for bug fixes.
  - Example:
    ```
    fix: resolve issue with user authentication timeout
    ```

## Workflows

### Code Contribution
**Trigger:** When adding new features or fixing bugs  
**Command:** `/contribute`

1. Create a new branch for your work.
2. Follow the coding conventions (file naming, imports, exports).
3. Write clear and conventional commit messages (e.g., `fix: ...`).
4. Add or update tests as needed.
5. Submit a pull request for review.

### Running Tests
**Trigger:** Before submitting code or verifying changes  
**Command:** `/run-tests`

1. Identify test files (pattern: `*.test.*`).
2. Run all test files using your preferred Python test runner (framework is unknown; try `pytest` or `unittest`).
   - Example:
     ```bash
     pytest
     ```
     or
     ```bash
     python -m unittest discover
     ```
3. Ensure all tests pass before merging.

## Testing Patterns

- Test files follow the pattern: `*.test.*` (e.g., `user_manager.test.py`).
- The specific testing framework is **unknown**; try standard frameworks like `pytest` or `unittest`.
- Place tests alongside the code or in a dedicated tests directory, following the file naming convention.

**Example test file:**
```python
# user_manager.test.py

from .user_manager import important_function

def test_important_function():
    assert important_function() == expected_value
```

## Commands
| Command        | Purpose                                      |
|----------------|----------------------------------------------|
| /contribute    | Start a new code contribution workflow       |
| /run-tests     | Run all tests in the codebase                |
```
