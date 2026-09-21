# QA Fixture: RIGHTFIT-02 (Huntington — Solutions Consultant/Integrations)

**Status: QA FIXTURE NEEDS SOURCE TEXT**

## Why this fixture exists

The RIGHTFIT-02 regression test (Right Fit run against a Huntington "Solutions
Consultant/Integrations" posting, resume: `William.James.Resume.pdf`) depends
on the full text of a real job description. That description was originally
supplied only as a live external URL:

```
https://huntington-careers.com/search/jobdetails/solutions-consultantintegrations/479ccdaa-75c0-4824-a066-39c035491486
Reference: R0070387
```

As of the QA baseline run, that URL returns "Job No Longer Available" and no
Wayback Machine snapshot exists. The full original posting text was never
successfully fetched or saved anywhere in this project's history — it does
not exist in any prior QA notes, commit, or session record available to this
fixture.

**No replacement text has been created.** Per QA instructions, the original
posting must not be recreated or invented — doing so would defeat the point
of a regression fixture (it needs to be the *real* posting, not an
approximation).

## What the test was designed to check

The posting's title said "Solutions Consultant/Integrations," but its actual
responsibilities reportedly emphasized product roadmap ownership, backlog/
epic definition, prioritization, OKRs, investment tracking, and managing
Product Owners. The test's purpose was to confirm Right Fit analyzes the
JOB DESCRIPTION content, not just the title — i.e., that it wouldn't see the
word "Integrations" and declare an easy match without reading the actual
responsibilities.

## What's needed to activate this fixture

To make RIGHTFIT-02 runnable without depending on a live external URL again:

1. Obtain the full, verbatim original posting text (a saved copy, screenshot
   transcription, or archived version from whoever originally sourced it).
2. Save it as `rightfit-02-huntington-posting.txt` alongside this file.
3. Update this document's status line to reflect the fixture is complete.

Until then, RIGHTFIT-02 remains blocked for regression purposes, and this is
an external-content gap, not an application defect.

**This directory is QA/testing documentation only — it is not served by the
application and contains no production content.**
