# Truthful, transferable and keyword-aware résumés (Finding 2)

Principle: **Discover the value. Preserve the truth. Communicate the potential.** None of the three may be traded for another.
A job posting is a source of *relevance*, never of *facts about the candidate*.

## The four evidence categories and what the code does with them

| Category | Example | What the system does |
|---|---|---|
| **A. Confirmed experience** | "Handled cash payments." | Kept; wording may be polished, the facts may not change. |
| **B. Confirmed transferable experience** | Cashier → bank teller: cash handling, customer service, transaction accuracy | Planner support `transferable` (needs a stated real activity). The writer shows the real activity in the candidate's own words and may name the underlying skill. The posting's specialised wording is never claimed. |
| **C. Potential, needs clarification** | A cashier "probably" balanced the register | Not claimed. The gap interview is told to ask one short targeted question ("Did you count or reconcile your cash register at the end of your shifts?"). A skipped or unanswered question is never evidence. |
| **D. Unsupported or explicitly denied** | Said **No** to video editing | Support `none`. Never appears as a qualification; stays visible to the candidate as a gap ("not in your profile"). |

"Related" means the **same** activity in other words, never a similar or lesser one. A lesson video is not an e-learning module,
screen recording is not video editing, mentoring a colleague is not working with subject matter experts.

## Where each rule is enforced

1. **Negative answers reach the planner and the writer.** `routes.job_build_resume` → `denials_from_history(qa_history)` →
   `build_checked_resume(..., denials)` → `plan_terms` (listed in the prompt) and `build_tailored_resume` (listed in the writer's request).
   Only an explicit `no` on a yes/no question is a denial; `skip`, blank and free-text answers are not.
2. **Scope-aware code guard** (`resume_quality.denied_by`). A multi-word posting term is forced to `none` only when every distinctive
   word of it sits inside the *gap the question was about* (its category, e.g. "Video editing"). A contrast such as "(beyond simple screen
   recording)" is not part of the denial. One-word terms are never decided by the guard. Adjacent, genuinely evidenced activity is not removed.
3. **Conflicts are flagged, not overridden.** A confirmed fact that repeats a denied question (3+ distinctive words in common) is held back
   from the writer and returned as `answer_conflicts` for the candidate to clarify.
4. **Writer instructions** (`job_match.BUILD_RESUME_SYSTEM_PROMPT`): accuracy over exact keyword insertion; keep the candidate's own wording;
   never rename a duty to match a posting; never upgrade a basic activity into a specialised one; use transferable activity honestly;
   do not mechanically insert every keyword.
5. **Whole-résumé validation** (plain code, no AI):
   - `find_claim_issues`: a posting term the evidence does not establish (or the candidate denied) appearing in the summary, headline or a bullet
     is flagged and handed to the existing single edit pass, which is told to keep what the evidence *does* say instead of substituting another claim.
   - `sanitize_skills`: a skill is removed only if it matches an unsupported (`none`) posting term, or shares **no** distinctive word with the
     candidate's own evidence (so it cannot be traced to anything they said). Supported, transferable and traceable skills stay.
   - Whatever the checks could not fix is returned as `claim_review` and `skills_removed`, and logged (`[career.truth]`); nothing is hidden.

## Last-resort strike and saved review (added after the PR #33 review)

- `term_pipeline.strike_unsupported_claims` runs after the edit pass. Any **sentence** that still states an unsupported or denied posting
  term is removed by plain code (a bullet with nothing left is dropped; a headline phrase is dropped; nothing is substituted), so a
  flagged claim of that kind cannot reach the saved or downloaded resume even when the edit pass is unavailable or incomplete.
  What was struck is returned as `claims_struck` and logged (`[career.truth] sentences_struck=N`).
- The findings are saved with the resume as `resume_data.truth_review` (`answer_conflicts`, `skills_removed`, `claims_struck`, `claim_review`)
  and are returned by `POST /api/career/job-build-resume` and `GET /api/career/resume-versions`. The Word file ignores them.
- Cost: a sentence is struck whole, so a supported fact that shares a sentence with an unsupported claim is lost with it (for example
  "mentored two student teachers as a subject matter resource" loses the true mentoring). The edit pass is tried first precisely to avoid this.
- **Invented figures are struck too** (added after the second PR #33 review): a sentence containing a number, amount or percentage that is not in
  the candidate's profile or confirmed facts is removed, with the reason `figure not in the candidate's evidence` in `claims_struck`. A number
  the evidence spells out ("five sections") also supplies its digit form, so "5 sections" is not mistaken for an invented figure. A true fact in
  the same sentence as the invented figure goes with it.
- Still only flagged, not struck: invented **names** (tools, employers; the name check has a higher false-positive risk), which the quality
  check hands to the edit pass.
- Paraphrases are caught when a sentence uses most of an unsupported term's distinctive words (at least two, and two thirds) and at least one
  of them is not in the candidate's own evidence ("Managed customer bank accounts" for "bank account servicing"; "subject matter resource" for
  "subject matter experts"). A sentence made only of the candidate's own words is never struck by this rule.
- Still not caught: a paraphrase that shares too few words with the planned term ("Polished each lesson recording"), and an invented **duty**
  that is not a posting term and not a denied topic.

## Known limits (be honest about these)

- **Prose is checked only against planned posting terms and denials.** A fabricated duty that is *not* a posting term and not a denied
  topic (for example an invented achievement in a bullet) is **not** caught by code; it relies on the writer prompt and the existing
  number/name checks. This is a false-negative risk.
- **The guard cannot see synonyms.** A denial whose gap name shares no words with the posting term (for example a "No" to "working with a
  non-teaching expert" versus the posting term "subject matter experts") is only honoured if the planner marks that term `none`, which it is
  told to do. The tests assume a compliant planner; a non-compliant model could still support such a term.
- **Over-removal risk (false positives).** A multi-word term wholly inside a denied gap is removed even if the candidate has a nearby
  genuine activity (for example "video production" after a No to "video editing"). A skill with zero shared words is removed even if it is a
  legitimate derived label. The candidate can restore a term by confirming it.
- **Word matching is simple** (five-letter stems). Rare spelling variants can be missed in either direction.
- **The checks cannot prove a live model's wording.** The automated tests replace the AI with fixed answers and verify the code around it.
  Only a live rerun shows what the model writes under the new instructions.
- **The interface does not yet show `answer_conflicts`, `claims_struck` or `claim_review`** to the candidate; they are returned by the API, saved with the resume as `truth_review`, and logged.
- A **previously saved profile skill** that the candidate later denies for a specific job is overridden for that job's résumé only; it is not
  edited in the profile.
