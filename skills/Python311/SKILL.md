---
name: python311-compat
description: Python 3.11 compatibility guard. Use this skill BEFORE writing ANY Python code, scripts, or fixes. Prevents common syntax errors that cause scripts to fail. Triggers on any Python file creation, editing, or generation. Covers walrus operators, f-strings, match statements, exception groups, type annotations, and other 3.10+ features that have nuanced behavior in 3.11. ALWAYS consult this when writing Python for the Tower bot or any user project.
---

# Python 3.11 Compatibility Skill

**STOP** before writing Python. Check this skill to avoid syntax that will crash on Python 3.11.

## Golden Rules

1. **ALWAYS test-parse your code mentally before writing it**
2. **NEVER use features from Python 3.12+** 
3. **AVOID edge cases even in 3.11-supported features**

---

## FORBIDDEN - Will Crash

### 1. Type Parameter Syntax (3.12+)
```python
# WRONG - Python 3.12+ only
def func[T](x: T) -> T: ...
class Box[T]: ...

# CORRECT - Python 3.11
from typing import TypeVar, Generic
T = TypeVar('T')
def func(x: T) -> T: ...
class Box(Generic[T]): ...
```

### 2. F-String Expressions with Backslashes
```python
# WRONG - breaks in 3.11
path = f"C:\Users\{name}\file"  # backslash in f-string

# CORRECT
path = f"C:\\Users\\{name}\\file"
# OR
path = "C:\\Users\\" + name + "\\file"
```

### 3. F-String Quote Nesting (complex cases)
```python
# RISKY - can fail depending on complexity
f"He said {d['key']}"  # quotes inside f-string

# SAFER
value = d['key']
f"He said {value}"
```

### 4. Match Statement Edge Cases
```python
# Match is 3.10+ but watch for:
# WRONG - using match on unsupported patterns
match obj:
    case {"key": str() as s}:  # complex patterns can fail
        ...

# SAFER - use if/elif for complex logic
if isinstance(obj, dict) and "key" in obj:
    s = obj["key"]
```

### 5. Exception Groups (3.11 has them BUT)
```python
# WRONG - ExceptionGroup syntax without proper handling
except* ValueError:  # 3.11+ but tricky
    ...

# CORRECT - standard exception handling
except ValueError:
    ...
```

---

## SAFE PATTERNS for 3.11

### Walrus Operator `:=` - SAFE in 3.11
```python
# OK
if (n := len(data)) > 10:
    print(f"Got {n} items")

# OK in comprehensions
[y for x in data if (y := process(x))]
```

### Standard Type Hints - SAFE
```python
from typing import Optional, Union, List, Dict

def func(x: Optional[str] = None) -> List[int]:
    ...
```

### Dataclasses - SAFE
```python
from dataclasses import dataclass, field

@dataclass
class Config:
    name: str
    items: list = field(default_factory=list)
```

### F-Strings Basic - SAFE  
```python
name = "world"
f"Hello {name}"
f"Value: {x + 1}"
f"Items: {len(items)}"
```

---

## JSON Handling Best Practices

When writing JSON manipulation code:

```python
import json

# CORRECT - explicit encoding
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# CORRECT - writing with proper formatting
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

---

## File Operations

```python
from pathlib import Path

# CORRECT - pathlib for cross-platform
path = Path(__file__).parent / "data" / "file.json"

# CORRECT - explicit encoding always
content = path.read_text(encoding='utf-8')
path.write_text(content, encoding='utf-8')
```

---

## Regex Patterns

```python
import re

# CORRECT - raw strings for regex
pattern = r'"status":\s*"[^"]*"'

# CORRECT - re.DOTALL for multiline
re.sub(pattern, replacement, content, flags=re.DOTALL)
```

---

## Pre-Flight Checklist

Before saving ANY Python file:

- [ ] No `[T]` type parameter syntax
- [ ] No complex f-string quote nesting
- [ ] No backslashes inside f-string braces
- [ ] No `except*` exception groups (unless certain)
- [ ] All file operations have `encoding='utf-8'`
- [ ] Using raw strings `r"..."` for regex
- [ ] Imports are standard library or installed packages

---

## Quick Reference: Version Features

| Feature | Min Version | Safe in 3.11? |
|---------|-------------|---------------|
| Walrus `:=` | 3.8 | ✅ Yes |
| Positional-only `/` | 3.8 | ✅ Yes |
| Match statement | 3.10 | ✅ Yes |
| Union `X \| Y` | 3.10 | ✅ Yes |
| ParamSpec | 3.10 | ✅ Yes |
| ExceptionGroup | 3.11 | ⚠️ Careful |
| `except*` | 3.11 | ⚠️ Careful |
| Type params `[T]` | 3.12 | ❌ NO |
| f-string any quote | 3.12 | ❌ NO |

---

## When This Skill Triggers

Use this skill when:
- Creating Python scripts
- Writing Python code blocks
- Generating fix scripts
- Editing Python files
- Any `.py` file operation

**Bottom line: When in doubt, use simpler syntax. Python 3.11 is stable but not bleeding edge.**
