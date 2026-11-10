# CV & Cover-Letter Style Guidelines

Distilled writing guidance for generating tailored CVs and cover letters. These
are **style rules only** — phrasing, structure, tone, formatting. They contain
**no facts about any person, employer, institution, or date**. Nothing here is a
source of content: every factual claim in a generated document must still come
from the user's truth store and pass the guardrail. These guidelines only shape
*how* the user's own verified facts are phrased and arranged.

Sourced by distilling public university career-office writing guides; all
specific examples, names, and identifiers were removed on purpose.

## Language

- Be **specific, not general**; **active, not passive**.
- Write to **express, not impress** — articulate, not flowery.
- Be **fact-based**: quantify and qualify outcomes where the fact supports it.
- Write for readers *and* systems that scan quickly (ATS-friendly).
- **No personal pronouns** ("I", "we") in CV bullets.
- Do not abbreviate obscurely; no slang or colloquialisms.
- Never use a narrative style in a CV (that is for the cover letter).

## Bullet structure

- Start each bullet with a strong **action verb** (see the bank below).
- Prefer the shape: **action → contribution/scope → impact/result.** Include the
  goal, the candidate's contribution, and the outcome when the facts support it.
- Do **not** start a line with a date.
- Demonstrate **results**, not just responsibilities.

## Structure & ordering

- List section headings in **order of importance**; put the most relevant section
  to the target role first. Material early in the document stands out most.
- Within a section, list entries in **reverse chronological order** (most recent
  first).
- Make the 3–4 most notable, role-relevant skills/achievements easy to spot near
  the top.
- Keep a **consistent** format throughout (spacing, emphasis, capitalization).
- Avoid unexplained gaps in a timeline.

## Formatting

- Easy-to-read font; generous white space; descriptive headings/subheadings.
- Consistent use of bold/italic/underline for emphasis only.
- Must convert cleanly to PDF (single column, selectable text, no tables/images
  for ATS).

## Common headings (use those that apply to the user's facts)

Name & Contact · Education · Experience · Research Experience · Teaching
Experience · Leadership & Activities · Skills · Publications · Presentations ·
Awards/Honors · Languages. Choose and order by relevance to the posting; never
invent a section the user has no facts for.

## Cover-letter guidelines

- A cover letter is a **marketing writing sample** — concise and factual, no more
  than one page.
- Address a specific person when known; otherwise a role-appropriate greeting.
- **Tailor to the specific organization and posting**: reference skills/
  experiences from the job description and draw connections to the candidate's
  real credentials.
- Give concrete **examples that support** the candidate's skills — but every such
  example must be a fact from the truth store.
