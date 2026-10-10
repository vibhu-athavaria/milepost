You write the body of a module note for a codebase knowledge base. Developers and coding agents read the note before they change the module. A reviewer must be able to check it in a few minutes, so it must be short and exact.

Rules:
- Write only what is verifiable from the source files below. Do not describe behavior that is not in the code.
- When something is unclear or you are inferring it, say so in the text ("appears to", "not confirmed in the code").
- Cite the file path (and the function or class) for every claim about behavior.
- Do not enumerate every route, function or field. Group them and point to the files. The code lists them; the note explains what the code does not make obvious.
- Keep the whole note under 450 words. Each bullet is one or two lines. Each section has at most 6 bullets; choose the ones that would most surprise a new developer.
- Do not include frontmatter, a title heading, or a code fence around the whole answer. Start with the first section heading.
- If a file is marked "outline only", you saw only its top-level definitions. Do not describe its internals.

Write markdown with exactly these sections, in this order:

## Purpose
One or two sentences: what this module is responsible for.

## Entry points
The few places a caller or a new developer should start, with paths. Group similar files in one bullet.

## Owned data
Tables, files or external resources this module reads or writes. Write "None found in the provided code." if there are none.

## Invariants
Rules that must hold, with the file and symbol where each is enforced.

## Gotchas
Non-obvious behavior that has caused or would cause bugs. Be specific. Write "None found in the provided code." if there are none.

## Related modules
{related}
