You write the body of a module note for a codebase knowledge base. Developers and coding agents read the note before they change the module, so it must be accurate and short.

Rules:
- Write only what is verifiable from the source files below. Do not describe behavior that is not in the code.
- When something is unclear or you are inferring it, say so in the text ("appears to", "not confirmed in the code").
- Cite the file path (and the function or class) for every claim about behavior.
- Do not include frontmatter, a title heading, or a code fence around the whole answer. Start with the first section heading.
- If the files are marked "outline only", you saw only their top-level definitions. Do not describe their internals.

Write markdown with exactly these sections, in this order:

## Purpose
One or two sentences: what this module is responsible for.

## Entry points
Routes, public functions or services a caller uses first, with paths.

## Owned data
Tables, files or external resources this module reads or writes. Write "None found in the provided code." if there are none.

## Invariants
Rules that must hold, with the file and symbol where each is enforced.

## Gotchas
Non-obvious behavior that has caused or would cause bugs. Be specific. Write "None found in the provided code." if there are none.

## Related modules
{related}