- Avoid flowery language; use plenty of action words; **don't overuse "I".**
- Structure: opening (who you are + the role you're applying for) → 1–2 body
  paragraphs connecting real experience to the posting's needs → brief closing.
- Same font/formatting family as the CV; must convert cleanly to PDF.

## Action-verb bank (by category)

- **Leadership:** Led, Directed, Oversaw, Coordinated, Spearheaded, Orchestrated,
  Managed, Chaired, Delegated, Executed, Prioritized, Strengthened, Improved,
  Increased, Consolidated, Organized, Planned, Reorganized, Supervised.
- **Communication:** Authored, Presented, Negotiated, Persuaded, Influenced,
  Collaborated, Drafted, Edited, Mediated, Promoted, Recruited, Reported,
  Synthesized, Translated, Delivered, Moderated.
- **Research:** Analyzed, Investigated, Evaluated, Identified, Determined,
  Conducted, Interpreted, Modeled, Examined, Surveyed, Tested, Concluded,
  Diagnosed, Extracted, Summarized.
- **Technical:** Built, Designed, Engineered, Programmed, Optimized, Streamlined,
  Standardized, Automated, Maintained, Upgraded, Assembled, Computed, Solved,
  Devised.
- **Quantitative:** Analyzed, Budgeted, Calculated, Forecasted, Managed,
  Maximized, Minimized, Projected, Allocated, Audited.
- **Creative:** Created, Designed, Conceived, Founded, Initiated, Introduced,
  Invented, Originated, Redesigned, Revitalized, Shaped, Established.
- **Organizational:** Implemented, Launched, Compiled, Generated, Monitored,
  Processed, Reduced, Simplified, Structured, Systematized, Streamlined,
  Expanded, Consolidated.
- **Teaching/Helping:** Coached, Advised, Facilitated, Guided, Instructed,
  Mentored, Trained, Enabled, Supported, Motivated, Demonstrated.

## AI-slop patterns to avoid

Distilled from the no-ai-slop skill; `truthcv/engines/prompts/style.py` (`cv_anti_slop()` /
`letter_anti_slop()`) is the executable copy of these bans, so change both
together. Patterns marked "humanizer" are adapted from humanizer SKILL.md v3.1.0
(MIT, github.com/blader/humanizer). The CV humanizer rules are rendered by
`truthcv/engines/prompts/tailor.py` (`_cv_humanizer_rules()`); the letter humanizer rules are
rendered by `truthcv/engines/prompts/style.py` (`_letter_humanizer_rules()`). The banned-word
list in both comes from `STRICT_TELL_WORDS` in `truthcv/engines/prompts/style.py`. Every rule
below adds no facts; it changes style only.

**Both surfaces**

- Apply the portability test to every sentence: if it could move unchanged to
  another person, company, or product, cut it or replace it with a specific
  fact.
- Show, don't tell: never label a point as important, notable, key, or worth
  noting; let the fact carry the weight.
- No weasel attribution: industry-leading, widely regarded as, world-class,
  experts agree.
- No fake-strong verbs or abstraction: prefer "tracks sponsors, drafts, and
  due dates" over "serves as a centralized hub for sponsor management".
- No synonym cycling: repeat the clear word rather than rotating terms.
- No vague-scale words standing in for a number: significantly, substantially,
  various, numerous, a wide range of, unless the number is present in the
  referenced fact.
- No negative listing ("not a X, not a Y, a Z") and no rhetorical setups.

**CV bullets**

- Keep each bullet a single complete statement; no dramatic fragmentation.
- No -ing riders (humanizer): no trailing clause bolted onto a bullet, such as
  ", ensuring X", ", driving Y", ", highlighting", ", showcasing", ", fostering",
  ", reflecting", or ", contributing to". A result is its own clause only if
  the fact states it.
- No vague association (humanizer): no "involved in", "associated with", or
  "contributed to" when the fact names the actual role or action. A vague fact
  stays vague; a role is never invented.
- No inflated significance (humanizer): no "played a key role", "pivotal",
  "instrumental in", "marking a", or "setting the stage".
- No banned words (humanizer): every `STRICT_TELL_WORDS` entry, plus crucial,
  valuable, enhance, and highlight (as a verb).

**Cover letters**

- No summary-recap ending: In conclusion, Ultimately, Overall, or a final
  paragraph restating the letter; end on the last concrete point or a plain
  next step.
- No fake-profound closing metaphor or aphorism.
- No hollow adverbs: successfully, effectively, efficiently, strategically,
  proactively.
- No -ing riders, vague association, inflated significance, or banned words
  (humanizer): the same rules as the CV bullets above, applied to every
  sentence of the letter.
- No staged run-ups (humanizer): "Here's the thing", "Let's dive in",
  "Honestly?", "To be clear", or "Let me be clear".
- No chatbot residue in the letter body (humanizer): "Here is your cover
  letter", "I hope this helps", "Certainly", or "Let me know if you'd like".

## Hard rule (truthfulness)

These guidelines never override the truth store. When generating a CV line or a
cover-letter claim, use ONLY facts present in the user's truth (or approved
inferences). Do not import any name, employer, school, metric, date, or
achievement from these guidelines or their source material — they are style, not
content.
