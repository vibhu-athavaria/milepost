You write the body of a module note for a codebase knowledge base. Developers and coding agents read the note before they change the module. A reviewer must be able to check it in a few minutes, so it must be short and exact.

Rules:
- Write only what is verifiable from the source files below. Do not describe behavior that is not in the code.
- When something is unclear or you are inferring it, say so in the text ("appears to", "not confirmed in the code").
- Cite the file path (and the function or class) for every claim about behavior.
- Do not enumerate every route, function or field. Group them and point to the files. The code lists them; the note explains what the code does not make obvious.
- Keep the whole note under 600 words. Each bullet is one or two lines. Entry points, Invariants and Gotchas have at most 6 bullets each; choose the ones that would most surprise a new developer.
- Put every file or symbol you mention in backticks, for example `routes/auth.py` or `routes/auth.py::login`. Tooling uses these citations.
- Do not include frontmatter, a title heading, or a code fence around the whole answer. Start with the first section heading.
- If a file is marked "outline only", you saw only its top-level definitions. Do not describe its internals.

Write markdown with exactly these sections, in this order:

## Purpose
One or two sentences: what this module is responsible for.

## Entry points
The few places a caller or a new developer should start, with paths.

## File map
One line per source file saying what it does. For a module with more than 15 files, one line per folder or group of similar files instead. Do not list functions.

## Owned data
Tables, files or external resources this module reads or writes. Write "None found in the provided code." if there are none.

## Invariants
Rules that must hold, with the file and symbol where each is enforced.

## Gotchas
Non-obvious behavior that has caused or would cause bugs. Be specific. Write "None found in the provided code." if there are none.

## Related modules
{related}
