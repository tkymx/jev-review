# How far can you trust Jev? Measurements

[日本語](findings.ja.md)

## Summary

**Jev answers more than 90% of questions correctly when each one asks about a single fact you can see in the code, but it loses accuracy when conditions are combined, when the kind of problem is not named, and when the question is abstract, so with narrow, concrete questions it works as a first pass before a person or an LLM reads the change.**

| | |
|---|---|
| Background | Having an LLM review every change in full is slow and expensive. Jev returns only a yes-probability per question, in about 0.3 seconds and for well under a cent. |
| Goal | Find out how accurate Jev stays when you add more viewpoints, cover many kinds of code, or ask abstract questions. |
| Method | 72 labeled cases in 10 languages and formats: code with exactly one planted problem, and clean code. We changed one thing about the questions at a time and scored the answers. 2,578 calls, about $0.36. |
| Results | Single-fact questions were 99% correct. 387 viewpoints did not hurt accuracy. Four conditions joined with AND dropped to 73%, unnamed kinds were mostly missed, and abstract questions fired on unrelated problems. |
| Conclusion | Ask one thing, ask for presence, and name what you want found. Use Jev to narrow a change down; leave the final call to a person or an LLM. |

Model: `jev-1.13.0`. Measured on 2026-09-23. The questions in the study were written in Japanese; the bundled English viewpoints were checked on the same samples (below).

## Terms

- **p**: Jev's probability that the answer is yes (0–1). We counted p >= 0.5 as yes.
- **Recall**: the share of real problems answered yes.
- **False positive**: a yes on code without the problem.

## What Jev does well

**Single facts.** Sixteen questions such as "is there a return statement?" or "is there a loop?", asked about 18 pieces of code: 99% correct. For problems visible in the text (dangerous calls, secrets) the right question averaged p = 0.97.

**Many viewpoints at once.** Growing one call from 6 to 387 questions kept detection of the original six at 89–92% and latency at 0.3–0.4 s. Only input tokens grow, about 38 per question.

**Stable answers.** Asking the same thing three times varied by ±0.005–0.013. Averaging three runs did not raise recall. One call is enough.

**Exceptions ("ignore X").** With zero to three exceptions, real violations stayed at p 0.96–0.98, and code covered by an exception flipped to no (a print inside a test: 0.97 → 0.15). Two weaknesses:

- The last exception in the list works least well (constant-only concatenation: 0.26 when first, 0.68 when last).
- **An exception spreads to cases that look similar.** "Ignore keys that are public by design, such as a Firebase web config" also cleared a Google key hard-coded in Swift (0.97 → 0.24). Scoping the exception by something visible, "the apiKey inside a JavaScript firebaseConfig object", brought Swift back to 0.95 while the Firebase config stayed at 0.12.

**Concrete team rules.** Seven rules ("estimate the cost before calling a paid API", ...) pasted into questions all separated violations from the rest at 0.5. The more abstract the rule, the higher the p on unrelated code: at most 0.11 for concrete rules, 0.44 for abstract ones.

## What Jev does badly

**AND.** Recall on cases where all conditions hold: 96% with one condition, 90% with two, 81% with three, 73% with four. Nested logic (A and (B or C)) was 84% correct. Asking each condition separately and combining in code gave 97% for nested logic and raised the overall rate from 95.3% to 97.9%. OR alone was fine when asked directly (99.7%).

**Unnamed kinds.** Under "is there a dangerous call such as eval, shell execution or SQL concatenation?", an XSS hunk scored 0.04; naming innerHTML gave 0.94. Recall by language: TypeScript, SQL and Swift 100%, Python 92%, JavaScript 80%, Dockerfile 50%, GitHub Actions 33%. Every miss was a form missing from the examples (continue-on-error, curl | bash, `${{ github.event.* }}` inside `run:`). Splitting injection into eight fine-grained questions worked: the highest p was the right kind in 10 of 11 cases, though neighbouring kinds sometimes fired too.

**Abstract questions.** Area-level questions ("any security issue?", "any cost risk?") also fired on problems of other kinds 35–76% of the time. "Is this safe to merge?" never passed a defective change but stopped 47% of clean ones.

**Absence.** "Is a timeout missing?" or "is a doc comment missing?" answered yes on 77% of clean code, against 3% for presence questions. When the thing was in the hunk, Jev correctly said no; a hunk simply rarely shows it.

**Intent.** Logic-bug questions averaged p = 0.65. An inverted comparison (`expires_at > now`) was missed under every condition.

**Subjective quality.** Across eight good/bad pairs differing in one respect, "is this maintainable?" ranked the good version higher every time, but a 0.5 cut-off was right only 54–75% of the time.

## Usage notes

- **Send one hunk at a time.** Adding 2k unrelated tokens lowered recall from 92% to 86%; 28k, to 89%. Buried in the middle of a long input: 83%.
- **Ask all questions in one call.** 24 questions in one call, four calls or six calls: same recall (89–92%), 1.8x and 2.4x the tokens.
- **Reading p.** At p >= 0.9, 97% were real; 0.7–0.9 about 75%; 0.5–0.7 about 48%; below 0.1, 0%. Moving the red line from 0.5 to 0.7 raised precision from 83% to 90% and lowered recall from 90% to 81%.

## Rules for writing questions

1. Ask one thing per question. Combine in code (`[[rule]]`).
2. Ask for presence. Leave absence checks to someone who can read the surrounding code.
3. Name what you want found, including each language's form.
4. At most three exceptions, most important first, scoped by something visible such as a file or object name.
5. Do not pass or fail a change on abstract or subjective questions.
6. One hunk per call, all questions in that call.
7. Red at 0.7, yellow at 0.5. A person or an LLM makes the final call.

## Limits of this study

- 72 hand-made cases. Real projects may behave differently.
- The "named" questions were written after seeing the cases, so they are optimistic.
- Abstract team rules had only one or two violating cases each.
- Three exception cases were dropped from scoring because Jev's reading was more reasonable than our label.
- One model version, `jev-1.13.0`.

## Bundled viewpoints

`core.ja` / `core.en` (15 checks, written by the rules above) on the 61 cases in [samples/](../samples/):

| | Red (p >= 0.7) as a hit | Yellow (p >= 0.5) as a hit |
|---|---|---|
| core.ja | all 61 correct (recall 100%, false positives 0%) | recall 100%, false positives 0.5% (4, p 0.51–0.67) |
| core.en | all 61 correct (recall 100%, false positives 0%) | recall 100%, false positives 0.2% (2, p 0.51–0.55) |

The samples are the cases the viewpoints were written against, so read these as an upper bound.
